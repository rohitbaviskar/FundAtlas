"""Reconcile gifts, folio consolidations and distinct orders using CAS evidence."""
import re
import json
from collections import defaultdict
from .db import connect, rows, setting
from .importer import ident, now
from .providers import normalized


def fund_key(name):
    base = normalized(re.sub(r"\s*\(.*", "", name))
    return " ".join(w for w in base.split() if w not in {"direct", "growth"})


def purchase_proof(group, evidence_rows):
    """Max per report avoids counting overlapping CAS exports as new orders."""
    if group["type"] != "PURCHASE" or not group["same_date"]:
        return []
    first = group["records"][0]
    by_source = defaultdict(list)
    for r in evidence_rows:
        if re.search(r"\b(gifting|consolidated|consolidation)\b", r["description"], re.I):
            continue
        if not re.search(r"\b(purchase|systematic investment)\b", r["description"], re.I):
            continue
        if r["person"] == first["person"] and r["date"] == first["date"] and fund_key(r["fund_name"]) == fund_key(group["fund"]) and abs(r["units"]-first["units"]) <= .005001 and abs(r["nav"]-first["nav"]) <= .005001 and abs(r["amount"]-first["amount"]) <= 1.010001:
            by_source[r["source"]].append(r)
    best = max(by_source.values(), key=len, default=[])
    return best if len(best) == len(group["records"]) else []


def reconcile_consolidations():
    """Keep the original acquisition; neutralize its folio out/in copies."""
    raw = rows("SELECT t.*,s.name AS fund FROM transactions t JOIN schemes s ON s.id=t.scheme")
    for e in rows("SELECT * FROM reconciliation_events"):
        if not re.search(r"\bpurchase consolidated from\b", e["description"], re.I):
            continue
        match = [t for t in raw if t["person"] == e["person"] and t["date"] == e["date"] and fund_key(t["fund"]) == fund_key(e["fund_name"]) and abs(t["units"]-e["units"]) <= .005001 and abs(t["nav"]-e["nav"]) <= .005001 and abs(t["amount"]-e["amount"]) <= 1.010001]
        buys = sorted([t for t in match if t["type"] == "PURCHASE"], key=lambda t: (t["occurrence"], t["row_number"], t["id"]))
        sells = [t for t in match if t["type"] == "REDEEM"]
        if len(buys) != 2 or len(sells) != 1 or len({(t["scheme"],t["units"],t["nav"],t["amount"]) for t in match}) != 1:
            continue
        original, incoming, outgoing = buys[0], buys[1], sells[0]
        cid = ident("folio-consolidation:" + original["id"])
        gid = ident("duplicate-review:" + ":".join(sorted(t["id"] for t in buys)))
        note = f"CAS confirms a folio consolidation ({e['source']}:{e['row_number']}). Original purchase row {original['row_number']} is retained once; Groww's matching redemption row {outgoing['row_number']} and incoming row {incoming['row_number']} are internal folio movements, with no external cash flow or added units."
        with connect() as conn:
            conn.execute("INSERT OR REPLACE INTO consolidations VALUES (?,?,?,?,?,?,?,?,?,?)", (cid,original["person"],original["scheme"],original["date"],original["id"],incoming["id"],outgoing["id"],original["units"],note,now()))
            conn.executemany("DELETE FROM exclusions WHERE transaction_id=?", [(t["id"],) for t in match])
            conn.execute("INSERT OR REPLACE INTO review_resolutions VALUES (?,?,?)", (gid,json.dumps([original["id"]]),now()))
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("review_evidence:"+gid,note))


def reconcile_verified_orders():
    from .review import duplicate_groups
    for group in duplicate_groups():
        if group.get("cas_proof") != "separate_orders":
            continue
        keep = group["required_keep_ids"]
        with connect() as conn:
            conn.executemany("DELETE FROM exclusions WHERE transaction_id=?", [(tid,) for tid in keep])
            conn.execute("INSERT OR REPLACE INTO review_resolutions VALUES (?,?,?)", (group["id"],json.dumps(sorted(keep)),now()))
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("review_evidence:"+group["id"],group["resolution_note"]))


