"""Duplicate review across every owner and transaction type, without page limits."""
import json
import threading
from collections import defaultdict
from datetime import date
from .db import rows, connect
from .importer import ident, now

edit_lock = threading.RLock()


def validate_changes(changes):
    """Preview before writing; rejected choices leave decisions and cash intact."""
    from .engine import calculate, EPS
    current = {r["transaction_id"] for r in rows("SELECT transaction_id FROM exclusions")}
    proposed = set(current)
    for tid, reason in changes.items():
        if reason is None:
            proposed.discard(tid)
        else:
            proposed.add(tid)
    if current == proposed:
        return
    before = {e["event_id"]:e for e in calculate(excluded_ids=current)["ledger_errors"]}
    for error in calculate(excluded_ids=proposed)["ledger_errors"]:
        old = before.get(error["event_id"])
        if old is None or error["shortfall"] > old["shortfall"] + EPS or error["shortfall"] == old["shortfall"] and error["message"] != old["message"]:
            raise ValueError(f"This choice would break {error['fund']} on {error['date']}: {error['message']}. No changes were saved. Check the paired redemption or transfer entries.")


def change_exclusion(tid, reason):
    with edit_lock:
        managed = rows("SELECT id FROM consolidations WHERE ? IN (original_id,purchase_id,redemption_id)", (tid,))
        proof = next((g for g in duplicate_groups() if g["cas_proof"] and tid in {r["id"] for r in g["records"]}), None)
        if managed or proof:
            raise ValueError("CAS has verified this purchase or folio consolidation. Its entries are reconciled together and cannot be removed as a duplicate.")
        validate_changes({tid: reason})
        with connect() as db:
            if reason is None:
                db.execute("DELETE FROM exclusions WHERE transaction_id=?", (tid,))
            else:
                db.execute("INSERT OR REPLACE INTO exclusions VALUES (?,?)", (tid,reason))


def duplicate_groups(people=None, start=None, end=None, fund=None):
    from .reconciliation import purchase_proof
    persons = {p["id"]: p["name"] for p in rows("SELECT id,name FROM people")}
    funds = {s["id"]: s["name"] for s in rows("SELECT id,name FROM schemes")}
    resolutions = {r["group_id"]: set(json.loads(r["kept_ids"])) for r in rows("SELECT * FROM review_resolutions")}
    evidence = {r["key"].removeprefix("review_evidence:"): r["value"] for r in rows("SELECT * FROM settings WHERE key LIKE 'review_evidence:%'")}
    buckets = defaultdict(list)
    cas_events = rows("SELECT * FROM reconciliation_events")
    consolidated = {tid: (c,role) for c in rows("SELECT * FROM consolidations") for role,tid in [("original",c["original_id"]),("incoming",c["purchase_id"]),("outgoing",c["redemption_id"])]}
    records = rows("SELECT t.*,e.reason AS excluded,l.transfer_id FROM transactions t LEFT JOIN exclusions e ON e.transaction_id=t.id LEFT JOIN transfer_links l ON l.transaction_id=t.id ORDER BY t.date,t.id")
    for r in records:
        c, role = consolidated.get(r["id"], (None,None))
        r["consolidation_id"] = c["id"] if c else None
        r["consolidation_role"] = role
        if people is not None and r["person"] not in people or fund and r["scheme"] != fund:
            continue
        key = (r["person"], r["scheme"], r["type"], r["units"], r["nav"], r["amount"])
        buckets[key].append(r)
    result = []
    for key, matching in buckets.items():
        clusters = []
        for r in matching:
            if not clusters or (date.fromisoformat(r["date"]) - date.fromisoformat(clusters[-1][0]["date"])).days > 7:
                clusters.append([])
            clusters[-1].append(r)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            if start and cluster[-1]["date"] < start or end and cluster[0]["date"] > end:
                continue
            group_id = ident("duplicate-review:" + ":".join(sorted(r["id"] for r in cluster)))
            active = {r["id"] for r in cluster if not r["excluded"] and r["consolidation_role"] not in {"incoming","outgoing"}}
            for r in cluster:
                r["person_name"] = persons.get(r["person"], r["person"])
                r["fund"] = funds.get(r["scheme"], r["scheme"])
            group = {"id": group_id, "person": key[0], "person_name": persons.get(key[0], key[0]), "scheme": key[1], "fund": funds.get(key[1], key[1]), "type": key[2], "records": cluster, "unresolved": len(active) > 1 and resolutions.get(group_id) != active, "active_count": len(active), "same_date": len({r["date"] for r in cluster}) == 1, "resolution_note": evidence.get(group_id), "cas_proof": None, "required_keep_ids": []}
            managed = next((consolidated[r["id"]][0] for r in cluster if r["id"] in consolidated), None)
            proof = purchase_proof(group, cas_events) if not managed else []
            if managed:
                group.update(cas_proof="consolidation", required_keep_ids=[managed["original_id"]], resolution_note=managed["evidence"], unresolved=active != {managed["original_id"]})
            elif proof:
                note = f"CAS lists {len(proof)} separate purchases: {proof[0]['source']}, rows {', '.join(str(r['row_number']) for r in proof)}. All are retained; these are not duplicate cash orders."
                required = {r["id"] for r in cluster}
                group.update(cas_proof="separate_orders", required_keep_ids=sorted(required), resolution_note=note, unresolved=active != required)
            result.append(group)
    result.sort(key=lambda g: (not g["unresolved"], -date.fromisoformat(g["records"][-1]["date"]).toordinal(), g["person_name"], g["fund"]))
    from .precision import apply_unit_precision
    apply_unit_precision([record for group in result for record in group["records"]])
    return result


def resolve_group(group_id, keep_ids, note=""):
    with edit_lock:
        return _resolve_group(group_id, keep_ids, note)


def _resolve_group(group_id, keep_ids, note=""):
    group = next((g for g in duplicate_groups() if g["id"] == group_id), None)
    if not group:
        raise ValueError("Duplicate group no longer exists; refresh the review list")
    ids = {r["id"] for r in group["records"]}
    keep = set(keep_ids)
    if not keep or not keep <= ids:
        raise ValueError("Keep at least one entry from this duplicate group")
    if group["cas_proof"] and keep != set(group["required_keep_ids"]):
        raise ValueError("CAS has already reconciled these entries. Separate verified purchases must all remain included; a folio consolidation must retain only its original purchase.")
    if any(r["transfer_id"] and r["id"] not in keep for r in group["records"]):
        raise ValueError("An entry is linked to a verified unit transfer. Remove the transfer in Transfers before replacing that source entry.")
    changes = {r["id"]: None if r["id"] in keep or r["consolidation_role"] in {"incoming","outgoing"} else "Duplicate resolved · kept " + ", ".join(sorted(keep)) for r in group["records"]}
    validate_changes(changes)
    with connect() as db:
        for r in group["records"]:
            if changes[r["id"]] is None:
                db.execute("DELETE FROM exclusions WHERE transaction_id=?", (r["id"],))
            else:
                db.execute("INSERT OR REPLACE INTO exclusions VALUES (?,?)", (r["id"], changes[r["id"]]))
        db.execute("INSERT OR REPLACE INTO review_resolutions VALUES (?,?,?)", (group_id, json.dumps(sorted(keep)), now()))
        if note:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("review_evidence:" + group_id, note))
        else:
            db.execute("DELETE FROM settings WHERE key=?", ("review_evidence:" + group_id,))
    return {"kept": len(keep), "excluded": sum(reason is not None for reason in changes.values())}
