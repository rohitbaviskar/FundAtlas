"""Published AMFI NAV and NSE TRI data; no inferred or interpolated quotes."""
import csv
import io
import json
import math
import os
import re
import ssl
import time
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from collections import defaultdict
import httpx
import truststore
from .db import connect, rows, set_setting
from .importer import day, now

INDEXES = {"NIFTY 50": "Nifty 50 TRI", "NIFTY LARGEMIDCAP 250": "Nifty LargeMidcap 250 TRI", "NIFTY 500": "Nifty 500 TRI", "NIFTY MIDCAP 150": "Nifty Midcap 150 TRI"}
CATALOG = "https://portal.amfiindia.com/spages/NAVAll.txt"
HISTORY = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
NIFTY = "https://www.niftyindices.com/Backpage/getTotalReturnIndexString"
# IDs published in AMFI's NAV download fund-house selector (Oct 2026).
AMCS = {"Aditya Birla Sun Life Mutual Fund": "3", "Axis Mutual Fund": "53", "Bandhan Mutual Fund": "48", "Edelweiss Mutual Fund": "47", "HDFC Mutual Fund": "9", "ICICI Prudential Mutual Fund": "20", "Invesco Mutual Fund": "42", "Motilal Oswal Mutual Fund": "55", "Nippon India Mutual Fund": "21", "PPFAS Mutual Fund": "64", "quant Mutual Fund": "13", "Tata Mutual Fund": "25", "UTI Mutual Fund": "28"}


def client():
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE")) if os.environ.get("SSL_CERT_FILE") else truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(timeout=httpx.Timeout(50, connect=15), follow_redirects=True, verify=context, headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalPortfolio/1.0)", "Accept": "*/*"})


def request(c, method, url, attempts=3, **kwargs):
    error = None
    for attempt in range(attempts):
        try:
            r = c.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except (httpx.HTTPError, ValueError) as exc:
            error = exc
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url.split('/')[2]}: {error}")


def parse_amfi(text):
    header, result, amc = None, [], ""
    for line in text.lstrip("\ufeff").splitlines():
        parts = [s.strip() for s in line.split(";")]
        if len(parts) == 1 and "mutual fund" in parts[0].lower() and not parts[0].startswith(("Open", "Close", "Interval")):
            amc = parts[0]
        if parts[0].lower() == "scheme code":
            header = [s.lower() for s in parts]
            continue
        if not header or not parts[0].isdigit() or len(parts) < len(header):
            continue
        rec = dict(zip(header, parts))
        name = rec.get("scheme name") or rec.get("nav name")
        # New format separates plan/option; older downloads embed them in name.
        complete = " ".join(x for x in [name, rec.get("plan", ""), rec.get("option", "")] if x)
        try:
            value = float(rec["net asset value"].replace(",", ""))
            if not math.isfinite(value) or value <= 0:
                continue
            result.append({"code": rec["scheme code"], "name": complete, "amc": amc, "date": day(rec["date"]), "value": value, "isin": next((v for k, v in rec.items() if "isin div payout" in k), "")})
        except (ValueError, KeyError):
            continue
    return result


def normalized(name):
    text = name.lower().replace("&", " and ")
    text = re.sub(r"\bfund\s+of\s+funds?\b", "fof", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"([a-z])([0-9])|([0-9])([a-z])", lambda m: " ".join(x for x in m.groups() if x), text)
    text = re.sub(r"\blargemidcap\b", "large midcap", text)
    text = re.sub(r"\b(plan|option|fund|scheme)\b", " ", text)
    words = text.split()
    # Formats sometimes repeat Direct / Growth after already including them.
    return " ".join(dict.fromkeys(words))


def eligible(source, candidate):
    source, candidate = normalized(source), normalized(candidate)
    for word in ("direct", "regular", "growth", "idcw"):
        if (word in source.split()) != (word in candidate.split()):
            return False
    return True


def mapping_overrides():
    overrides_path = Path(os.getenv("CONFIG_DIR", "config")) / "schemes.json"
    return json.loads(overrides_path.read_text()) if overrides_path.exists() else {}


