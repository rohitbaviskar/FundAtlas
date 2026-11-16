import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, ArrowLeft, Plus, X, Info, LoaderCircle, Download, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import GrowthChart from './GrowthChart';
import { money, pct, exactNumber } from './display.js';
import { comparisonQuery, comparisonTraces, fundColors } from './fundComparison.js';

type Row = Record<string, any>;
const day = (d: any) => d ? new Date(d.slice(0,10)+'T12:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}) : '—';
const nameOf = (s: string) => s?.replace(/ Direct( Plan)? Growth/g,'').replace(/ Fund$/,'');

function FundPicker({meta,ids,onChange}: Row) {
  const [open,setOpen] = useState(false);
  const [search,setSearch] = useState('');
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown',close);
    return () => document.removeEventListener('pointerdown',close);
  },[]);
  return <div className="fund-picker" ref={root} onKeyDown={e=>{if(e.key==='Escape')setOpen(false);}}>
    <button className="secondary" aria-expanded={open} onClick={()=>setOpen(!open)}><Plus size={15}/>{ids.length ? 'Add / remove funds' : 'Choose funds'}</button>
    {open && <div className="fund-picker-menu"><div className="search-input"><Search size={14}/><input autoFocus placeholder="Search all funds…" aria-label="Find funds to compare" value={search} onChange={e=>setSearch(e.target.value)}/></div><div className="fund-picker-options">{meta.schemes.filter((s:Row)=>s.name.toLowerCase().includes(search.toLowerCase())).map((s:Row)=><label key={s.id}><input type="checkbox" checked={ids.includes(s.id)} onChange={()=>onChange(ids.includes(s.id)?ids.filter((id:string)=>id!==s.id):[...ids,s.id])}/><span>{nameOf(s.name)}</span></label>)}</div><button className="text-button" onClick={()=>setOpen(false)}>Done <ArrowRight size={13}/></button></div>}
  </div>;
}

function FundKPI({label,value,foot}: Row) {
  return <article className="kpi"><div className="kpi-label">{label}</div><strong>{value}</strong><span className="kpi-foot">{foot}</span></article>;
}

