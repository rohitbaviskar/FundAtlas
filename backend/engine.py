"""Daily unit ledger, FIFO historical cost, ownership cash flows and benchmarks."""
import bisect
import copy
import json
import math
from collections import defaultdict
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
import pyxirr
from .db import rows
from .providers import INDEXES

EPS = 1e-7
ZERO_VALUE_THRESHOLD = 5.0


def balance_group(position):
    """Display grouping only; small balances remain in valuations and XIRR."""
    if position.get("market_value") is None or position.get("units") is None:
        return "unknown"
    if position["units"] <= 0 or abs(position["market_value"]) <= ZERO_VALUE_THRESHOLD:
        return "zero"
    return "active"


def today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def irr(flows, end, value):
    grouped = defaultdict(float)
    for d, amount in flows:
        grouped[d] += amount
    if value is not None:
        grouped[end] += value
    values = sorted((date.fromisoformat(d), a) for d, a in grouped.items() if abs(a) > EPS)
    if len(values) < 2 or not any(a < 0 for _, a in values) or not any(a > 0 for _, a in values):
        return None
    try:
        result = pyxirr.xirr(values, silent=True)
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, ArithmeticError):
        return None


class Quotes:
    def __init__(self, prices):
        self.series = defaultdict(dict)
        for r in prices:
            self.series[(r["kind"], r["instrument"])][r["date"]] = r
        self.dates = {k: sorted(v) for k, v in self.series.items()}

    def at(self, kind, instrument, d):
        key = kind, instrument
        ds = self.dates.get(key, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.series[key][ds[i]] if i >= 0 else None

    def next(self, kind, instrument, d):
        key = kind, instrument
        ds = self.dates.get(key, [])
        i = bisect.bisect_left(ds, d)
        return self.series[key][ds[i]] if i < len(ds) else None


def consume(lots, units, requested=None, tolerance=0):
    """Extract actual lots; never lose original transaction IDs or acquisition dates."""
    units = Decimal(str(units))
    available = sum(l["units"] for l in lots)
    if units > available + Decimal(str(tolerance)):
        raise ValueError(f"Insufficient units: requested {units:f}, available {available:f}")
    deficit = max(0, units - available)
    amount = min(units, available)
    taken = []
    allocation = requested or [{"lot_id": l["origin"], "units": l["units"]} for l in lots]
    if requested and sum(Decimal(str(r["units"])) for r in requested) != amount:
        raise ValueError("Lot allocations must sum to transferred units")
    for allocation_row in allocation:
        target = Decimal(str(allocation_row["units"]))
        if target <= 0:
            raise ValueError("Lot quantities must be positive")
        if requested and sum(l["units"] for l in lots if l["origin"] == allocation_row["lot_id"]) < target:
            raise ValueError("A selected purchase lot has insufficient units")
        for lot in lots:
            if lot["origin"] != allocation_row["lot_id"] or lot["units"] <= 0:
                continue
            qty = min(lot["units"], target, amount)
            if qty <= 0:
                continue
            portion = float(qty / lot["units"])
            part = dict(lot, units=qty, cost=lot["cost"] * portion, basis=lot["basis"] * portion)
            lot["units"] -= qty
            lot["cost"] -= part["cost"]
            lot["basis"] -= part["basis"]
            taken.append(part)
            target -= qty
            amount -= qty
        if amount <= 0:
            break
    if amount > 0:
        raise ValueError("Purchase lot allocation is incomplete")
    lots[:] = [l for l in lots if l["units"] > 0]
    return taken, deficit


def calculate(people=None, start=None, end=None, fund=None, include_daily=False, excluded_ids=None):
    persons = rows("SELECT * FROM people ORDER BY name")
    selected = set(people) if people is not None else {p["id"] for p in persons}
    schemes = {s["id"]: s for s in rows("SELECT * FROM schemes ORDER BY name")}
    excluded = {r["transaction_id"] for r in rows("SELECT transaction_id FROM exclusions")} if excluded_ids is None else set(excluded_ids)
    transactions = rows("SELECT * FROM transactions WHERE id NOT IN (SELECT transaction_id FROM transfer_links) AND id NOT IN (SELECT purchase_id FROM consolidations UNION SELECT redemption_id FROM consolidations) ORDER BY date, CASE type WHEN 'PURCHASE' THEN 0 WHEN 'REINVEST' THEN 0 ELSE 1 END, id")
    transactions = [t for t in transactions if t["id"] not in excluded]
    from .precision import apply_unit_precision
    apply_unit_precision(transactions)
    transfers = rows("SELECT * FROM transfers ORDER BY date,id")
    transfer_links = defaultdict(list)
    for link in rows("SELECT * FROM transfer_links"):
        transfer_links[link["transfer_id"]].append(link["transaction_id"])
    quotes = Quotes(rows("SELECT * FROM prices ORDER BY date"))
    reference_days = set(quotes.dates.get(("index", "NIFTY 50"), []))
    reference_bounds = (min(reference_days), max(reference_days)) if reference_days else None
    end = min(end or today().isoformat(), today().isoformat())
    events = defaultdict(list)
    for tx in transactions:
        events[tx["date"]].append(("tx", tx))
    for transfer in transfers:
        events[transfer["date"]].append(("transfer", transfer))
    active_ids = {t["scheme"] for t in transactions if t["person"] in selected and t["date"] <= end}
    active_ids |= {t["scheme"] for t in transfers if {t["sender"], t["recipient"]} & selected and t["date"] <= end}
    if fund:
        active_ids &= {fund} if isinstance(fund, str) else set(fund)
    if not events:
        return {"summary": {}, "funds": [], "series": [], "yearly": [], "benchmarks": [], "daily": [], "issues": [], "ledger_errors": [], "lots": [], "transfer_details": []}
    first = min(events)
    selected_dates = [t["date"] for t in transactions if t["person"] in selected and t["scheme"] in active_ids and t["date"] <= end]
    selected_dates += [t["date"] for t in transfers if {t["sender"], t["recipient"]} & selected and t["scheme"] in active_ids and t["date"] <= end]
    start = max(start or min(selected_dates, default=first), first)
    if start > end:
        start = end
    lots = defaultdict(list)
    metrics = defaultdict(lambda: defaultdict(float))
    flows = defaultdict(list)
    all_flows = []
    # Opening holdings are seeded separately in benchmarks at the previous
    # close. They are not a new purchase at the first day's closing TRI.
    period_flows = []
    daily, series, issues, transfer_details, ledger_errors = [], [], [], [], []
    observed = set()
    invalid_schemes = set()
    counts = defaultdict(int)
    period_open = {}
    prior_close = None
    unitized = 1.0
    prev_value = 0.0
    twr_valid = True
    peak = 1.0
    max_drawdown = 0.0
    yearly = defaultdict(lambda: defaultdict(float))
    yearly_funds = defaultdict(lambda: defaultdict(float))

    def issue(message):
        if message not in observed:
            issues.append(message)
            observed.add(message)

    def flow(scheme_id, d, amount, kind):
        if scheme_id not in active_ids or d < start:
            return
        flows[scheme_id].append((d, amount))
        all_flows.append((d, amount))
        period_flows.append((d, amount))
        if kind == "purchase":
            metrics[scheme_id]["purchases"] += -amount
        elif kind == "withdrawal":
            metrics[scheme_id]["withdrawals"] += amount
        elif kind == "payout":
            metrics[scheme_id]["payouts"] += amount
        elif kind == "transfer_in":
            metrics[scheme_id]["transfers_in"] += -amount
        elif kind == "transfer_out":
            metrics[scheme_id]["transfers_out"] += amount

    d = date.fromisoformat(first)
    final_positions = []
    while d.isoformat() <= end:
        ds = d.isoformat()
        day_flows = len(all_flows)
        if ds == start and prior_close:
            for sid, v in prior_close.items():
                period_open[sid] = v
                if v is None:
                    twr_valid = False
                elif v:
                    flows[sid].append((ds, -v))
                    all_flows.append((ds, -v))
            prev_value = sum(v or 0 for v in prior_close.values())
            day_flows = len(all_flows)
        for kind, event in events.get(ds, []):
            sid = event["scheme"]
            if kind == "tx":
                person, qty, amount = event["person"], event["units"], event["amount"]
                key = person, sid
                counts[key] += 1
                if event["type"] in {"PURCHASE", "REINVEST"}:
                    lots[key].append({"origin": event["id"], "date": ds, "units": Decimal(str(qty)), "cost": amount, "basis": amount})
                    if person in selected and event["type"] == "PURCHASE":
                        flow(sid, ds, -amount, "purchase")
                elif event["type"] == "REDEEM":
                    available = sum(l["units"] for l in lots[key])
                    try:
                        taken, deficit = consume(lots[key], qty, tolerance=0.0051 * counts[key])
                        if deficit > 0 and person in selected and sid in active_ids:
                            issue(f"{schemes[sid]['name']}: redemption exceeds rounded units by {deficit:f}; FIFO consumed available units. Reconcile with CAS.")
                        if person in selected and sid in active_ids and ds >= start:
                            metrics[sid]["realized_gain"] += amount - sum(l["basis"] for l in taken)
                            metrics[sid]["original_realized_gain"] += amount - sum(l["cost"] for l in taken)
                    except ValueError as exc:
                        if person in selected and sid in active_ids:
                            issue(f"Ledger error · {ds} · {schemes[sid]['name']}: {exc}")
                            ledger_errors.append({"event_id": event["id"], "scheme": sid, "person": person, "date": ds, "fund": schemes[sid]["name"], "requested": qty, "available": float(available), "shortfall": float(max(0,Decimal(str(qty))-available)), "message": str(exc)})
                            invalid_schemes.add(sid)
                    if person in selected:
                        flow(sid, ds, amount, "withdrawal")
                elif event["type"] == "PAYOUT" and person in selected:
                    flow(sid, ds, amount, "payout")
                if person in selected and sid in active_ids and ds >= start:
                    for mode, label in (("calendar", str(d.year)), ("financial", f"FY{d.year if d.month >= 4 else d.year-1}–{str((d.year if d.month >= 4 else d.year-1)+1)[-2:]}")):
                        field = {"PURCHASE": "purchases", "REDEEM": "withdrawals", "PAYOUT": "payouts", "REINVEST": "reinvested"}[event["type"]]
                        yearly[(mode, label)][field] += amount
                        yearly_funds[(mode, label, sid)][field] += amount
            else:
                sender, recipient = event["sender"], event["recipient"]
                q = quotes.at("fund", sid, ds)
                nav = event["nav"] or (q["value"] if q and (d - date.fromisoformat(q["date"])).days <= 7 else None)
                available = sum(l["units"] for l in lots[(sender, sid)])
                try:
                    if not nav:
                        raise ValueError("Transfer-date NAV is missing; supply the effective NAV")
                    value = event["units"] * nav
                    allocation = json.loads(event["lots"] or "[]")
                    counts[(sender, sid)] += 1
                    tolerance = .0051 * counts[(sender, sid)] if transfer_links[event["id"]] else 0
                    taken, deficit = consume(lots[(sender, sid)], event["units"], allocation, tolerance)
                    if deficit > 0:
                        if not taken:
                            raise ValueError("No purchase history available for the gifted units")
                        # Annual statements round each line to two decimals.
                        # Preserve all historical cost and the recorded incoming
                        # quantity; disclose the small unit reconciliation.
                        taken[-1]["units"] += deficit
                        if {sender, recipient} & selected and sid in active_ids:
                            issue(f"{schemes[sid]['name']}: CAS gift exceeds rounded annual units by {deficit:f}; original cost preserved and recipient receives the full CAS quantity. Earlier rounded rows need precise source history.")
                    cost = sum(l["cost"] for l in taken)
                    for lot in taken:
                        original_basis = lot["basis"]
                        # A transfer between selected people must preserve basis too.
                        new_basis = original_basis if sender in selected and recipient in selected else float(lot["units"]) * nav
                        lots[(recipient, sid)].append(dict(lot, basis=new_basis))
                    lots[(recipient, sid)].sort(key=lambda x: (x["date"], x["origin"]))
                    if not ({sender, recipient} <= selected):
                        if sender in selected:
                            flow(sid, ds, value, "transfer_out")
                            if ds >= start:
                                metrics[sid]["realized_gain"] += value - sum(l["basis"] for l in taken)
                        if recipient in selected:
                            flow(sid, ds, -value, "transfer_in")
                    for mode, label in (("calendar", str(d.year)), ("financial", f"FY{d.year if d.month >= 4 else d.year-1}–{str((d.year if d.month >= 4 else d.year-1)+1)[-2:]}")):
                        if ds >= start and sid in active_ids:
                            for person, field in ((sender, "transfer_out"), (recipient, "transfer_in")):
                                if person in selected:
                                    yearly[(mode, label)][field] += value
                                    yearly_funds[(mode, label, sid)][field] += value
                    if {sender, recipient} & selected and sid in active_ids and ds >= start:
                        transfer_details.append(dict(event, original_cost=cost, market_value=value, effective_nav=nav, allocation_method="Specific lots" if allocation else "FIFO", source_transactions=transfer_links[event["id"]], recipient_unmatched=recipient.startswith("external-gift:")))
                except ValueError as exc:
                    if {sender, recipient} & selected and sid in active_ids:
                        issue(f"Ledger error · transfer {event['id']}: {exc}")
                        ledger_errors.append({"event_id": event["id"], "scheme": sid, "person": sender, "recipient": recipient, "date": ds, "fund": schemes[sid]["name"], "requested": event["units"], "available": float(available), "shortfall": float(max(0,Decimal(str(event["units"]))-available)), "message": str(exc)})
                        invalid_schemes.add(sid)
        positions = []
        totals = defaultdict(float)
        values_by_fund = {}
        for sid in sorted(active_ids):
            owned = [l for (person, scheme), ls in lots.items() if person in selected and scheme == sid for l in ls]
            qty = float(sum(l["units"] for l in owned))
            cost = sum(l["cost"] for l in owned)
            basis = sum(l["basis"] for l in owned)
            quote = quotes.at("fund", sid, ds)
            nav = quote["value"] if quote else None
            value = None if sid in invalid_schemes else qty * nav if nav is not None else (0.0 if qty == 0 else None)
            # Genuine missing business-day prices remain visible; carry-forward is
            # only a dated valuation, not a manufactured observation in prices.
            stale_days = (d - date.fromisoformat(quote["date"])).days if quote else None
            position = {"date": ds, "scheme": sid, "name": schemes[sid]["name"], "units": qty, "remaining_cost": cost, "ownership_basis": basis, "nav": nav, "nav_date": quote["date"] if quote else None, "market_value": value, "nav_source": quote["source"] if quote else None, "stale_days": stale_days, "average_nav": cost / qty if qty > 0 else None}
            positions.append(position)
            values_by_fund[sid] = value
            totals["remaining_cost"] += cost
            totals["value"] += value or 0
            totals["missing"] += value is None
            if include_daily and ds >= start and (qty > 0 or events.get(ds)):
                daily.append(position)
        complete = totals["missing"] == 0
        value = totals["value"] if complete else None
        if ds >= start:
            # Calendar ageing during a closed domestic session does not add a
            # missing valuation. This matters for overseas holiday gaps that
            # cross a weekend; a stale price on a trading day still invalidates
            # TWR. Until reference dates load, weekdays are the fallback.
            valuation_day = ds in reference_days if reference_bounds and reference_bounds[0] <= ds <= reference_bounds[1] else d.weekday() < 5
            if any(p["units"] > 0 and (p["stale_days"] is None or p["stale_days"] > 7 and valuation_day) for p in positions):
                twr_valid = False
            cf = sum(a for _, a in all_flows[day_flows:])
            # End-of-day cash-flow TWR convention, disclosed in methodology.
            if value is not None and prev_value > EPS:
                factor = (value + cf) / prev_value
                if factor >= 0:
                    unitized *= factor
                else:
                    twr_valid = False
            elif value is None:
                twr_valid = False
            if twr_valid:
                peak = max(peak, unitized)
                max_drawdown = min(max_drawdown, unitized / peak - 1)
            m = {k: sum(v[k] for v in metrics.values()) for k in ("purchases", "withdrawals", "payouts", "transfers_in", "transfers_out")}
            net = m["purchases"] - m["withdrawals"] + m["transfers_in"] - m["transfers_out"] - m["payouts"]
            series.append({"date": ds, "value": value, "net_contributions": net, "remaining_cost": totals["remaining_cost"], "twr": unitized - 1 if twr_valid else None, "drawdown": unitized / peak - 1 if twr_valid else None})
            prev_value = value or 0
        prior_close = values_by_fund
        final_positions = positions
        d += timedelta(days=1)

    funds = []
    for p in final_positions:
        sid = p["scheme"]
        m = metrics[sid]
        f = flows[sid]
        opening = period_open.get(sid, 0)
        value = p["market_value"]
        invalid = sid in invalid_schemes or opening is None
        gain = None if value is None or invalid else value + sum(a for _, a in f)
        paid_in = sum(-a for _, a in f if a < 0)
        funds.append(dict(p, **{k: m[k] for k in ("purchases", "withdrawals", "payouts", "transfers_in", "transfers_out", "realized_gain", "original_realized_gain")}, total_gain=gain, total_return=gain / paid_in if gain is not None and paid_in > 0 else None, xirr=irr(f, end, value) if not invalid and value is not None else None, unrealized_gain=value-p["ownership_basis"] if value is not None else None, original_unrealized_gain=value-p["remaining_cost"] if value is not None else None, status="Held" if p["units"] > 0 else "Exited", mapping_status=schemes[sid]["mapping_status"], code=schemes[sid]["code"], opening_value=opening))
    funds.sort(key=lambda f: (f["status"] != "Held", -(f["market_value"] or 0), f["name"]))
    final_value = series[-1]["value"] if series else None
    opening_complete = not any(v is None for v in period_open.values())
    total_gain = final_value + sum(a for _, a in all_flows) if final_value is not None and opening_complete else None
    paid_in = sum(-a for _, a in all_flows if a < 0)
    summary = {"value": final_value, "remaining_cost": sum(p["remaining_cost"] for p in funds), "purchases": sum(f["purchases"] for f in funds), "withdrawals": sum(f["withdrawals"] for f in funds), "transfers_in": sum(f["transfers_in"] for f in funds), "transfers_out": sum(f["transfers_out"] for f in funds), "total_gain": total_gain, "total_return": total_gain/paid_in if paid_in > 0 and total_gain is not None else None, "xirr": irr(all_flows, end, final_value) if final_value is not None and opening_complete else None, "twr": series[-1]["twr"] if series else None, "max_drawdown": max_drawdown if twr_valid else None, "active_funds": sum(balance_group(f) == "active" for f in funds), "zero_funds": sum(balance_group(f) == "zero" for f in funds), "zero_value_threshold": ZERO_VALUE_THRESHOLD, "nav_date": min((f["nav_date"] for f in funds if f["status"] == "Held" and f["nav_date"]), default=None), "as_of": end, "start": start, "opening_value": sum(v or 0 for v in period_open.values()) if opening_complete else None}
    summary["net_contributions"] = summary["purchases"] - summary["withdrawals"]
    for point in series:
        point["gain"] = point["value"] - summary["opening_value"] - point["net_contributions"] if point["value"] is not None and opening_complete else None
    summary["realized_gain"] = None if invalid_schemes else sum(f["realized_gain"] for f in funds)
    if invalid_schemes:
        summary["remaining_cost"] = None
        for f in funds:
            if f["scheme"] in invalid_schemes:
                f.update(remaining_cost=None, average_nav=None, realized_gain=None, original_realized_gain=None, units=None, status="Needs review")
    for f in funds:
        f["balance_group"] = balance_group(f)
        f["is_residual"] = f["balance_group"] == "zero" and f["units"] > 0
    if not opening_complete:
        issue("Period returns unavailable: a holding has no published price at the period opening. Current value uses available end-date prices.")
    for f in funds:
        if f["status"] == "Held" and (f["nav"] is None or (f["stale_days"] or 0) > 4):
            issue(f"Price coverage · {f['name']}: {'no published NAV loaded' if f['nav'] is None else 'latest NAV is '+f['nav_date']}")
    benchmarks, benchmark_details = [], []
    for instrument, label in INDEXES.items():
        b, detail = benchmark(quotes, instrument, label, period_flows, start, end, opening_value=summary["opening_value"])
        benchmarks.append(b)
        if include_daily:
            benchmark_details.extend(detail)
    yearly_rows = [{"mode": mode, "year": year, **dict(m), "net": m["purchases"] - m["withdrawals"]} for (mode, year), m in sorted(yearly.items())]
    fund_yearly_rows = [{"mode": mode, "year": year, "scheme": sid, "name": schemes[sid]["name"], **dict(m), "net": m["purchases"] - m["withdrawals"]} for (mode, year, sid), m in sorted(yearly_funds.items())]
    lot_rows = [{"person": person, "scheme": sid, "fund": schemes[sid]["name"], **lot, "units": float(lot["units"])} for (person, sid), ls in lots.items() for lot in ls if person in selected and sid in active_ids]
    return {"summary": summary, "funds": funds, "series": series, "yearly": yearly_rows, "yearly_funds": fund_yearly_rows, "benchmarks": benchmarks, "daily": daily, "benchmark_details": benchmark_details, "issues": issues, "ledger_errors": ledger_errors, "lots": lot_rows, "transfer_details": transfer_details, "cashflows": [{"date": d, "amount": a} for d, a in all_flows]}


def benchmark(quotes, instrument, label, flows, start, end, opening_value=0):
    transactions = defaultdict(float)
    cash_by_date = defaultdict(float)
    effective_flows, detail, error = [], [], None
    units = 0.0
    if opening_value is None:
        error = "Missing portfolio value at the period opening"
    elif opening_value > EPS:
        prior_day = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        q = quotes.at("index", instrument, prior_day)
        if not q or (date.fromisoformat(prior_day) - date.fromisoformat(q["date"])).days > 7:
            error = f"Missing TRI at period opening {start}"
        else:
            units = opening_value / q["value"]
            effective_flows.append((start, -opening_value))
            detail.append({"date": start, "cashflow_date": start, "index": label, "tri": q["value"], "tri_date": q["date"], "cashflow": -opening_value, "unit_change": units, "type": "Opening investment"})
    for d, cash in flows:
        if abs(cash) < EPS:
            continue
        q = quotes.next("index", instrument, d)
        if not q or q["date"] > end or (date.fromisoformat(q["date"]) - date.fromisoformat(d)).days > 7:
            error = f"Missing TRI near cash-flow date {d}"
            break
        delta = -cash / q["value"]
        transactions[q["date"]] += delta
        cash_by_date[q["date"]] += cash
        effective_flows.append((q["date"], cash))
        detail.append({"date": q["date"], "cashflow_date": d, "index": label, "tri": q["value"], "cashflow": cash, "unit_change": delta, "type": "Cash flow"})
    series = []
    invested = opening_value or 0.0
    previous_value = invested
    unitized = 1.0
    d = date.fromisoformat(start)
    latest = quotes.at("index", instrument, end)
    while d.isoformat() <= end:
        ds = d.isoformat()
        units += transactions.get(ds, 0)
        if units < -EPS:
            error = "Matched withdrawals exceed benchmark value; comparison unavailable"
        q = quotes.at("index", instrument, ds)
        cash = cash_by_date.get(ds, 0)
        invested -= cash
        v = (units * q["value"] if q else 0.0 if units == 0 else None) if not error else None
        if previous_value > EPS and v is not None:
            unitized *= (v + cash) / previous_value
        series.append({"date": ds, "value": v, "units": units, "tri": q["value"] if q else None, "tri_date": q["date"] if q else None, "gain": v - invested if v is not None else None, "twr": unitized - 1 if v is not None else None, "net_contributions": invested - (opening_value or 0)})
        previous_value = v or 0.0
        detail.append({"date": ds, "index": label, "tri": q["value"] if q else None, "tri_date": q["date"] if q else None, "units": units, "value": v, "type": "Daily value"})
        d += timedelta(days=1)
    value = series[-1]["value"] if series else None
    if not latest:
        error = "No published TRI data loaded"
    return {"id": instrument, "name": label, "value": value if not error else None, "xirr": irr(effective_flows, end, value) if value is not None and not error else None, "total_gain": series[-1]["gain"] if series and not error else None, "opening_value": opening_value, "series": series if not error else [], "date": latest["date"] if latest else None, "error": error}, detail