def archived_definition(scheme):
    entry = mapping_overrides().get(scheme["name"])
    if isinstance(entry, dict) and entry.get("historical") is True and str(entry.get("code")) == str(scheme["code"]):
        return entry
    return None


def apply_mappings(catalog):
    overrides = mapping_overrides()
    available = {r["code"]: r for r in catalog}
    unique = list(available.values())
    with connect() as db:
        for scheme in rows("SELECT * FROM schemes"):
            if scheme["mapping_status"] == "manual" and scheme["code"] and scheme["name"] not in overrides:
                continue
            override = overrides.get(scheme["name"])
            if override:
                code = str(override["code"] if isinstance(override, dict) else override)
                match = available.get(code)
                if not match and isinstance(override, dict) and override.get("historical") is True:
                    if not override.get("amc") or normalized(override.get("name", "")) != normalized(scheme["name"]):
                        raise ValueError(f"Invalid archived mapping for {scheme['name']}")
                    match = dict(override, code=code, isin=override.get("isin"))
                if not match:
                    raise ValueError(f"Unknown AMFI code {override} in config for {scheme['name']}")
                status = "manual"
            else:
                candidates = [(SequenceMatcher(None, normalized(scheme["name"]), normalized(r["name"])).ratio(), r) for r in unique if eligible(scheme["name"], r["name"])]
                candidates.sort(key=lambda x: x[0], reverse=True)
                exact = [r for score, r in candidates if normalized(scheme["name"]) == normalized(r["name"])]
                # Fuzzy guesses are offered to the user, never used as a price source.
                match = exact[0] if len(exact) == 1 else None
                status = "matched" if match else "review"
                options = [{"score": round(score, 3), "code": r["code"], "name": r["name"]} for score, r in candidates[:4]]
                db.execute("UPDATE schemes SET candidates=? WHERE id=?", (json.dumps(options), scheme["id"]))
            new_code = match["code"] if match else None
            if new_code != scheme["code"]:
                db.execute("DELETE FROM prices WHERE kind='fund' AND instrument=?", (scheme["id"],))
                db.execute("DELETE FROM windows WHERE kind='fund'")
            db.execute("UPDATE schemes SET code=?,official_name=?,isin=?,mapping_status=? WHERE id=?", (new_code, match["name"] if match else None, match["isin"] if match else None, status, scheme["id"]))


def save_prices(kind, observations, source, overwrite=True):
    with connect() as db:
        verb = "REPLACE" if overwrite else "IGNORE"
        db.executemany(f"INSERT OR {verb} INTO prices VALUES (?,?,?,?,?,?)", [(kind, r["instrument"], r["date"], r["value"], source, now()) for r in observations])


def fund_observations(data, schemes):
    mapped = defaultdict(list)
    for s in schemes:
        mapped[s["code"]].append(s["id"])
    return [{"instrument": sid, "date": r["date"], "value": r["value"]} for r in data for sid in mapped[r["code"]]]


