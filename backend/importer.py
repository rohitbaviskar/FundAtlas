import hashlib
import json
import os
import re
import math
import warnings
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from openpyxl import load_workbook
from .db import connect


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def number(value):
    result = float(str(value or 0).replace(",", "").replace("₹", "").strip())
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric value in transaction export")
    return result


def day(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date: {value}")


def ident(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def read_workbook(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book:
            rows = list(sheet.values)
            pan = name = None
            header_index = None
            for i, row in enumerate(rows):
                for j, cell in enumerate(row):
                    label = str(cell or "").strip().lower()
                    if label in ("pan", "name") and j + 1 < len(row):
                        if label == "pan":
                            pan = str(row[j + 1] or "").strip().upper()
                        else:
                            name = str(row[j + 1] or "").strip()
                if {"Scheme Name", "Transaction Type", "Units", "NAV", "Amount", "Date"}.issubset(set(row)):
                    header_index = i
                    break
                if {"Scheme Name", "Transaction Description", "Units", "NAV", "Amount", "Date"}.issubset(set(row)):
                    if not pan or not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
                        raise ValueError("Missing or invalid PAN in CAS personal details")
                    header = {str(v).strip(): j for j, v in enumerate(row) if v}
                    gifts = []
                    for row_number, detail in enumerate(rows[i+1:], i+2):
                        get = lambda key: detail[header[key]] if header[key] < len(detail) else None
                        description = str(get("Transaction Description") or "")
                        # CAS copies have different precision, consolidation
                        # entries and cancelled orders. Save evidence, never add
                        # these overlapping rows as a second cash ledger.
                        is_gift = bool(re.search(r"\bgifting of units\b", description, re.I))
                        is_purchase = bool(re.search(r"\b(purchase|systematic investment)\b", description, re.I))
                        is_redemption = bool(re.search(r"\bredemption\b", description, re.I))
                        if re.search(r"\bcancell?ed\b", description, re.I) or not (is_gift or is_purchase or is_redemption) or not get("Units"):
                            continue
                        qty, nav = number(get("Units")), number(get("NAV"))
                        if nav > 0 and (is_purchase and qty > 0 or is_redemption and qty < 0 or is_gift and (qty < 0 and re.search(r"\bto\b", description, re.I) or qty > 0 and re.search(r"\bfrom\b", description, re.I))):
                            gifts.append({"person": ident(pan), "date": day(get("Date")), "fund_name": str(get("Scheme Name")).strip(), "units": qty, "nav": nav, "amount": abs(number(get("Amount"))), "description": description, "row_number": row_number})
                    return {"id": ident(pan), "name": name or pan[-4:], "pan": pan, "report_kind": "cas", "gifts": gifts}, []
            if header_index is None:
                continue
            if not pan or not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
                raise ValueError("Missing or invalid PAN in personal details")
            header = {str(v).strip(): i for i, v in enumerate(rows[header_index]) if v}
            transactions, occurrences = [], Counter()
            for i, row in enumerate(rows[header_index + 1:], header_index + 2):
                get = lambda key: row[header[key]] if header[key] < len(row) else None
                if not get("Scheme Name") or not get("Transaction Type"):
                    continue
                kind = str(get("Transaction Type")).upper().strip()
                aliases = {"REDEEM": "REDEEM", "REDEMPTION": "REDEEM", "PURCHASE": "PURCHASE", "BUY": "PURCHASE", "SELL": "REDEEM", "SWITCH IN": "PURCHASE", "SWITCH OUT": "REDEEM", "DIVIDEND": "PAYOUT", "IDCW PAYOUT": "PAYOUT", "DIVIDEND REINVESTMENT": "REINVEST", "IDCW REINVESTMENT": "REINVEST"}
                if kind not in aliases:
                    raise ValueError(f"Row {i}: unsupported transaction type {kind}. Record unit transfers in Transfers, not as purchases.")
                scheme = str(get("Scheme Name")).strip()
                tx = {"person": ident(pan), "scheme": ident(scheme), "date": day(get("Date")), "type": aliases[kind], "units": number(get("Units")), "nav": number(get("NAV")), "amount": number(get("Amount")), "row_number": i, "scheme_name": scheme}
                if tx["units"] < 0 or tx["amount"] < 0 or (tx["type"] != "PAYOUT" and tx["units"] <= 0):
                    raise ValueError(f"Row {i}: units and amounts must be positive")
                canonical = json.dumps([tx[k] for k in ("person", "scheme", "date", "type", "units", "nav", "amount")])
                occurrences[canonical] += 1
                tx["occurrence"] = occurrences[canonical]
                tx["id"] = ident(canonical + ":" + str(tx["occurrence"]))
                transactions.append(tx)
            return {"id": ident(pan), "name": name or pan[-4:], "pan": pan}, transactions
        raise ValueError("No transaction table found. Capital-gains reports cannot replace transaction history.")
    finally:
        book.close()


def import_files():
    root = Path(os.getenv("IMPORT_DIR", ".")).resolve()
    paths = sorted(p for p in root.rglob("*.xlsx") if not any(x.startswith(".") or x in {"node_modules", "backend", "frontend", "tests"} for x in p.relative_to(root).parts) and not p.name.startswith("~$"))
    all_transactions, people, sources, errors, reports, gifts = {}, {}, [], [], [], []
    for path in paths:
        source = str(path.relative_to(root))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            person, records = read_workbook(path)
            people[person["id"]] = {k: person[k] for k in ("id", "name", "pan")}
            if person.get("report_kind") == "cas":
                reports.append(source)
                for gift in person["gifts"]:
                    gifts.append(dict(gift, id=ident(source + ":" + str(gift["row_number"])), source=source))
            for tx in records:
                tx["source"] = source
                # Preserve identical legitimate rows inside a file; overlapping exports
                # use the maximum occurrence count rather than summing duplicates.
                all_transactions.setdefault(tx["id"], tx)
            sources.append((source, digest, len(records), now(), None))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            sources.append((source, digest, 0, now(), str(exc)))
    with connect() as db:
        # A failed new export must not silently remove previously imported history.
        if errors:
            for source, digest, count, stamp, error in sources:
                if error:
                    db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?)", (source, digest, count, stamp, error))
        else:
            db.execute("DELETE FROM transactions")
            db.execute("DELETE FROM sources")
            for person in people.values():
                db.execute("INSERT OR REPLACE INTO people VALUES (:id,:name,:pan)", person)
            for tx in all_transactions.values():
                db.execute("INSERT OR IGNORE INTO schemes(id,name) VALUES (?,?)", (tx["scheme"], tx["scheme_name"]))
                db.execute("INSERT INTO transactions VALUES (:id,:person,:scheme,:date,:type,:units,:nav,:amount,:source,:row_number,:occurrence)", tx)
            db.executemany("INSERT INTO sources VALUES (?,?,?,?,?)", sources)
            db.execute("DELETE FROM reconciliation_events")
            db.executemany("INSERT INTO reconciliation_events VALUES (:id,:person,:date,:fund_name,:units,:nav,:amount,:description,:source,:row_number)", gifts)
            db.execute("DELETE FROM issues WHERE category='reconciliation'")
            db.executemany("INSERT INTO issues(category,message,source,created_at) VALUES ('reconciliation',?,?,?)", [(f"{source}: CAS retained as reconciliation evidence. Its overlapping higher-precision transactions are not added to the annual transaction ledger.", source, now()) for source in reports])
        db.execute("DELETE FROM issues WHERE category='import'")
        db.executemany("INSERT INTO issues(category,message,source,created_at) VALUES ('import',?,'workbooks',?)", [(x, now()) for x in errors])
    if not errors:
        from .reconciliation import reconcile_gifts, reconcile_consolidations, reconcile_verified_orders
        reconcile_consolidations()
        reconcile_verified_orders()
        reconcile_gifts()
        from .precision import reconcile_unit_precision
        reconcile_unit_precision()
    return {"files": len(paths), "transactions": len(all_transactions), "errors": errors}


def seed_initial_statement_navs():
    """A launch-day execution NAV may predate the first public observation."""
    from .db import rows
    from datetime import timedelta
    for s in rows("SELECT scheme,MIN(date) AS first_date FROM transactions GROUP BY scheme"):
        public = rows("SELECT MIN(date) AS first_date FROM prices WHERE kind='fund' AND instrument=?", (s["scheme"],))[0]["first_date"]
        if not public or not s["first_date"] < public <= (date.fromisoformat(s["first_date"])+timedelta(days=7)).isoformat():
            continue
        tx = rows("SELECT * FROM transactions WHERE scheme=? AND date=? AND type='PURCHASE' AND nav>0", (s["scheme"], s["first_date"]))
        if not tx or len({t["nav"] for t in tx}) != 1:
            continue
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO prices VALUES ('fund',?,?,?,?,?)", (s["scheme"], s["first_date"], tx[0]["nav"], f"Statement execution NAV · {tx[0]['source']}:{tx[0]['row_number']}", now()))
