import csv
import io
import json
import math
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db
from .engine import calculate, today, Quotes
from .importer import import_files, seed_initial_statement_navs, now, ident, day
from .providers import refresh_prices, save_prices, INDEXES
from .review import duplicate_groups, resolve_group, change_exclusion, edit_lock

job_lock = threading.Lock()
job = {"running": False, "message": "Ready", "completed": 0, "total": 0, "errors": []}
stop = threading.Event()
server_instance = uuid.uuid4().hex
data_revision = str(time.time_ns())


@lru_cache(maxsize=16)
def snapshot(people, start, end, fund, detailed=False):
    return calculate(list(people) if people is not None else None, start, end, fund, detailed)


def invalidate():
    global data_revision
    snapshot.cache_clear()
    data_revision = str(time.time_ns())


def job_status():
    return dict(job, server_instance=server_instance, data_revision=data_revision)


def refresh():
    if not job_lock.acquire(blocking=False):
        return
    job.update(running=True, message="Importing transaction files", completed=0, total=1, errors=[], started=now())
    db.set_setting("last_attempt", now())
    db.set_setting("refresh_in_progress", "1")
    errors = []
    try:
        with edit_lock:
            result = import_files()
        errors.extend(result["errors"])
        invalidate()
        if not errors:
            def progress(message, completed, total):
                job.update(message=message, completed=completed, total=total)
            errors.extend(refresh_prices(progress))
            seed_initial_statement_navs()
        db.set_setting("last_refresh", now())
        db.set_setting("last_refresh_errors", json.dumps(errors))
    except Exception as exc:
        errors.append(str(exc))
        db.set_setting("last_refresh_errors", json.dumps(errors))
    finally:
        db.set_setting("last_refresh", now())
        db.set_setting("refresh_in_progress", "0")
        invalidate()
        job.update(running=False, message="Refresh finished" if not errors else "Refresh finished with data gaps", errors=errors, finished=now())
        job_lock.release()


def schedule():
    if stop.wait(3):
        return
    while not stop.is_set():
        if os.getenv("AUTO_REFRESH", "1") == "1":
            local = datetime.now(ZoneInfo("Asia/Kolkata"))
            scheduled_day = local.date() if local.hour >= int(os.getenv("REFRESH_HOUR", "7")) else local.date() - timedelta(days=1)
            last = db.setting("scheduled_day")
            if last != scheduled_day.isoformat() or db.setting("refresh_in_progress") == "1" or not db.setting("last_refresh"):
                db.set_setting("scheduled_day", scheduled_day.isoformat())
                refresh()
        stop.wait(30)