export default function FundView({meta,ids,query,revision,request,onChangeFunds,onBack,onData}: Row) {
  const [indexes,setIndexes] = useState<string[]>(()=>meta.indices.map((i:Row)=>i.id));
  const [data,setData] = useState<Row|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [method,setMethod] = useState(ids.length>1?'market':'investment');
  const [percent,setPercent] = useState(ids.length>1);
  const previousCount = useRef(ids.length);
  const key = comparisonQuery(query,ids,indexes);
  useEffect(()=>{
    if(previousCount.current<=1 && ids.length>1){setMethod('market');setPercent(true);}
    if(previousCount.current>1 && ids.length===1){setMethod('investment');setPercent(false);}
    previousCount.current=ids.length;
  },[ids.length]);
  useEffect(()=>{
    let active=true;
    if(!ids.length){setData(null);setBusy(false);setError('');return;}
    setBusy(true);setError('');
    request('/funds/compare?'+key).then((r:Row)=>{if(active)setData(r);}).catch((e:Error)=>{if(active)setError(e.message);}).finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[key,revision]);
  const traces = useMemo(()=>data?comparisonTraces(data,method,percent,ids):[],[data,method,percent,ids.join(',')]);
  const summary=data?.investment.summary||{};
  const sameFunds=data?.funds.map((f:Row)=>f.id).join(',')===ids.join(',');
  const primary=ids.length===1&&sameFunds?data?.funds[0]:null;
  const holding=primary?.holding;
  const market=data?.performance;
  const scheme=primary&&meta.schemes.find((s:Row)=>s.id===primary.id);
  return <section className="fund-view">
    <div className="fund-view-toolbar"><button className="text-button" onClick={onBack}><ArrowLeft size={15}/>All funds</button><FundPicker meta={meta} ids={ids} onChange={onChangeFunds}/></div>
    {ids.length>0 && <div className="selected-fund-chips" aria-label="Selected comparison funds">{ids.map((id:string,i:number)=><span className="fund-chip" key={id}><i style={{background:fundColors[i%fundColors.length]}}/>{nameOf(meta.schemes.find((s:Row)=>s.id===id)?.name)||'Unknown fund'}<button aria-label={'Remove '+(meta.schemes.find((s:Row)=>s.id===id)?.name||'fund')} onClick={()=>onChangeFunds(ids.filter((sid:string)=>sid!==id))}><X size={13}/></button></span>)}</div>}
    {!ids.length && <div className="empty"><div><Plus size={30}/></div><h2>Choose funds to compare</h2><p>Add one fund to see its holdings and growth. Add more funds to compare their performance with the indexes.</p></div>}
    {busy && <div className="notice"><LoaderCircle size={16} className="spin"/>Calculating fund returns and index comparisons…</div>}
    {error && <div className="notice warning">{error}</div>}
    {sameFunds&&data&&<div className={busy?'fund-view-body updating':'fund-view-body'} aria-busy={busy}>
      <div className="kpi-grid"><FundKPI label={new URLSearchParams(query).has('end') ? 'Value at period end' : 'Current value'} value={money(summary.value)} foot={ids.length===1?'Selected people’s holdings':'Combined value of selected funds'}/><FundKPI label="Remaining invested cost" value={money(summary.remaining_cost)} foot="Original cost follows transferred units"/><FundKPI label="Total gain" value={money(summary.total_gain)} foot={summary.total_return==null?'Selected ownership period':pct(summary.total_return)+' on contributions'}/><FundKPI label={ids.length===1?'Fund XIRR':'Selected funds XIRR'} value={pct(summary.xirr)} foot="Annualized · selected people and period"/></div>
      {data.investment.ledger_errors?.length>0&&<div className="notice warning"><Info size={15}/><span>Some transactions need reconciliation. Affected investment values and returns are unavailable.</span><button onClick={()=>onData('review',ids.length===1?ids[0]:'')}>Review issues <ArrowRight size={13}/></button></div>}
      {primary&&!holding&&<div className="notice"><Info size={15}/><span>No investment history for this fund and the selected people. Market performance can still be compared using its published NAVs.</span></div>}
      <section className="panel growth fund-growth"><div className="panel-header"><div><h2>{method==='market'?'Fund & index performance':ids.length===1?'Fund growth':'Selected funds growth'}</h2><p>{method==='market'?'Equal starting investment · common comparison dates':'Your actual investments · indexes replay the same cash flows'}</p></div><div className="segmented" aria-label="Chart value format"><button className={!percent?'active':''} onClick={()=>setPercent(false)}>{method==='market'?'Gain on ₹10,000':'Growth ₹'}</button><button className={percent?'active':''} onClick={()=>setPercent(true)}>Return %</button></div></div>
        <div className="fund-comparison-controls"><div className="segmented" aria-label="Comparison method"><button className={method==='investment'?'active':''} onClick={()=>setMethod('investment')}>Your investments</button><button className={method==='market'?'active':''} onClick={()=>setMethod('market')}>Market performance</button></div><div className="index-choices" aria-label="Comparison indexes">{meta.indices.map((index:Row)=><label key={index.id}><input type="checkbox" checked={indexes.includes(index.id)} onChange={()=>setIndexes(indexes.includes(index.id)?indexes.filter(id=>id!==index.id):[...indexes,index.id])}/>{index.name.replace(' TRI','')}</label>)}</div></div>
        {method==='market'&&market.error?<div className="notice warning fund-chart-message"><Info size={16}/>{market.error}</div>:<GrowthChart traces={traces} percent={percent} viewportKey={key+':'+method+':'+percent} showLegend={false} externalLegend/>}
        <div className="fund-comparison-caption">{method==='market'?<><strong>{market.start?day(market.start)+' – '+day(market.end):'Common price history required'}</strong><span>Each line starts at zero. Growth ₹ shows gain/loss on ₹10,000 invested in each fund and index at the common start; Return % shows NAV/TRI growth. These returns are independent of your purchases, redemptions and XIRR. The range ends at the earliest last published price among your selections.</span></>:<><strong>{day(summary.start)} – {day(summary.as_of)}</strong><span>{ids.length>1?'Selected funds are combined for this chart. ':''}Growth ₹ shows gains/losses from zero after opening holdings and net cash flows. Opening holdings: {money(summary.opening_value)}. Indexes receive the same opening amount and dated contributions, withdrawals and ownership transfers. Return % shows time-weighted returns from 0%.</span></>}</div>
        {method==='market'&&market.series.some((s:Row)=>s.has_gaps)&&<div className="chart-note"><Info size={13}/>Some price observations are too old for a daily comparison. Those points remain gaps.</div>}
        {method==='investment'&&data.investment.benchmarks.filter((b:Row)=>b.error).map((b:Row)=><div className="chart-note" key={b.id}><Info size={13}/>{b.name}: {b.error}</div>)}
      </section>
      {primary&&<section className="panel fund-facts"><div className="panel-header"><h2>Fund details</h2><span className="badge">{holding?.status||'No position'}</span></div><div className="fund-facts-grid">{[
        ['Units held',exactNumber(holding?.units)],['Average invested NAV',money(holding?.average_nav)],['Latest NAV',money(holding?.nav)],['NAV date',day(holding?.nav_date)],['Purchases in period',money(summary.purchases)],['Withdrawals in period',money(summary.withdrawals)],['Transfers in / out',money(summary.transfers_in)+' / '+money(summary.transfers_out)],['Realized ownership gain',money(summary.realized_gain)],['Original-cost unrealized gain',money(holding?.original_unrealized_gain)],['Time-weighted return',pct(summary.twr)],['Maximum drawdown',pct(summary.max_drawdown)],['AMFI scheme code',scheme?.code||'Needs mapping']
      ].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>}
      {ids.length>1&&<section className="panel"><div className="panel-header"><h2>Your fund positions</h2><span className="muted">Click a fund to open its details.</span></div><div className="table-scroll"><table><thead><tr>{['Fund','Units held','Remaining cost','Current value','Total gain','XIRR'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{data.funds.map((f:Row)=><tr key={f.id}><td><button className="text-button fund-name-link" onClick={()=>onChangeFunds([f.id])}>{nameOf(f.name)} <ArrowRight size={12}/></button></td><td>{exactNumber(f.holding?.units)}</td><td>{money(f.summary.remaining_cost)}</td><td>{money(f.summary.value)}</td><td>{money(f.summary.total_gain)}</td><td>{pct(f.summary.xirr)}</td></tr>)}</tbody></table></div></section>}
      {indexes.length>0&&<section className="panel"><div className="panel-header"><div><h2>Your fund XIRR vs indexes</h2><p>Each row uses that fund’s own dated cash flows, selected people and period.</p></div></div><div className="table-scroll"><table className="fund-xirr-table"><thead><tr><th>Fund</th><th>Your XIRR</th>{meta.indices.filter((i:Row)=>indexes.includes(i.id)).map((i:Row)=><th key={i.id}>{i.name}</th>)}</tr></thead><tbody>{data.funds.map((f:Row)=><tr key={f.id}><td><button className="text-button fund-name-link" onClick={()=>onChangeFunds([f.id])}>{nameOf(f.name)}</button></td><td className="emphasis">{pct(f.summary.xirr)}</td>{meta.indices.filter((i:Row)=>indexes.includes(i.id)).map((i:Row)=>{const b=f.benchmarks.find((b:Row)=>b.id===i.id);return <td key={i.id} title={b?.error||'Matched cash-flow XIRR'}>{pct(b?.xirr)}</td>;})}</tr>)}</tbody></table></div></section>}
      {method==='market'&&!market.error&&<section className="panel"><div className="panel-header"><div><h2>Equal-investment comparison</h2><p>₹10,000 each · {day(market.start)} – {day(market.end)}</p></div></div><div className="table-scroll"><table><thead><tr>{['Fund / Index','Ending value','Total return','Price date'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{market.series.map((r:Row)=><tr key={r.id}><td>{nameOf(r.name)}</td><td>{money(r.value)}</td><td>{pct(r.total_return)}</td><td>{day(r.price_date)}</td></tr>)}</tbody></table></div></section>}
      {primary&&<FundHistory meta={meta} id={ids[0]} query={query} investment={data.investment} request={request} revision={revision} onData={onData}/>}
      {data.investment.issues.length>0&&<details className="fund-notes"><summary>{data.investment.issues.length} notes about this selection</summary>{data.investment.issues.map((note:string,i:number)=><p key={i}>{note}</p>)}</details>}
    </div>}
  </section>;
}

function FundHistory({meta,id,query,investment,request,revision,onData}: Row) {
  const [tab,setTab]=useState('transactions');
  const [yearMode,setYearMode]=useState('financial');
  const [offset,setOffset]=useState(0);
  const [records,setRecords]=useState<Row[]>([]);
  const [total,setTotal]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const p=new URLSearchParams(query);p.set('fund',id);p.delete('funds');
  const base=p.toString();p.set('limit','50');p.set('offset',String(offset));
  const key=p.toString();
  useEffect(()=>setOffset(0),[base]);
  useEffect(()=>{
    let active=true;
    if(tab!=='transactions')return;
    setBusy(true);setError('');
    request('/data/transactions?'+key).then((r:Row)=>{if(active){setRecords(r.rows);setTotal(r.total);}}).catch((e:Error)=>{if(active)setError(e.message);}).finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[tab,key,revision]);
  const person=(id:string)=>meta.people.find((p:Row)=>p.id===id)?.name||'External recipient';
  const rows=tab==='lots'?investment.lots:tab==='yearly'?investment.yearly.filter((r:Row)=>r.mode===yearMode):tab==='transfers'?investment.transfer_details:records;
  return <section className="panel fund-history"><div className="panel-header"><h2>Fund history</h2><button className="text-button" onClick={()=>onData('transactions',id)}>Open detailed data <ArrowRight size={13}/></button></div><div className="detail-tabs">{[['transactions','Transactions'],['lots','Purchase lots'],['yearly','Yearly investments'],['transfers','Transfers']].map(([value,label])=><button key={value} className={tab===value?'active':''} onClick={()=>setTab(value)}>{label}</button>)}</div>
    <div className="fund-history-tools">{tab==='yearly'?<div className="segmented"><button className={yearMode==='financial'?'active':''} onClick={()=>setYearMode('financial')}>Financial year</button><button className={yearMode==='calendar'?'active':''} onClick={()=>setYearMode('calendar')}>Calendar year</button></div>:<span className="muted">{tab==='transactions'?'Source entries retain their calculation treatment.':'Original purchase dates and costs are preserved.'}</span>}{['transactions','lots'].includes(tab)&&<a className="text-button" href={'/api/export/'+tab+'.csv?'+base}><Download size={13}/>CSV</a>}</div>
    {busy&&tab==='transactions'&&<div className="notice fund-chart-message"><LoaderCircle size={14} className="spin"/>Reading fund transactions…</div>}{error&&tab==='transactions'&&<div className="notice warning fund-chart-message">{error}</div>}
    <div className="table-scroll"><table><thead><tr>{(tab==='transactions'?['Date','Person','Type','Units','NAV','Amount','Calculation treatment']:tab==='lots'?['Acquired','Owner','Units','Original cost','Ownership basis']:tab==='yearly'?['Year','Purchases','Withdrawals','Net invested','Transfers in','Transfers out']:['Date','From → To','Units','Original cost','Market value']).map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r:Row,i:number)=><tr key={r.id||i} className={r.excluded?'excluded-row':''}>
      {tab==='transactions'?<><td>{day(r.date)}</td><td>{r.person_name}</td><td>{r.type}</td><td>{exactNumber(r.units)}</td><td>{money(r.nav)}</td><td>{money(r.amount)}</td><td title={r.excluded||r.treatment}>{r.treatment}</td></>:tab==='lots'?<><td>{day(r.date)}</td><td>{person(r.person)}</td><td>{exactNumber(r.units)}</td><td>{money(r.cost)}</td><td>{money(r.basis)}</td></>:tab==='yearly'?<><td>{r.year}</td>{['purchases','withdrawals','net','transfer_in','transfer_out'].map(k=><td key={k}>{money(r[k]||0)}</td>)}</>:<><td>{day(r.date)}</td><td>{person(r.sender)} → {person(r.recipient)}</td><td>{exactNumber(r.units)}</td><td>{money(r.original_cost)}</td><td>{money(r.market_value)}</td></>}
    </tr>)}</tbody></table>{!rows.length&&<div className="small-empty">No {tab==='yearly'?'yearly investments':tab==='lots'?'remaining purchase lots':tab} for this selection.</div>}</div>
    {tab==='transactions'&&<div className="pagination"><span>{total?`${offset+1}–${Math.min(offset+50,total)} of ${total}`:'0 entries'}</span><button className="icon-btn" aria-label="Previous fund transactions" disabled={!offset||busy} onClick={()=>setOffset(Math.max(0,offset-50))}><ChevronLeft size={16}/></button><button className="icon-btn" aria-label="Next fund transactions" disabled={offset+50>=total||busy} onClick={()=>setOffset(offset+50)}><ChevronRight size={16}/></button></div>}
  </section>;
}