def mirror_history(c, scheme, start, end):
    """Use a labeled mirror only for missing quotes; published AMFI quotes win."""
    url = f"https://api.mfapi.in/mf/{scheme['code']}"
    body = request(c, "GET", url).json()
    meta = body.get("meta", {})
    expected_isin = scheme.get("isin")
    supplied_isins = {meta.get("isin_growth"), meta.get("isin_div_reinvestment")}
    valid_isin = bool(expected_isin and expected_isin not in {"-", "N.A.", "NA"})
    if valid_isin and expected_isin not in supplied_isins:
        raise ValueError(f"Historical mirror ISIN mismatch for {scheme['name']}")
    plan_ok = eligible(scheme["name"], meta.get("scheme_name", ""))
    # Some official catalog names omit plan/option. An exact ISIN identifies
    # that plan, but may never override an explicitly conflicting plan name.
    candidate_words = set(normalized(meta.get("scheme_name", "")).split())
    source_words = set(normalized(scheme["name"]).split())
    conflict = any(word in candidate_words and word not in source_words for word in ("direct", "regular", "growth", "idcw"))
    if str(meta.get("scheme_code")) != str(scheme["code"]) or not (plan_ok or valid_isin and not conflict):
        raise ValueError(f"Historical mirror identity/plan mismatch for {scheme['name']}")
    observations = []
    for r in body.get("data", []):
        ds = day(r["date"])
        value = float(r["nav"])
        if start.isoformat() <= ds <= end.isoformat() and math.isfinite(value) and value > 0:
            observations.append({"instrument": scheme["id"], "date": ds, "value": value})
    if not observations:
        raise ValueError("Historical mirror returned no usable observations")
    mirrored = {r["date"]: r["value"] for r in observations}
    official = rows("SELECT date,value FROM prices WHERE kind='fund' AND instrument=? AND source LIKE 'https://portal.amfiindia.com/%'", (scheme["id"],))
    overlap = [r for r in official if r["date"] in mirrored]
    if not overlap:
        archive = archived_definition(scheme)
        if not archive or normalized(meta.get("scheme_name", "")) != normalized(archive["name"]):
            raise ValueError(f"Cannot verify historical mirror against AMFI for {scheme['name']}")
        statement = rows("SELECT DISTINCT date,nav FROM transactions WHERE scheme=? AND nav>0", (scheme["id"],))
        checks = [r for r in statement if r["date"] in mirrored]
        if not checks or any(abs(r["nav"] - mirrored[r["date"]]) > 0.005001 for r in checks):
            raise ValueError(f"Archived NAV history does not agree with statement NAVs for {scheme['name']}")
        save_prices("fund", observations, url + " · archived scheme; identity and rounded statement NAVs checked", overwrite=False)
        with connect() as db:
            db.execute("DELETE FROM issues WHERE category='provider' AND source=?", (scheme["id"],))
            message = f"{scheme['name']}: archived scheme absent from the live AMFI catalog. MFAPI history uses the configured historical identity; {len(checks)} dated statement NAVs agree to export precision. No live AMFI overlap is available."
            db.execute("INSERT INTO issues(category,message,source,created_at) VALUES ('provider',?,?,?)", (message, scheme["id"], now()))
        return len(observations)
    def differs(r):
        return abs(r["value"] - mirrored[r["date"]]) > max(0.0002, abs(r["value"]) * 0.000001)
    mismatches = [r for r in overlap if differs(r)]
    recent = sorted(overlap, key=lambda r: r["date"], reverse=True)[:3]
    if any(differs(r) for r in recent) or len(mismatches) > max(3, len(overlap) * 0.01):
        raise ValueError(f"Historical mirror differs from AMFI on {mismatches[0]['date']} for {scheme['name']}")
    save_prices("fund", observations, url + " · historical fallback; latest AMFI overlap verified", overwrite=False)
    with connect() as db:
        message = f"{scheme['name']}: older history supplied by MFAPI; {len(overlap)-len(mismatches)} overlapping NAVs agree with AMFI. {len(mismatches)} historical differences use the official AMFI value. Latest overlap verified."
        db.execute("DELETE FROM issues WHERE category='provider' AND source=?", (scheme["id"],))
        db.execute("INSERT INTO issues(category,message,source,created_at) VALUES ('provider',?,?,?)", (message, scheme["id"], now()))
    return len(observations)