@asynccontextmanager
async def lifespan(app):
    db.init()
    import_files()
    stop.clear()
    threading.Thread(target=schedule, daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Portfolio", lifespan=lifespan, docs_url="/api/docs")


@app.middleware("http")
async def same_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in {"POST", "PUT", "DELETE", "PATCH"} and origin and urlsplit(origin).netloc != request.headers.get("host"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Cross-origin mutations are disabled"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/") or request.url.path in {"/", "/index.html"}:
        response.headers["Cache-Control"] = "no-store"
    return response


def params(people, start, end, fund, detailed=False):
    selected = tuple(sorted(filter(None, people.split(",")))) if people is not None else None
    known = {r["id"] for r in db.rows("SELECT id FROM people")}
    if selected is not None and not set(selected) <= known:
        raise HTTPException(400, "Unknown person")
    for value in (start, end):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(400, "Dates must use YYYY-MM-DD")
    if start and end and start > end:
        raise HTTPException(400, "Start date must precede end date")
    return snapshot(selected, start, end, fund, detailed)


@app.get("/api/health")
def health():
    return {"status": "ok", "timezone": "Asia/Kolkata"}


@app.get("/api/meta")
def meta():
    people = db.rows("SELECT * FROM people ORDER BY name")
    for p in people:
        p["pan"] = "••••••" + p["pan"][-4:]
    return {"people": people, "indices": [{"id": key, "name": label} for key, label in INDEXES.items()], "schemes": db.rows("SELECT * FROM schemes ORDER BY name"), "sources": db.rows("SELECT * FROM sources ORDER BY path"), "provider_notes": db.rows("SELECT message FROM issues WHERE category IN ('provider','reconciliation') ORDER BY source"), "last_refresh": db.setting("last_refresh"), "refresh_errors": json.loads(db.setting("last_refresh_errors", "[]")), "today": today().isoformat(), "job": job_status()}


@app.get("/api/dashboard")
def dashboard(people: str | None = None, start: str | None = None, end: str | None = None, fund: str | None = None):
    result = dict(params(people, start, end, fund))
    groups = duplicate_groups(people.split(",") if people is not None else None, start, end, fund)
    result["review_summary"] = {"unresolved": sum(g["unresolved"] for g in groups), "total": len(groups)}
    return result


@app.get("/api/review")
def review(people: str | None = None, start: str | None = None, end: str | None = None, fund: str | None = None):
    result = params(people,start,end,fund)
    return {"groups": duplicate_groups(people.split(",") if people is not None else None, start, end, fund), "blocking_issues": result.get("ledger_errors", [])}


@app.get("/api/funds/compare")
def compare_funds(funds: str, people: str | None = None, start: str | None = None, end: str | None = None, indices: str | None = None):
    from .comparison import market_performance
    ids = list(dict.fromkeys(filter(None,funds.split(','))))
    known = {s['id']:s['name'] for s in db.rows('SELECT id,name FROM schemes')}
    if not ids or not set(ids) <= known.keys():
        raise HTTPException(400,'Choose at least one known fund')
    indexes = list(INDEXES) if indices is None else list(dict.fromkeys(filter(None,indices.split(','))))
    if not set(indexes) <= INDEXES.keys():
        raise HTTPException(400,'Unknown comparison index')
    basket = params(people,start,end,ids[0] if len(ids)==1 else tuple(sorted(ids)))
    per_fund = []
    for sid in ids:
        r = params(people,start,end,sid)
        per_fund.append({'id':sid,'name':known[sid],'holding':next((f for f in r['funds'] if f['scheme']==sid),None),'summary':r['summary'],'benchmarks':[{k:v for k,v in b.items() if k!='series'} for b in r['benchmarks'] if b['id'] in indexes],'lots':r['lots'],'issues':r['issues']})
    investment = {key:basket.get(key,[]) for key in ['summary','series','yearly','yearly_funds','lots','transfer_details','cashflows','issues','ledger_errors']}
    investment['benchmarks'] = [b for b in basket['benchmarks'] if b['id'] in indexes]
    return {'funds':per_fund,'investment':investment,'performance':market_performance(ids,indexes,start,end)}


class ReviewChoice(BaseModel):
    group_id: str
    keep_ids: list[str] = Field(min_length=1)
    note: str = Field(default="", max_length=1000)


@app.post("/api/review/resolve")
def resolve_review(choice: ReviewChoice):
    if job["running"]:
        raise HTTPException(409, "Wait for the current refresh before changing review decisions")
    try:
        result = resolve_group(choice.group_id, choice.keep_ids, choice.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    invalidate()
    return result


@app.get("/api/refresh")
def refresh_status():
    return job_status()


@app.post("/api/refresh", status_code=202)
def start_refresh():
    if not job["running"]:
        job["running"] = True
        threading.Thread(target=refresh, daemon=True).start()
    return job_status()


@app.post("/api/import")
def reimport():
    if job["running"]:
        raise HTTPException(409, "Wait for the current refresh")
    with edit_lock:
        result = import_files()
    invalidate()
    return result


class Mapping(BaseModel):
    code: str = Field(pattern=r"^[0-9]{3,10}$")


@app.put("/api/schemes/{scheme_id}")
def set_mapping(scheme_id: str, body: Mapping):
    from .providers import client, request as get, CATALOG, parse_amfi
    if not db.rows("SELECT id FROM schemes WHERE id=?", (scheme_id,)):
        raise HTTPException(404, "Fund not found")
    with client() as c:
        catalog = parse_amfi(get(c, "GET", CATALOG).text)
    match = next((r for r in catalog if r["code"] == body.code), None)
    if not match:
        raise HTTPException(400, "AMFI code is not present in the current catalog")
    with db.connect() as conn:
        conn.execute("UPDATE schemes SET code=?,official_name=?,isin=?,mapping_status='manual' WHERE id=?", (body.code, match["name"], match["isin"], scheme_id))
        conn.execute("DELETE FROM prices WHERE kind='fund' AND instrument=?", (scheme_id,))
        conn.execute("DELETE FROM windows WHERE kind='fund'")
    invalidate()
    return {"name": match["name"]}


class Person(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")


@app.post("/api/people", status_code=201)
def add_person(person: Person):
    pid = ident(person.pan)
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO people VALUES (?,?,?)", (pid, person.name, person.pan))
    invalidate()
    return {"id": pid, "name": person.name}


class Allocation(BaseModel):
    lot_id: str
    units: float = Field(gt=0, allow_inf_nan=False)


class Transfer(BaseModel):
    date: date
    scheme: str
    sender: str
    recipient: str
    units: float = Field(gt=0, allow_inf_nan=False)
    nav: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    lots: list[Allocation] = []
    note: str = Field(default="", max_length=500)


@app.post("/api/transfers", status_code=201)
def add_transfer(t: Transfer):
    if t.date > today():
        raise HTTPException(400, "Transfer date cannot be in the future")
    if t.sender == t.recipient:
        raise HTTPException(400, "Sender and recipient must differ")
    known = {p["id"] for p in db.rows("SELECT id FROM people")}
    if not {t.sender, t.recipient} <= known:
        raise HTTPException(400, "Add both people before recording a transfer")
    if not db.rows("SELECT id FROM schemes WHERE id=?", (t.scheme,)):
        raise HTTPException(400, "Unknown fund")
    nav = t.nav
    if not nav:
        q = Quotes(db.rows("SELECT * FROM prices WHERE kind='fund'")).at("fund", t.scheme, t.date.isoformat())
        if not q or (t.date-date.fromisoformat(q["date"])).days > 7:
            raise HTTPException(400, "Enter transfer-date NAV or refresh historical prices first")
        nav = q["value"]
    tid = uuid.uuid4().hex[:20]
    previous_errors = {x for x in calculate()["issues"] if x.startswith("Ledger error")}
    with db.connect() as conn:
        conn.execute("INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, t.date.isoformat(), t.scheme, t.sender, t.recipient, t.units, nav, json.dumps([x.model_dump() for x in t.lots]), t.note, now()))
    try:
        result = calculate()
        errors = [x for x in result["issues"] if x.startswith("Ledger error") and x not in previous_errors]
        if errors:
            raise ValueError(errors[0])
    except Exception as exc:
        with db.connect() as conn:
            conn.execute("DELETE FROM transfers WHERE id=?", (tid,))
        invalidate()
        raise HTTPException(400, str(exc))
    invalidate()
    return {"id": tid}


@app.delete("/api/transfers/{tid}")
def delete_transfer(tid: str):
    with db.connect() as conn:
        for link in conn.execute("SELECT t.id FROM transfer_links l JOIN transactions t ON t.id=l.transaction_id WHERE l.transfer_id=? AND t.type='REDEEM'", (tid,)).fetchall():
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?, '1')", ("ignore_cas_gift_" + link["id"],))
        conn.execute("DELETE FROM transfers WHERE id=?", (tid,))
    invalidate()
    return {"deleted": tid}


class Exclusion(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@app.put("/api/transactions/{tid}/exclude")
def exclude(tid: str, body: Exclusion):
    if job["running"]:
        raise HTTPException(409, "Wait for the current refresh before changing review decisions")
    if not db.rows("SELECT id FROM transactions WHERE id=?", (tid,)):
        raise HTTPException(404, "Transaction not found")
    if db.rows("SELECT transfer_id FROM transfer_links WHERE transaction_id=?", (tid,)):
        raise HTTPException(409, "This row is linked to a unit transfer. Remove the transfer in Transfers before excluding its source row.")
    try:
        change_exclusion(tid, body.reason)
    except ValueError as exc:
        raise HTTPException(409,str(exc))
    invalidate()
    return {"excluded": tid}


@app.delete("/api/transactions/{tid}/exclude")
def restore(tid: str):
    if job["running"]:
        raise HTTPException(409, "Wait for the current refresh before changing review decisions")
    try:
        change_exclusion(tid,None)
    except ValueError as exc:
        raise HTTPException(409,str(exc))
    invalidate()
    return {"restored": tid}


def dataset(kind, people=None, start=None, end=None, fund=None):
    person_map = {p["id"]: p["name"] for p in db.rows("SELECT * FROM people")}
    scheme_map = {s["id"]: s["name"] for s in db.rows("SELECT * FROM schemes")}
    if kind == "transactions":
        records = db.rows("SELECT t.*,e.reason AS excluded,l.transfer_id FROM transactions t LEFT JOIN exclusions e ON e.transaction_id=t.id LEFT JOIN transfer_links l ON l.transaction_id=t.id ORDER BY t.date DESC,t.id")
        from .precision import apply_unit_precision
        apply_unit_precision(records)
        consolidated = {tid: (c["id"],role) for c in db.rows("SELECT * FROM consolidations") for role,tid in [("original",c["original_id"]),("incoming",c["purchase_id"]),("outgoing",c["redemption_id"])]}
        for r in records:
            r["consolidation_id"],r["consolidation_role"] = consolidated.get(r["id"], (None,None))
            r["treatment"] = "Original purchase · CAS verified" if r["consolidation_role"] == "original" else "Internal folio consolidation · no added units or cash flow" if r["consolidation_id"] else "Excluded" if r["excluded"] else "Unit transfer · source row replaced by linked transfer" if r["transfer_id"] else "Cash transaction"
    elif kind in {"navs", "indices"}:
        records = db.rows("SELECT * FROM prices WHERE kind=? ORDER BY date DESC,instrument", ("fund" if kind == "navs" else "index",))
    elif kind == "transfers":
        records = calculate(people.split(",") if people is not None else None)["transfer_details"]
    elif kind == "status":
        records = coverage()
    elif kind == "gaps":
        from .providers import potential_gaps
        records = [{"date": d, "instrument": r["instrument"], "name": r["name"], "kind": r["kind"], "status": "Potential publication gap · retry on refresh"} for r in coverage() for d in potential_gaps(r["kind"], r["instrument"])]
        records = list({(r["kind"], r["instrument"], r["date"]): r for r in records}.values())
    else:
        key = {"valuations": "daily", "benchmarks": "benchmark_details", "lots": "lots", "cashflows": "cashflows"}.get(kind)
        if not key:
            raise HTTPException(400, "Unknown table")
        result = params(people, start, end, fund, True)
        records = result[key]
    selected = set(people.split(",")) if people is not None else None
    answer = []
    for r in records:
        if selected is not None and "person" in r and r["person"] not in selected:
            continue
        if selected is not None and "sender" in r and not ({r["sender"], r["recipient"]} & selected):
            continue
        if fund and (r.get("scheme") or (r.get("instrument") if kind in {"navs", "status", "gaps"} else fund)) != fund:
            continue
        if start and r.get("date", start) < start or end and r.get("date", end) > end:
            continue
        r = dict(r)
        if "person" in r:
            r["person_name"] = person_map.get(r["person"], r["person"])
        if "scheme" in r:
            r["fund"] = scheme_map.get(r["scheme"], r["scheme"])
        if kind == "navs":
            r["fund"] = scheme_map.get(r["instrument"], r["instrument"])
        answer.append(r)
    return answer


@app.get("/api/data/{kind}")
def data(kind: str, people: str | None = None, start: str | None = None, end: str | None = None, fund: str | None = None, search: str = "", sort: str = "date", direction: str = "desc", offset: int = 0, limit: int = 100):
    records = dataset(kind, people, start, end, fund)
    if search:
        records = [r for r in records if search.lower() in json.dumps(r, ensure_ascii=False).lower()]
    records.sort(key=lambda r: (r.get(sort) is None, r.get(sort) if isinstance(r.get(sort), (int, float)) else str(r.get(sort) or "")), reverse=direction == "desc")
    return {"rows": records[max(0, offset):max(0, offset) + min(max(limit, 1), 500)], "total": len(records)}


@app.get("/api/export/{kind}.csv")
def export(kind: str, people: str | None = None, start: str | None = None, end: str | None = None, fund: str | None = None, search: str = ""):
    records = dataset(kind, people, start, end, fund)
    if search:
        records = [r for r in records if search.lower() in json.dumps(r, ensure_ascii=False).lower()]
    output = io.StringIO()
    if records:
        fields = list(dict.fromkeys(k for r in records for k in r))
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        # Prevent formula injection when exported strings are opened in Excel.
        for r in records:
            writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for k, v in r.items()})
    return StreamingResponse(iter(["\ufeff" + output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="portfolio-{kind}.csv"'})


def coverage():
    from .providers import potential_gaps
    result = db.rows("SELECT kind,instrument,MIN(date) AS first_date,MAX(date) AS last_date,COUNT(*) AS observations,MAX(fetched_at) AS fetched_at,GROUP_CONCAT(DISTINCT source) AS source FROM prices GROUP BY kind,instrument")
    fund_map = {s["id"]: s for s in db.rows("SELECT * FROM schemes")}
    found = {r["instrument"] for r in result}
    for r in result:
        r["name"] = fund_map.get(r["instrument"], {}).get("name", INDEXES.get(r["instrument"], r["instrument"]))
        r["status"] = "Loaded"
        gaps = potential_gaps(r["kind"], r["instrument"])
        r["potential_gaps"] = len(gaps)
        r["gap_dates"] = ", ".join(sorted(gaps))
        if r["potential_gaps"]:
            r["status"] = "Potential gaps"
    for sid, s in fund_map.items():
        if sid not in found:
            result.append({"kind": "fund", "instrument": sid, "name": s["name"], "first_date": None, "last_date": None, "observations": 0, "source": "AMFI", "status": "Mapping review" if not s["code"] else "Not downloaded"})
    for index, label in INDEXES.items():
        if index not in found:
            result.append({"kind": "index", "instrument": index, "name": label, "first_date": None, "last_date": None, "observations": 0, "source": "NSE Indices", "status": "Not downloaded"})
    return result


@app.get("/api/status")
def status():
    return {"coverage": coverage(), "issues": db.rows("SELECT * FROM issues ORDER BY id DESC"), "sources": db.rows("SELECT * FROM sources ORDER BY path"), "refresh": dict(job), "last_refresh": db.setting("last_refresh"), "errors": json.loads(db.setting("last_refresh_errors", "[]"))}


class IndexCSV(BaseModel):
    index: str
    csv: str = Field(max_length=10_000_000)


@app.post("/api/index-csv")
def import_index_csv(body: IndexCSV):
    if body.index not in INDEXES:
        raise HTTPException(400, "Unknown index")
    parsed = []
    for r in csv.DictReader(io.StringIO(body.csv.lstrip("\ufeff"))):
        r = {k.strip().lower().replace(" ", ""): v.strip() for k, v in r.items() if k}
        d = r.get("date") or r.get("historicaldate")
        value = r.get("totalreturnsindex") or r.get("totalreturnindex") or r.get("tri")
        if not d or not value:
            raise HTTPException(400, "CSV requires Date and Total Returns Index columns. Price-index Close is not accepted.")
        try:
            v = float(value.replace(",", ""))
            if not math.isfinite(v) or v <= 0:
                raise ValueError("Nonpositive TRI")
            parsed.append({"instrument": body.index, "date": day(d), "value": v})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    if not parsed:
        raise HTTPException(400, "CSV has no observations")
    save_prices("index", parsed, "NSE TRI CSV · user supplied")
    invalidate()
    return {"imported": len(parsed)}


static_path = Path(os.getenv("STATIC_DIR", "frontend/dist"))
if static_path.exists():
    app.mount("/", StaticFiles(directory=static_path, html=True), name="dashboard")