def reconcile_gifts():
    records = rows("SELECT t.*,s.name AS fund FROM transactions t JOIN schemes s ON s.id=t.scheme WHERE t.id NOT IN (SELECT transaction_id FROM exclusions)")
    links = {r["transaction_id"]: r["transfer_id"] for r in rows("SELECT * FROM transfer_links")}
    messages = []
    evidence_rows = rows("SELECT * FROM reconciliation_events ORDER BY date,id")
    for evidence in (r for r in evidence_rows if r["units"] < 0 and re.search(r"\bgifting of units\b", r["description"], re.I)):
        matching = [r for r in records if r["person"] == evidence["person"] and r["type"] == "REDEEM" and r["date"] == evidence["date"] and fund_key(r["fund"]) == fund_key(evidence["fund_name"]) and "regular" not in normalized(evidence["fund_name"]).split() and abs(r["units"] - abs(evidence["units"])) <= .005001 and abs(r["nav"] - evidence["nav"]) <= .005001 and abs(r["amount"] - evidence["amount"]) <= .500001]
        if len(matching) != 1:
            messages.append((f"CAS gift {evidence['date']} · {evidence['fund_name']}: could not uniquely match an included outgoing annual transaction. No automatic reclassification was made.", evidence["source"]))
            continue
        outgoing = matching[0]
        if setting("ignore_cas_gift_" + outgoing["id"]) == "1":
            messages.append((f"CAS gift {evidence['date']} · {outgoing['fund']}: automatic transfer treatment was removed by the user; original cash rows are included.", evidence["source"]))
            continue
        tid = links.get(outgoing["id"], ident("cas-gift:" + outgoing["id"]))
        incoming = [r for r in records if r["person"] != outgoing["person"] and r["scheme"] == outgoing["scheme"] and r["type"] == "PURCHASE" and r["date"] == outgoing["date"] and abs(r["units"] - outgoing["units"]) < 1e-7 and abs(r["nav"] - outgoing["nav"]) < 1e-7 and abs(r["amount"] - outgoing["amount"]) < 1e-7 and (r["id"] not in links or links[r["id"]] == tid)]
        if len(incoming) > 1:
            messages.append((f"CAS gift {evidence['date']} · {outgoing['fund']}: multiple possible recipients/orders; review incoming duplicates. No automatic reclassification was made.", evidence["source"]))
            continue
        incoming_proofs = [r for r in evidence_rows if r["units"] > 0 and re.search(r"\bgifting of units\b", r["description"], re.I) and r["person"] != evidence["person"] and r["date"] == evidence["date"] and fund_key(r["fund_name"]) == fund_key(evidence["fund_name"]) and abs(r["units"] - abs(evidence["units"])) < .000001 and abs(r["nav"] - evidence["nav"]) < .000001 and abs(r["amount"] - evidence["amount"]) < .010001]
        proof_owners = {r["person"] for r in incoming_proofs}
        if len(proof_owners) > 1 or incoming and proof_owners and proof_owners != {incoming[0]["person"]}:
            messages.append((f"CAS gift {evidence['date']} · {outgoing['fund']}: conflicting recipient evidence; review the source files. No automatic reclassification was made.", evidence["source"]))
            continue
        recipient = incoming[0]["person"] if incoming else next(iter(proof_owners)) if proof_owners else "external-gift:" + outgoing["id"]
        note = f"CAS verified gift · {evidence['source']}:{evidence['row_number']}. Original annual rows linked, not counted again. Transfer units retain the full CAS quantity; original annual units remain visible for audit."
        if incoming_proofs:
            note += f" Incoming CAS: {incoming_proofs[0]['source']}:{incoming_proofs[0]['row_number']}."
        if not incoming and proof_owners:
            messages.append((f"CAS gift {evidence['date']} · {outgoing['fund']}: recipient verified by their incoming CAS gift. The annual incoming purchase is absent; the transfer adds the received units once, and will link a matching annual row if it arrives later.", evidence["source"]))
        elif not incoming:
            note += " Recipient not matched in loaded files."
            messages.append((f"CAS gift {evidence['date']} · {outgoing['fund']}: recipient is not present in the loaded incoming transactions. Treated as an outgoing ownership transfer, not a cash redemption. It will cancel in combined returns once a unique matching incoming export is added.", evidence["source"]))
        with connect() as conn:
            existing = conn.execute("SELECT id FROM transfers WHERE id=?", (tid,)).fetchone()
            if existing:
                conn.execute("UPDATE transfers SET recipient=?,units=?,nav=?,note=? WHERE id=?", (recipient, abs(evidence["units"]), evidence["nav"], note, tid))
            else:
                conn.execute("INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, outgoing["date"], outgoing["scheme"], outgoing["person"], recipient, abs(evidence["units"]), evidence["nav"], "[]", note, now()))
            conn.execute("INSERT OR IGNORE INTO transfer_links VALUES (?,?)", (outgoing["id"], tid))
            if incoming:
                conn.execute("INSERT OR IGNORE INTO transfer_links VALUES (?,?)", (incoming[0]["id"], tid))
                links[incoming[0]["id"]] = tid
        links[outgoing["id"]] = tid
    with connect() as conn:
        conn.executemany("INSERT INTO issues(category,message,source,created_at) VALUES ('reconciliation',?,?,?)", [(message, source, now()) for message, source in messages])
