"""Comparable NAV/TRI growth alongside ownership-aware investment returns."""
from datetime import date, timedelta
from .db import rows
from .engine import Quotes, today
from .providers import INDEXES


def market_performance(fund_ids, index_ids, start=None, end=None, initial_value=10000):
    end = min(end or today().isoformat(), today().isoformat())
    schemes = {s['id']: s['name'] for s in rows('SELECT id,name FROM schemes')}
    instruments = [('fund', sid, schemes[sid]) for sid in fund_ids] + [('index', sid, INDEXES[sid]) for sid in index_ids]
    quotes = Quotes(rows('SELECT * FROM prices ORDER BY date'))
    missing = [name for kind,sid,name in instruments if not quotes.dates.get((kind,sid))]
    result = {'start':None,'end':None,'requested_start':start,'requested_end':end,'initial_value':initial_value,'series':[],'error':None}
    if missing:
        result['error'] = 'Price history is unavailable for: ' + ', '.join(missing) + '. Refresh data or remove these comparisons.'
        return result
    first = max(([start] if start else []) + [quotes.dates[(kind,sid)][0] for kind,sid,_ in instruments])
    last = min([end] + [quotes.dates[(kind,sid)][-1] for kind,sid,_ in instruments])
    if first >= last:
        result['error'] = 'These funds and indexes have no overlapping price history with at least two dates in the selected period. Remove a fund or choose a longer period.'
        return result
    def fresh(ds):
        return all((q := quotes.at(kind,sid,ds)) and (date.fromisoformat(ds)-date.fromisoformat(q['date'])).days <= 7 for kind,sid,_ in instruments)
    while first < last and not fresh(first):
        first = (date.fromisoformat(first)+timedelta(days=1)).isoformat()
    while last > first and not fresh(last):
        last = (date.fromisoformat(last)-timedelta(days=1)).isoformat()
    if first >= last:
        result['error'] = 'No shared comparison window has recent published prices at both ends. Refresh data or remove a fund.'
        return result
    result.update(start=first,end=last)
    for kind,sid,name in instruments:
        base = quotes.at(kind,sid,first)
        if not base or (date.fromisoformat(first)-date.fromisoformat(base['date'])).days > 7:
            result['error'] = f'{name} has no recent published price at the common starting date. Refresh data or remove this comparison.'
            result['series'] = []
            return result
        values = []
        d = date.fromisoformat(first)
        while d.isoformat() <= last:
            ds = d.isoformat()
            q = quotes.at(kind,sid,ds)
            usable = q and (d-date.fromisoformat(q['date'])).days <= 7
            growth = q['value']/base['value'] if usable else None
            values.append({'date':ds,'value':initial_value*growth if growth is not None else None,'return':growth-1 if growth is not None else None,'quote_date':q['date'] if q else None})
            d += timedelta(days=1)
        result['series'].append({'id':sid,'kind':kind,'name':name,'base_price':base['value'],'base_price_date':base['date'],'value':values[-1]['value'],'total_return':values[-1]['return'],'price_date':values[-1]['quote_date'],'has_gaps':any(v['value'] is None for v in values),'series':values})
    return result