def intervals(start, end, days=85):
    while start <= end:
        stop = min(start + timedelta(days=days - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def windows_needed(kind, instrument, start, end, days=85, gap_dates=()):
    done = rows("SELECT start,end FROM windows WHERE kind=? AND instrument=?", (kind, instrument))
    # Historic successful windows are cached. The trailing week is always refetched.
    for lo, hi in intervals(start, end, days):
        covered = any(x["start"] <= lo.isoformat() and x["end"] >= hi.isoformat() for x in done)
        has_gap = any(lo.isoformat() <= d <= hi.isoformat() for d in gap_dates)
        if not covered or has_gap or hi >= end - timedelta(days=7):
            yield lo, hi


def potential_gaps(kind, instrument):
    """Interior omissions against published reference dates, never a guessed calendar."""
    own = rows("SELECT date FROM prices WHERE kind=? AND instrument=? ORDER BY date", (kind, instrument))
    if len(own) < 2:
        return []
    present = {r["date"] for r in own}
    # Domestic index dates are the reference. Until downloaded, use the domestic
    # growth scheme with the most loaded observations. Different fund holidays
    # can make these potential gaps rather than proof of a missing publication.
    expected = rows("SELECT date FROM prices WHERE kind='index' AND instrument='NIFTY 50'")
    if not expected:
        reference = rows("SELECT p.instrument,COUNT(*) AS n FROM prices p JOIN schemes s ON s.id=p.instrument WHERE p.kind='fund' AND lower(s.name) NOT LIKE '%liquid%' AND lower(s.name) NOT LIKE '%china%' AND lower(s.name) NOT LIKE '%us %' GROUP BY p.instrument ORDER BY n DESC LIMIT 1")
        if reference:
            expected = rows("SELECT date FROM prices WHERE kind='fund' AND instrument=?", (reference[0]["instrument"],))
    return [r["date"] for r in expected if own[0]["date"] < r["date"] < own[-1]["date"] and r["date"] not in present]


def mark_window(kind, instrument, lo, hi):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?)", (kind, instrument, lo.isoformat(), hi.isoformat(), now()))


def parse_tri(body, instrument):
    # Current NSE route returns an array; older downloads use a 'd' wrapper.
    raw = body if isinstance(body, list) else body.get("d", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    observations = []
    for r in raw:
        value = r.get("TotalReturnsIndex") or r.get("TotalReturnIndex") or r.get("TRI") or r.get("Total Return Index")
        d = r.get("Date") or r.get("HistoricalDate")
        if value is not None and d:
            v = float(str(value).replace(",", ""))
            if math.isfinite(v) and v > 0:
                observations.append({"instrument": instrument, "date": day(d), "value": v})
    return observations


def refresh_index(c, index, start, end, progress=None):
    """Backfill one TRI using the same persistent windows as daily refresh."""
    label = INDEXES[index]
    errors = []
    pending = list(windows_needed("index", index, start, end, days=300, gap_dates=potential_gaps("index", index)))
    for i, (lo, hi) in enumerate(pending):
        if progress:
            progress(f"{label} · {lo:%b %Y} – {hi:%b %Y}", i, len(pending))
        try:
            payload = {"cinfo": json.dumps({"name": index, "startDate": lo.strftime("%d-%b-%Y"), "endDate": hi.strftime("%d-%b-%Y"), "indexName": index})}
            response = request(c, "POST", NIFTY, attempts=2, timeout=20, json=payload, headers={"Referer": "https://www.niftyindices.com/reports/historical-data", "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json; charset=UTF-8"})
            observations = parse_tri(response.json(), index)
            if not observations:
                raise ValueError("NSE returned no TRI rows; no price-index substitution was made")
            save_prices("index", observations, NIFTY)
            mark_window("index", index, lo, hi)
        except Exception as exc:
            errors.append(f"{label} {lo}–{hi}: {exc}")
            # Preserve successful windows and retry the remaining history later.
            break
        time.sleep(0.15)
    return errors


def refresh_prices(progress):
    tx_range = rows("SELECT MIN(date) AS start FROM transactions")[0]["start"]
    if not tx_range:
        return []
    from .engine import today
    start, end = date.fromisoformat(tx_range), today()
    errors = []
    with client() as c:
        progress("Matching funds to AMFI schemes", 0, 1)
        catalog = []
        try:
            catalog = parse_amfi(request(c, "GET", CATALOG).text)
            if not catalog:
                raise ValueError("AMFI returned no valid NAV rows")
            apply_mappings(catalog)
            save_prices("fund", fund_observations(catalog, rows("SELECT * FROM schemes WHERE code IS NOT NULL")), CATALOG)
            set_setting("catalog_refreshed", now())
        except Exception as exc:
            errors.append(f"Fund catalog: {exc}")
        schemes = rows("SELECT * FROM schemes WHERE code IS NOT NULL")
        # Small fund-house batches, restricted to each house's investment period.
        catalog_by_code = {r["code"]: r for r in catalog}
        amcs = dict(AMCS)
        unknown = {catalog_by_code.get(s["code"], {}).get("amc", "") for s in schemes} - amcs.keys() - {""}
        if unknown:
            try:
                text = request(c, "GET", "https://www.amfiindia.com/net-asset-value/nav-download").text.replace('\\"', '"')
                amcs.update({name: code for code, name in re.findall(r'"mfId":"([^\"]+)","mfName":"([^\"]+)"', text)})
            except Exception:
                pass
        # Include prior business-day quotes for purchases dated on holidays.
        starts = {r["scheme"]: date.fromisoformat(r["start"]) - timedelta(days=14) for r in rows("SELECT scheme,MIN(date) AS start FROM transactions GROUP BY scheme")}
        groups, group_ends = {}, {}
        for s in schemes:
            if archived_definition(s):
                continue
            amc_name = catalog_by_code.get(s["code"], {}).get("amc", "")
            code = amcs.get(amc_name)
            if not code:
                errors.append(f"{s['name']}: fund-house identifier unavailable; review AMFI mapping")
                continue
            groups[code] = min(groups.get(code, end), starts.get(s["id"], start))
            # Only request dates the fund house has actually published. A
            # weekend-only tail must not become a false refresh failure.
            published = date.fromisoformat(catalog_by_code[s["code"]]["date"])
            group_ends[code] = min(end, max(group_ends.get(code, published), published))
        group_gaps = {amc: set() for amc in groups}
        for s in schemes:
            amc = amcs.get(catalog_by_code.get(s["code"], {}).get("amc", ""))
            if amc in group_gaps:
                group_gaps[amc].update(potential_gaps("fund", s["id"]))
        pending = [(amc, lo, hi) for amc, first in groups.items() for lo, hi in windows_needed("fund", amc, first, group_ends[amc], gap_dates=group_gaps[amc])]
        fallback_complete = set()
        fallback_failed = set()
        for i, (amc, lo, hi) in enumerate(pending):
            if amc in fallback_failed and hi < end - timedelta(days=90):
                continue
            if amc in fallback_complete and hi < end - timedelta(days=90):
                mark_window("fund", amc, lo, hi)
                continue
            progress(f"NAV history · batch {i+1}/{len(pending)} · {lo:%b %Y}", i + 1, len(pending) + len(INDEXES))
            try:
                data = parse_amfi(request(c, "GET", HISTORY, params={"frmdt": lo.strftime("%d-%b-%Y"), "todt": hi.strftime("%d-%b-%Y"), "mf": amc}).text)
                observations = fund_observations(data, schemes)
                if not observations:
                    raise ValueError("No matching historical NAVs returned")
                save_prices("fund", observations, HISTORY)
                mark_window("fund", amc, lo, hi)
                # Existing partial history is checked below; missing mapping later
                # invalidates windows through the manual mapping endpoint.
            except Exception as exc:
                try:
                    if amc in fallback_complete:
                        raise RuntimeError(str(exc))
                    members = [s for s in schemes if not archived_definition(s) and amcs.get(catalog_by_code.get(s["code"], {}).get("amc", "")) == amc]
                    progress(f"Verifying older NAV history · {len(members)} funds", i + 1, len(pending) + len(INDEXES))
                    for s in members:
                        mirror_history(c, s, starts.get(s["id"], start), end)
                    fallback_complete.add(amc)
                    mark_window("fund", amc, lo, hi)
                except Exception as fallback_error:
                    fallback_failed.add(amc)
                    errors.append(f"NAV fund house {amc} {lo}–{hi}: {exc}; fallback: {fallback_error}")
            time.sleep(0.15)
        for s in schemes:
            if not archived_definition(s):
                continue
            progress(f"Archived NAV history · {s['name']}", len(pending), len(pending) + len(INDEXES))
            try:
                mirror_history(c, s, starts.get(s["id"], start), end)
            except Exception as exc:
                errors.append(f"Archived history · {s['name']}: {exc}")
        for j, index in enumerate(INDEXES):
            def index_progress(message, completed, total):
                progress(message, len(pending) + j, len(pending) + len(INDEXES))
            errors.extend(refresh_index(c, index, start, end, index_progress))
    return errors
