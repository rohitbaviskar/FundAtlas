"""Use matched CAS quantities without changing source transactions or cash flows."""
import re
from collections import defaultdict
from decimal import Decimal
from .db import rows, connect
from .reconciliation import fund_key


def more_precise(value, original):
    return Decimal(str(value)).normalize().as_tuple().exponent < Decimal(str(original)).normalize().as_tuple().exponent


def reconcile_unit_precision():
    raw = rows("SELECT t.*,s.name AS fund FROM transactions t JOIN schemes s ON s.id=t.scheme WHERE t.id NOT IN (SELECT transaction_id FROM exclusions) AND t.id NOT IN (SELECT transaction_id FROM transfer_links) AND t.id NOT IN (SELECT purchase_id FROM consolidations UNION SELECT redemption_id FROM consolidations)")
    buckets = defaultdict(list)
    for t in raw:
        buckets[(t['person'], t['date'], fund_key(t['fund']), t['type'])].append(t)
    reports = defaultdict(list)
    for e in rows("SELECT * FROM reconciliation_events"):
        desc = e['description']
        if re.search(r'\b(gifting|cancelled)\b', desc, re.I):
            continue
        kind = 'REDEEM' if e['units'] < 0 and re.search(r'\bredemption\b', desc, re.I) else 'PURCHASE' if e['units'] > 0 and re.search(r'\b(purchase|systematic investment)\b', desc, re.I) else None
        if kind:
            reports[(e['person'], e['date'], fund_key(e['fund_name']), kind, e['source'])].append(e)
    proposals = defaultdict(list)
    conflicts = set()
    for key, evidence in reports.items():
        annual = buckets.get(key[:-1], [])
        # Connected match groups preserve order multiplicity within one report.
        # Overlapping reports are never added together to invent extra orders.
        links = {t['id']: [i for i,e in enumerate(evidence) if abs(t['units']-abs(e['units'])) <= .005001 and abs(t['nav']-e['nav']) <= .005001 and abs(t['amount']-e['amount']) <= 1.010001] for t in annual}
        remaining = {tid for tid, matches in links.items() if matches}
        while remaining:
            tids, ids = {min(remaining)}, set()
            while True:
                new_ids = {i for tid in tids for i in links[tid]}
                new_tids = {tid for tid in remaining if set(links[tid]) & new_ids}
                if new_tids == tids and new_ids == ids:
                    break
                tids, ids = new_tids, new_ids
            remaining -= tids
            if len(tids) != len(ids):
                continue
            # Different precise quantities behind otherwise identical rounded
            # orders cannot be assigned to FIFO lots without an order identity.
            if any(len(links[tid]) > 1 for tid in tids) and len({abs(evidence[i]['units']) for i in ids}) > 1:
                continue
            for tid in tids:
                t = next(t for t in annual if t['id'] == tid)
                e = evidence[links[tid][0]]
                value = abs(e['units'])
                proposals[tid].append((value, e['source'], e['row_number']))
    chosen = []
    raw_by_id = {t['id']: t for t in raw}
    for tid, options in proposals.items():
        if len({o[0] for o in options}) != 1:
            conflicts.add(tid)
            continue
        value, source, row_number = sorted(options, key=lambda o: (o[1],o[2]))[0]
        if more_precise(value, raw_by_id[tid]['units']):
            chosen.append((tid, value, source, row_number))
    with connect() as c:
        c.execute("DELETE FROM unit_precision")
        c.executemany("INSERT INTO unit_precision VALUES (?,?,?,?)", chosen)
        if conflicts:
            c.execute("INSERT INTO issues(category,message,source,created_at) VALUES ('reconciliation',?,'CAS unit precision',datetime('now'))", (f"CAS reports disagree on precise units for {len(conflicts)} transactions. Original statement quantities retained; review the source reports.",))


def apply_unit_precision(records):
    precision = {p['transaction_id']:p for p in rows('SELECT * FROM unit_precision')}
    for r in records:
        p = precision.get(r['id'])
        r['statement_units'] = r['units']
        r['unit_source'] = f"{p['source']}:{p['row_number']}" if p else f"{r['source']}:{r['row_number']}"
        if p:
            r['units'] = p['units']
    return records
