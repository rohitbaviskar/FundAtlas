import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Plotly from 'plotly.js-cartesian-dist-min';
import { Activity, ArrowDownLeft, ArrowRight, ArrowRightLeft, ArrowUpRight, BarChart3, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Database, Download, FileSpreadsheet, Filter, Info, Layers3, LoaderCircle, Plus, RefreshCw, Search, ShieldCheck, SlidersHorizontal, Trash2, TriangleAlert, TrendingUp, Users, X } from 'lucide-react';
import './style.css';
import GrowthChart from './GrowthChart';
import FundView from './FundView';
import PerformancePeriod from './PerformancePeriod';
import { investmentTraces } from './performance.js';
import { readNavigation, navigationHash } from './fundComparison.js';
import { money, num, pct, exactNumber, reviewCounts, filterReviewGroups } from './display.js';

type Row = Record<string, any>;
const dateLabel = (d: any) => d ? new Date(d.slice(0, 10) + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Not loaded';
const shortFund = (s: string) => s?.replace(/ Direct( Plan)? Growth| Direct Plan Growth| Direct Growth/g, '').replace(/ Fund$/, '');
const colors = ['#17634b', '#4c8dce', '#9673c8', '#c69b3f', '#cf7360'];
const benchmarkColors: Row = { 'NIFTY 50': colors[1], 'NIFTY LARGEMIDCAP 250': colors[2], 'NIFTY 500': colors[3], 'NIFTY MIDCAP 150': colors[4] };
async function api(path: string, options?: RequestInit) {
  const res = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  if (!res.ok) { const body = await res.json().catch(() => ({})); throw Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`); }
  return res.json();
}

function Chart({ data, height = 300, layout = {} }: { data: any[], height?: number, layout?: Row }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const element = ref.current as HTMLDivElement & { _fullLayout?: { width: number } };
    Plotly.react(element, data.map(trace => ({ ...trace, hovertemplate: trace.hovertemplate || (layout.yaxis?.ticksuffix === '%' ? '%{y:.2f}%' : '₹%{y:,.2f}') + '<extra>%{fullData.name}</extra>' })), {
      autosize: false, width: element.clientWidth || undefined, height, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { family: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif', size: 11, color: '#758079' },
      margin: { l: 58, r: 20, t: 16, b: 45 }, showlegend: true,
      legend: { orientation: 'h', x: 0, y: -0.2, font: { size: 10 } },
      xaxis: { gridcolor: '#f0f2ef', showline: false, zeroline: false, tickformat: '%Y', nticks: 8 },
      yaxis: { gridcolor: '#edf0ed', zeroline: false, tickformat: '.3~s', tickprefix: '₹', automargin: true },
      hovermode: 'x unified', hoverlabel: { bgcolor: '#fff', bordercolor: '#dce4dd', font: { color: '#24372c' } }, ...layout
    }, { displayModeBar: false, responsive: false, scrollZoom: false });
    const observer = new ResizeObserver(() => { const width = element.clientWidth; if (width > 0 && element._fullLayout && Math.abs(element._fullLayout.width - width) >= 1) Plotly.relayout(element, { width, height, autosize: false }); });
    observer.observe(element);
    return () => { observer.disconnect(); Plotly.purge(element); };
  }, [data, height, layout]);
  return <div ref={ref} className="plot" style={{ height, minHeight: height }} />;
}

function App() {
  const [route, setRoute] = useState(() => readNavigation(window.location.hash));
  const tab = route.tab;
  const navigate = (next: Row) => { setRoute(next); const hash = navigationHash(next); if (window.location.hash !== hash) window.location.hash = hash; };
  const setTab = (tab: string) => navigate({ tab, funds: [] });
  useEffect(() => { const sync = () => setRoute(readNavigation(window.location.hash)); window.addEventListener('hashchange', sync); return () => window.removeEventListener('hashchange', sync); }, []);
  const [meta, setMeta] = useState<Row>({ people: [], schemes: [], sources: [], today: new Date().toISOString().slice(0, 10) });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [range, setRange] = useState({ start: '', end: '' });
  const [data, setData] = useState<Row | null>(null);
  const [job, setJob] = useState<Row>({ running: false });
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [method, setMethod] = useState(false);
  const [detailKind, setDetailKind] = useState('transactions');
  const [yearMode, setYearMode] = useState('financial');
  const [fund, setFund] = useState('');
  const [chartMode, setChartMode] = useState('value');
  const remoteRevision = useRef('');
  const serverInstance = useRef('');
  const openFunds = (ids: string[]) => { setFund(''); navigate({ tab: 'Fund details', funds: ids }); window.scrollTo({ top: 0 }); };

  const reload = () => setRevision(x => x + 1);
  const notify = (message: string) => { setToast(message); setTimeout(() => setToast(''), 5000); };
  useEffect(() => { api('/meta').then(m => { setMeta(m); setJob(m.job); remoteRevision.current = m.job.data_revision || ''; serverInstance.current = m.job.server_instance || ''; setSelected(previous => previous === null ? m.people.map((p: Row) => p.id) : [...new Set([...previous, ...m.people.filter((p: Row) => !meta.people.some((old: Row) => old.id === p.id)).map((p: Row) => p.id)])]); }).catch(e => setError(e.message)); }, [revision]);
  const query = new URLSearchParams();
  if (selected !== null) query.set('people', selected.join(','));
  if (range.start) query.set('start', range.start);
  if (range.end) query.set('end', range.end);
  if (fund && tab === 'Data details') query.set('fund', fund);
  const qs = query.toString();
  useEffect(() => {
    if (selected === null) return;
    let active = true;
    setLoading(true); setError('');
    api('/dashboard?' + qs).then(r => { if (active) setData(r); }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [qs, revision]);
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const j = await api('/refresh');
        if (serverInstance.current && j.server_instance && serverInstance.current !== j.server_instance) { window.location.reload(); return; }
        if (j.data_revision && remoteRevision.current && remoteRevision.current !== j.data_revision) reload();
        remoteRevision.current = j.data_revision || remoteRevision.current;
        setJob(prev => { if (prev.running && !j.running) { notify(j.errors?.length ? 'Refresh finished. Review data coverage for remaining gaps.' : 'Your portfolio is up to date.'); } return j; });
      } catch { /* keep current data visible while server reconnects */ }
    }, 1500);
    return () => clearInterval(id);
  }, []);
  async function refresh() { try { setJob(await api('/refresh', { method: 'POST' })); } catch (e: any) { setError(e.message); } }
  const openData = (kind = 'transactions') => { setDetailKind(kind); setTab('Data details'); };
  const summary = data?.summary || {};
  const ledgerErrors = data?.issues?.filter((x: string) => x.startsWith('Ledger error')) || [];
  const hasSelection = selected === null || selected.length > 0;
  const yearRows = (data?.yearly || []).filter((r: Row) => r.mode === yearMode);
  const moneyAxis = chartMode === 'value';
  const growthTraces = useMemo(() => data ? investmentTraces(data, !moneyAxis, 'Portfolio', colors[0], benchmarkColors) : [], [data, moneyAxis]);
  return <>
    <header className="topbar"><div className="nav-wrap"><button className="brand" onClick={() => setTab('Overview')}><span className="brandmark"><i/><i/><i/></span>Portfolio<span className="brand-dot">.</span></button><nav aria-label="Main navigation">{['Overview', 'Funds', 'Compare', 'Yearly', 'Transfers', 'Data details'].map(t => <button key={t} className={(tab === t || t === 'Funds' && tab === 'Fund details' && route.funds.length === 1 || t === 'Compare' && tab === 'Fund details' && route.funds.length !== 1) ? 'active' : ''} onClick={() => { if (t === 'Compare') openFunds([]); else { setTab(t); if (t !== 'Data details') setFund(''); } }}>{t}</button>)}</nav><span className="private"><ShieldCheck size={14}/> Private & local</span><button className="icon-btn" title="Calculation methodology" aria-label="Calculation methodology" onClick={() => setMethod(true)}><CircleHelp size={18}/></button></div></header>
    <main>
      <div className="page-header"><div><div className="eyebrow">YOUR INVESTMENT WORKSPACE</div><h1>{tab === 'Fund details' ? (route.funds.length === 1 ? shortFund(meta.schemes.find((s: Row) => s.id === route.funds[0])?.name) || 'Fund details' : 'Compare funds') : tab === 'Overview' ? 'Portfolio overview' : tab === 'Funds' ? 'Your funds' : tab === 'Yearly' ? 'Investment history' : tab === 'Transfers' ? 'Unit transfers' : 'Data details'}</h1></div><div className="header-controls"><div className="people" aria-label="Select people">{meta.people.map((p: Row) => <button key={p.id} aria-pressed={selected?.includes(p.id) || false} className={selected?.includes(p.id) ? 'selected' : ''} onClick={() => setSelected(old => old?.includes(p.id) ? old.filter(x => x !== p.id) : [...(old || []), p.id])}><span className="person-circle">{p.name.slice(0, 1)}</span>{p.name.split(' ')[0]}{selected?.includes(p.id) && <Check size={13}/>}</button>)}</div><PerformancePeriod today={meta.today} range={range} onChange={setRange}/><button className="primary" onClick={refresh} disabled={job.running}>{job.running ? <LoaderCircle size={15} className="spin"/> : <RefreshCw size={15}/>} {job.running ? 'Refreshing' : 'Refresh data'}</button></div></div>
      <div className="context-row"><span><span className={'status-dot ' + (summary.nav_date ? 'green' : 'amber')}/>{tab === 'Fund details' ? 'Fund comparisons · selected people and period' : summary.nav_date ? `NAVs through ${dateLabel(summary.nav_date)}` : 'Refresh to load published prices'}</span><span>{meta.sources.length} files<span className="sep">/</span>{meta.schemes.length} funds<span className="sep">/</span>{selected?.length || 0} {selected?.length === 1 ? 'person' : 'people'} selected</span></div>
      {job.running && <div className="refresh-banner"><LoaderCircle className="spin" size={17}/><div><strong>{job.message}</strong><span>Historical prices are saved as they arrive. You can keep browsing.</span></div><progress value={job.completed || 0} max={job.total || 1}/></div>}
      {tab !== 'Fund details' && ledgerErrors.length > 0 && <div className="notice warning"><TriangleAlert size={17}/><span><strong>Transaction history needs review.</strong> Some transactions exceed available units. Affected portfolio returns are unavailable.</span><button onClick={() => openData('review')}>Review entries <ArrowRight size={14}/></button></div>}
      {tab !== 'Fund details' && !!data?.review_summary?.unresolved && <div className="notice warning"><TriangleAlert size={17}/><span><strong>{data.review_summary.unresolved} duplicate groups need review.</strong> Purchases and redemptions are checked. Totals include every entry that has not been excluded.</span><button onClick={() => openData('review')}>Review entries <ArrowRight size={14}/></button></div>}
      {tab !== 'Fund details' && data?.transfer_details?.some((t: Row) => t.recipient_unmatched) && <div className="notice warning"><ArrowRightLeft size={17}/><span><strong>A gift recipient has not been matched.</strong> CAS-confirmed gifts are outgoing ownership transfers. Add the recipient's matching transactions to include their units in combined totals.</span><button onClick={() => setTab('Transfers')}>View transfer <ArrowRight size={14}/></button></div>}
      {tab !== 'Fund details' && !job.running && !ledgerErrors.length && data?.issues?.length > 0 && <div className="notice"><Info size={17}/><span>{data.issues.length} data {data.issues.length === 1 ? 'note' : 'notes'} · {data.issues[0]}</span><button onClick={() => openData('status')}>Review <ArrowRight size={14}/></button></div>}
      {error && <div className="notice warning">{error}<button onClick={reload}>Try again</button></div>}
      {!hasSelection ? <Empty icon={<Users size={32}/>} title="Choose a person to get started" text="Select one person above, or select multiple people to see their combined portfolio."/> : !data ? <Empty icon={<LoaderCircle size={30} className="spin"/>} title="Reading your portfolio" text="Loading transaction history and calculations…"/> : <div className={loading ? 'content updating' : 'content'}>
        {(tab === 'Overview' || tab === 'Funds') && <>
          <section className="kpi-grid">
            <KPI label={range.end ? "Value at period end" : "Current value"} value={money(summary.value)} foot={summary.value == null ? (ledgerErrors.length ? 'Reconcile transactions to calculate' : 'Published NAVs needed') : `${summary.active_funds} funds ${range.end ? 'held at period end' : 'currently held'}`} icon={<Layers3 size={17}/>}/>
            <KPI label="Remaining invested cost" value={money(summary.remaining_cost)} foot="Original purchase cost of units held" icon={<ArrowDownLeft size={17}/>}/>
            <KPI label="Total gain" value={money(summary.total_gain)} foot={summary.total_return == null ? 'During the selected ownership period' : `${pct(summary.total_return)} on contributions`} positive={summary.total_gain >= 0 && summary.total_gain != null} icon={<TrendingUp size={17}/>}/>
            <KPI label="Portfolio XIRR" value={pct(summary.xirr)} foot="Annualized · selected ownership period" positive={summary.xirr >= 0 && summary.xirr != null} icon={<Activity size={17}/>}/>
          </section>
          {tab === 'Overview' && <>
            <section className="panel growth"><div className="panel-header"><div><h2>Portfolio growth</h2><p>Gains from zero · same opening investment and later cash flows.</p></div><div className="segmented"><button className={moneyAxis ? 'active' : ''} onClick={() => setChartMode('value')}>Growth ₹</button><button className={!moneyAxis ? 'active' : ''} onClick={() => setChartMode('return')}>Return %</button></div></div>
              <GrowthChart traces={growthTraces} percent={!moneyAxis} viewportKey={qs + ':' + chartMode}/>
              <div className="fund-comparison-caption"><strong>{dateLabel(summary.start)} – {dateLabel(summary.as_of)}</strong><span>Growth ₹ shows gains/losses after opening holdings and net cash flows; Return % shows time-weighted returns from 0%. Opening holdings: {money(summary.opening_value)}. Portfolio value above remains the actual holdings value at the period end.</span></div>
              {data.benchmarks.some((b: Row) => b.error) && <div className="chart-note"><Info size={13}/><span>Benchmark comparison unavailable: {data.benchmarks.find((b: Row) => b.error)?.error}.</span><button onClick={() => openData(ledgerErrors.length ? 'review' : 'indices')}>Data details <ArrowRight size={12}/></button></div>}
            </section>
          </>}
          <section className="panel"><div className="panel-header"><h2>Your funds</h2><div className="small-actions"><button className="text-button" onClick={() => openFunds([])}><Plus size={14}/> Compare funds</button><a href={'/api/export/lots.csv?' + qs} className="text-button"><Download size={14}/> Export lots</a></div></div><FundTable funds={data.funds} onSelect={(id: string) => openFunds([id])}/></section>
          {tab === 'Overview' && <div className="bottom-grid"><section className="panel"><div className="panel-header"><h2>Yearly investments</h2><YearToggle value={yearMode} change={setYearMode}/></div><YearChart rows={yearRows}/><button className="panel-link" onClick={() => setTab('Yearly')}>Explore fund-wise breakdown <ArrowRight size={14}/></button></section><section className="panel movement"><div className="panel-header"><h2>Cash flows</h2><ArrowRightLeft size={17} className="muted"/></div><dl><dt>Purchases</dt><dd>{money(summary.purchases)}</dd><dt>Withdrawals</dt><dd>{money(summary.withdrawals)}</dd><dt>Net cash invested</dt><dd>{money(summary.net_contributions)}</dd><dt>Transfers in / out</dt><dd>{money(summary.transfers_in)} / {money(summary.transfers_out)}</dd></dl><p className="note">Transfers cancel when both people are selected.</p><button className="panel-link" onClick={() => setTab('Transfers')}>Manage unit transfers <ArrowRight size={14}/></button></section></div>}
          {tab === 'Overview' && <div className="bottom-grid"><section className="panel"><div className="panel-header"><h2>Performance beyond contributions</h2><button className="icon-btn" aria-label="Read return methodology" onClick={() => setMethod(true)}><Info size={15}/></button></div><div className="secondary-kpis"><div><span>Time-weighted return</span><strong>{pct(summary.twr)}</strong></div><div><span>Maximum drawdown</span><strong>{pct(summary.max_drawdown)}</strong></div><div><span>Realized gains</span><strong>{money(summary.realized_gain)}</strong></div></div><Chart height={185} data={[{ x: data.series.map((r: Row) => r.date), y: data.series.map((r: Row) => r.drawdown == null ? null : r.drawdown * 100), type: 'scatter', mode: 'lines', line: { color: '#b37b66', width: 1.5 }, fill: 'tozeroy', fillcolor: '#b37b6612', name: 'Drawdown' }]} layout={{ showlegend: false, margin: { l: 50, r: 20, t: 10, b: 30 }, yaxis: { ticksuffix: '%', gridcolor: '#f0f2ef' } }}/></section><section className="panel"><div className="panel-header"><h2>Allocation</h2><span className="muted">{summary.value == null ? 'Available values only' : 'By current value'}</span></div>{data.funds.filter((f: Row) => f.balance_group === 'active').slice(0, 6).map((f: Row, i: number) => { const total = data.funds.reduce((a: number, f: Row) => a + (f.market_value || 0), 0); return <div className="allocation" key={f.scheme}><div><span>{shortFund(f.name)}</span><strong>{total ? (f.market_value / total * 100).toFixed(1) : '0'}%</strong></div><div className="allocation-track"><i style={{ width: `${total ? f.market_value / total * 100 : 0}%`, background: colors[i % 4] }}/></div></div>; })}{!summary.nav_date && <div className="small-empty">Allocation appears after prices are downloaded.</div>}</section></div>}
        </>}
        {tab === 'Fund details' && <FundView meta={meta} ids={route.funds} query={qs} revision={revision} request={api} onChangeFunds={openFunds} onBack={() => setTab('Funds')} onData={(kind: string, id: string) => { setFund(id); setDetailKind(kind); setTab('Data details'); }}/> }
        {tab === 'Yearly' && <Yearly data={data} mode={yearMode} setMode={setYearMode} qs={qs}/>}
        {tab === 'Transfers' && <Transfers data={data} meta={meta} refresh={reload} notify={notify}/>}
        {tab === 'Data details' && <DataDetails meta={meta} data={data} query={query} fund={fund} setFund={setFund} kind={detailKind} setKind={setDetailKind} revision={revision} reload={reload} notify={notify}/>}
      </div>}
      <footer><span><ShieldCheck size={12}/> Your files stay on your machine.</span><button onClick={() => setMethod(true)}>Calculation methodology <ArrowUpRight size={12}/></button><span>AMFI NAVs · NSE total return indices</span></footer>
    </main>
    {toast && <div className="toast"><Check size={17}/>{toast}<button aria-label="Dismiss notification" onClick={() => setToast('')}><X size={14}/></button></div>}
    {method && <Modal title="How your returns are calculated" close={() => setMethod(false)}><div className="method"><h3>Cost and units</h3><p>Purchases add units and their recorded amount to original cost. Redemptions use FIFO purchase lots. Average invested NAV is remaining original cost divided by remaining units. Rounded exports can leave small unit differences; these are disclosed, never hidden.</p><h3>Transfers</h3><p>Original purchase dates and cost move with the actual lots. For a single owner, transfer-date market value is a synthetic contribution or withdrawal for XIRR. When both owners are selected, the cash flows cancel and original history continues. Specific lots can be selected; otherwise FIFO is explicit.</p><h3>Gains and XIRR</h3><p>Total gain = ending value + withdrawals + payouts + outgoing boundary transfers − purchases − incoming boundary transfers − period opening value. XIRR uses dated ownership cash flows, a 365-day year, and ending market value. A selected period starts with a synthetic opening investment at the previous day's closing value. XIRR may be unavailable when the cash flows have no valid solution.</p><h3>Returns and benchmarks</h3><p>Absolute return divides total gain by all negative ownership cash flows, including a period's opening value. TWR uses end-of-day cash flows: (closing value + investor cash flow) / prior closing value. Maximum drawdown uses that TWR series, so withdrawals do not masquerade as market losses. TRI benchmarks seed opening holdings with the same value at the previous closing TRI, then replay later cash flows on the next available trading day, within seven days. Negative simulated holdings make that comparison unavailable.</p><h3>Prices and dates</h3><p>Published NAVs and TRI values are stored with their source and date. If a fund launch-day execution predates its first public quote by up to seven days, the statement execution NAV fills that initial date and is labeled as such. Calendar-day charts carry the latest known value, with its actual quote date visible in Data details. Trading-day gaps and delayed prices remain flagged. Growth ₹ starts at zero and shows gains/losses after subtracting opening holdings and net cash flows. Return % shows time-weighted returns for the portfolio and each simulated benchmark, starting at 0%. Period selectors recalculate the window; zoom only changes what is visible and Reset zoom restores the selected window. All values are INR, before personal taxes. Refresh runs at 7 AM IST while the container runs, and catches up on startup.</p></div></Modal>}
  </>;
}

function KPI({ label, value, foot, icon, positive = false }: Row) { return <article className="kpi"><div className="kpi-label">{label}<span>{icon}</span></div><strong className={positive ? 'positive' : ''}>{value}</strong><span className="kpi-foot">{foot}</span></article>; }
function Empty({ icon, title, text }: Row) { return <div className="empty"><div>{icon}</div><h2>{title}</h2><p>{text}</p></div>; }
function Modal({ title, close, children }: any) { return <div className="modal-backdrop" onClick={close}><section className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}><div className="modal-head"><h2>{title}</h2><button aria-label="Close dialog" className="icon-btn" onClick={close}><X size={20}/></button></div>{children}</section></div>; }
function YearToggle({ value, change }: any) { return <div className="segmented"><button className={value === 'financial' ? 'active' : ''} onClick={() => change('financial')}>Financial year</button><button className={value === 'calendar' ? 'active' : ''} onClick={() => change('calendar')}>Calendar year</button></div>; }
function YearChart({ rows }: { rows: Row[] }) { return <Chart height={240} data={['purchases', 'withdrawals'].map((field, i) => ({ x: rows.map(r => r.year), y: rows.map(r => r[field] || 0), type: 'bar', name: i ? 'Withdrawals' : 'Purchases', marker: { color: i ? '#cbd3cc' : '#287455' }, width: 0.28 }))} layout={{ barmode: 'group', xaxis: { type: 'category', tickfont: { size: 10 } }, bargap: 0.4, margin: { l: 60, r: 15, t: 10, b: 50 }, legend: { orientation: 'h', y: -0.2 } }}/>; }

function FundTable({ funds, onSelect }: any) {
  const [search, setSearch] = useState('');
  const [balance, setBalance] = useState('active');
  const [sort, setSort] = useState('market_value');
  const [direction, setDirection] = useState(-1);
  const columns = [['remaining_cost', 'Remaining cost'], ['average_nav', 'Avg invested NAV'], ['nav', 'Current NAV'], ['market_value', 'Current value'], ['total_gain', 'Total gain'], ['total_return', 'Return'], ['xirr', 'XIRR']];
  const matchesBalance = (f: Row) => balance === 'all' || (balance === 'zero' ? f.balance_group === 'zero' : f.balance_group !== 'zero');
  const filtered = funds.filter((f: Row) => matchesBalance(f) && f.name.toLowerCase().includes(search.toLowerCase())).sort((a: Row, b: Row) => ((a[sort] || 0) - (b[sort] || 0)) * direction);
  const counts: Row = { all: funds.length, zero: funds.filter((f: Row) => f.balance_group === 'zero').length, active: funds.filter((f: Row) => f.balance_group !== 'zero').length };
  return <><div className="fund-filter-bar"><div className="segmented" aria-label="Fund balance filter">{[['active', 'Active'], ['zero', 'Zero'], ['all', 'All']].map(([id, label]) => <button key={id} className={balance === id ? 'active' : ''} aria-pressed={balance === id} onClick={() => setBalance(id)}>{label} ({counts[id]})</button>)}</div><span className="muted">Zero includes balances of ₹5 or less.</span></div><div className="table-search"><Search size={15}/><input aria-label="Search funds" placeholder="Find a fund…" value={search} onChange={e => setSearch(e.target.value)}/><span>{filtered.length} funds</span></div><div className="table-scroll"><table className="fund-table"><thead><tr><th>Fund</th>{columns.map(([key, label]) => <th key={key}><button onClick={() => { setSort(key); setDirection(sort === key ? -direction : -1); }}>{label}{sort === key && <ChevronDown size={12} style={{ transform: direction === 1 ? 'rotate(180deg)' : undefined }}/>}</button></th>)}</tr></thead><tbody>{filtered.map((f: Row, i: number) => <tr key={f.scheme} title="Open fund details" className={f.balance_group === 'zero' ? 'exited' : ''} onClick={() => onSelect(f.scheme)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(f.scheme); } }}><td><div className="fund-cell"><span className={'fund-avatar tone-' + i % 4}>{f.name.split(' ').slice(0, 2).map((s: string) => s[0]).join('')}</span><div><strong>{shortFund(f.name)}</strong><span>Direct · Growth <i/> <em className={f.balance_group === 'active' ? 'held' : ''}>{f.balance_group === 'zero' ? (f.is_residual ? 'Small balance' : 'Zero balance') : f.market_value == null ? 'Needs review' : 'Active'}</em></span></div></div></td><td>{money(f.remaining_cost)}</td><td>{money(f.average_nav, 2)}</td><td title={dateLabel(f.nav_date)}>{money(f.nav, 2)}</td><td className="emphasis">{money(f.market_value)}</td><td className={f.total_gain >= 0 ? 'positive' : 'negative'}>{money(f.total_gain)}</td><td className={f.total_return >= 0 ? 'positive' : 'negative'}>{pct(f.total_return)}</td><td className={f.xirr >= 0 ? 'positive' : 'negative'}>{pct(f.xirr)}</td></tr>)}</tbody></table>{filtered.length === 0 && <div className="small-empty">No funds match your search.</div>}</div><div className="table-foot"><Info size={12}/> Filters keep all underlying units and values in portfolio calculations. Cost follows original purchase lots. Click a fund for details.</div></>;
}

function Yearly({ data, mode, setMode, qs }: Row) {
  const [metric, setMetric] = useState('purchases');
  const ys = data.yearly.filter((r: Row) => r.mode === mode);
  const fys = data.yearly_funds.filter((r: Row) => r.mode === mode);
  const funds = [...new Set(fys.map((r: Row) => r.scheme))] as string[];
  const values = funds.map(sid => ys.map((y: Row) => fys.find((r: Row) => r.scheme === sid && r.year === y.year)?.[metric] || 0));
  return <><div className="section-tools"><YearToggle value={mode} change={setMode}/><span className="muted">{mode === 'financial' ? '1 April – 31 March' : '1 January – 31 December'}</span><button className="text-button" onClick={() => { const header = ['Fund', ...ys.map((y: Row) => y.year)]; const content = [header, ...funds.map((sid, i) => [data.funds.find((f: Row) => f.scheme === sid)?.name, ...values[i]])].map(row => row.map((x: any) => '"' + String(x ?? '').replaceAll('"', '""') + '"').join(',')).join('\n'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['\ufeff' + content], { type: 'text/csv' })); a.download = 'yearly-fund-breakdown.csv'; a.click(); URL.revokeObjectURL(a.href); }}><Download size={15}/> Export breakdown</button></div><section className="panel"><div className="panel-header"><h2>Year by year</h2><span className="muted">Transfers shown separately below</span></div><YearChart rows={ys}/><div className="table-scroll"><table><thead><tr><th>Year</th>{['Purchases', 'Withdrawals', 'Net invested', 'Transfers in', 'Transfers out'].map(s => <th key={s}>{s}</th>)}</tr></thead><tbody>{ys.map((r: Row) => <tr key={r.year}><td className="emphasis">{r.year}</td>{['purchases', 'withdrawals', 'net', 'transfer_in', 'transfer_out'].map(k => <td key={k}>{money(r[k] || 0)}</td>)}</tr>)}</tbody><tfoot><tr><td>Total</td>{['purchases', 'withdrawals', 'net', 'transfer_in', 'transfer_out'].map(k => <td key={k}>{money(ys.reduce((a: number, r: Row) => a + (r[k] || 0), 0))}</td>)}</tr></tfoot></table></div></section><section className="panel"><div className="panel-header"><h2>Fund-wise investment history</h2><select aria-label="Yearly breakdown metric" value={metric} onChange={e => setMetric(e.target.value)}><option value="purchases">Purchases</option><option value="withdrawals">Withdrawals</option><option value="net">Net invested</option><option value="transfer_in">Transfers in</option><option value="transfer_out">Transfers out</option></select></div><div className="table-scroll"><table className="heatmap"><thead><tr><th>Fund</th>{ys.map((y: Row) => <th key={y.year}>{y.year}</th>)}<th>Total</th></tr></thead><tbody>{funds.map((sid, i) => <tr key={sid}><td>{shortFund(data.funds.find((f: Row) => f.scheme === sid)?.name)}</td>{values[i].map((v: number, j: number) => <td key={j} style={{ backgroundColor: v ? `rgba(36,111,79,${Math.min(0.25, Math.abs(v) / Math.max(1, ...values.flat().map(Math.abs)) * 0.25) + 0.03})` : undefined }}>{v ? money(v) : '—'}</td>)}<td className="emphasis">{money(values[i].reduce((a, b) => a + b, 0))}</td></tr>)}</tbody></table></div></section></>;
}

function Transfers({ data, meta, refresh, notify }: Row) {
  const [open, setOpen] = useState(false);
  const [addPerson, setAddPerson] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState<Row>({ date: meta.today, sender: meta.people[0]?.id || '', recipient: meta.people[1]?.id || '', scheme: '', units: '', nav: '', note: '' });
  const [specific, setSpecific] = useState(false);
  const [allocations, setAllocations] = useState<Row>({});
  const [lots, setLots] = useState<Row[]>([]);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (form.sender && form.scheme && form.date) api('/data/lots?' + new URLSearchParams({ people: form.sender, fund: form.scheme, end: form.date, limit: '500' })).then(r => setLots(r.rows)).catch(() => setLots([])); }, [form.sender, form.scheme, form.date]);
  async function submit(e: React.FormEvent) { e.preventDefault(); setSaving(true); setError(''); try { await api('/transfers', { method: 'POST', body: JSON.stringify({ ...form, units: Number(form.units), nav: form.nav ? Number(form.nav) : null, lots: specific ? Object.entries(allocations).filter(([, v]) => Number(v) > 0).map(([lot_id, units]) => ({ lot_id, units: Number(units) })) : [] }) }); setOpen(false); refresh(); notify('Transfer recorded. Original purchase lots preserved.'); } catch (e: any) { setError(e.message); } finally { setSaving(false); } }
  const person = (id: string) => id.startsWith('external-gift:') ? 'Recipient not yet matched' : meta.people.find((p: Row) => p.id === id)?.name.split(' ')[0] || id;
  return <><div className="transfer-explainer"><div className="transfer-symbol"><ArrowRightLeft size={25}/></div><div><h2>Move units. Keep their history.</h2><p>Original purchase cost and dates follow the units. Each person's XIRR starts or ends at the transfer-date market value.</p></div><button className="primary" onClick={() => { setOpen(true); setError(''); }}><Plus size={15}/> Record transfer</button></div><div className="section-tools"><span className="muted">Only record actual unit transfers. Cash redemptions remain transactions.</span><button className="text-button" onClick={() => setAddPerson(true)}><Users size={15}/> Add person</button></div><section className="panel"><div className="panel-header"><h2>Transfer history</h2><span className="count">{data.transfer_details.length}</span></div>{data.transfer_details.length ? <div className="table-scroll"><table><thead><tr>{['Date', 'Fund', 'From → To', 'Units', 'Original cost', 'Market value', 'Allocation', 'Evidence', ''].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>{data.transfer_details.map((t: Row) => <tr key={t.id}><td>{dateLabel(t.date)}</td><td>{shortFund(meta.schemes.find((s: Row) => s.id === t.scheme)?.name)}</td><td>{person(t.sender)} → {person(t.recipient)}</td><td>{exactNumber(t.units)}</td><td>{money(t.original_cost)}</td><td>{money(t.market_value)}</td><td>{t.allocation_method}</td><td title={t.note}>{t.source_transactions?.length ? 'CAS verified' : t.note || 'Manual'}</td><td><button className="icon-btn" aria-label="Delete transfer" onClick={async () => { if (window.confirm(t.source_transactions?.length ? 'Remove this CAS-verified transfer and restore its source rows as cash transactions? This choice persists on refresh.' : 'Remove this transfer and recalculate ownership?')) { await api('/transfers/' + t.id, { method: 'DELETE' }); refresh(); } }}><Trash2 size={14}/></button></td></tr>)}</tbody></table></div> : <Empty icon={<ArrowRightLeft size={30}/>} title="No transfers recorded" text="Add a recipient, then record the date, fund and units transferred."/>}</section>
    {open && <Modal title="Record a unit transfer" close={() => setOpen(false)}><form onSubmit={submit} className="form"><div className="form-grid"><label>From<select required value={form.sender} onChange={e => setForm({ ...form, sender: e.target.value })}>{meta.people.map((p: Row) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>To<select required value={form.recipient} onChange={e => setForm({ ...form, recipient: e.target.value })}><option value="">Choose recipient</option>{meta.people.filter((p: Row) => p.id !== form.sender).map((p: Row) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div><label>Fund<select required value={form.scheme} onChange={e => { setForm({ ...form, scheme: e.target.value }); setAllocations({}); }}><option value="">Choose a fund</option>{meta.schemes.map((s: Row) => <option key={s.id} value={s.id}>{shortFund(s.name)}</option>)}</select></label><div className="form-grid"><label>Effective date<input required type="date" max={meta.today} value={form.date} onChange={e => setForm({ ...form, date: e.target.value })}/></label><label>Units<input required type="number" step="any" min="0" value={form.units} onChange={e => setForm({ ...form, units: e.target.value })}/></label></div><label>Transfer-date NAV <span className="muted">optional when published NAV is loaded</span><input type="number" min="0" step="any" placeholder="Use published NAV" value={form.nav} onChange={e => setForm({ ...form, nav: e.target.value })}/></label><label className="checkbox"><input type="checkbox" checked={specific} onChange={e => setSpecific(e.target.checked)}/> Select specific purchase lots</label>{specific ? <div className="lot-picker">{lots.length ? lots.map((l: Row) => <label key={l.origin}><span>{dateLabel(l.date)} · {exactNumber(l.units)} units · {money(l.cost)}</span><input aria-label={'Units from lot ' + l.date} type="number" min="0" max={l.units} step="any" value={allocations[l.origin] || ''} onChange={e => setAllocations({ ...allocations, [l.origin]: e.target.value })}/></label>) : <p>No purchase lots available for this fund/date.</p>}</div> : <p className="note">FIFO: the oldest purchase lots move first. Original dates and costs are retained.</p>}<label>Note<input value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} maxLength={500} placeholder="Optional reference"/></label>{error && <div className="form-error">{error}</div>}<button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Record transfer'}</button></form></Modal>}
    {addPerson && <Modal title="Add a person" close={() => setAddPerson(false)}><form className="form" onSubmit={async e => { e.preventDefault(); const fields = new FormData(e.currentTarget); try { await api('/people', { method: 'POST', body: JSON.stringify({ name: fields.get('name'), pan: fields.get('pan') }) }); setAddPerson(false); refresh(); notify('Person added. You can now transfer units to them.'); } catch (e: any) { setError(e.message); } }}><p className="note">People are also added automatically when their Excel files are imported.</p><label>Full name<input name="name" required/></label><label>PAN<input name="pan" required pattern="[A-Z]{5}[0-9]{4}[A-Z]" maxLength={10} style={{ textTransform: 'uppercase' }} onInput={e => { e.currentTarget.value = e.currentTarget.value.toUpperCase(); }}/></label>{error && <div className="form-error">{error}</div>}<button className="primary">Add person</button></form></Modal>}
  </>;
}

const tableColumns: Record<string, string[]> = {
  transactions: ['date', 'person_name', 'fund', 'type', 'treatment', 'units', 'statement_units', 'unit_source', 'nav', 'amount', 'source', 'row_number', 'excluded', 'transfer_id'],
  navs: ['date', 'fund', 'value', 'source', 'fetched_at'],
  indices: ['date', 'instrument', 'value', 'source', 'fetched_at'],
  valuations: ['date', 'fund', 'units', 'nav', 'nav_date', 'remaining_cost', 'market_value', 'nav_source'],
  benchmarks: ['date', 'index', 'type', 'tri', 'tri_date', 'cashflow', 'unit_change', 'units', 'value'],
  lots: ['person_name', 'fund', 'date', 'origin', 'units', 'cost', 'basis'],
  cashflows: ['date', 'amount'],
  gaps: ['date', 'name', 'kind', 'status'],
  status: ['name', 'kind', 'status', 'potential_gaps', 'gap_dates', 'first_date', 'last_date', 'observations', 'source', 'fetched_at'],
};
const labels: Row = { statement_units: 'Original statement units', unit_source: 'Calculation unit source', treatment: 'Calculation treatment', transfer_id: 'Linked transfer ID', potential_gaps: 'Dates to verify', gap_dates: 'Flagged dates', person_name: 'Person', fund: 'Fund', type: 'Type', units: 'Units', nav: 'NAV', amount: 'Amount', value: 'Published value', date: 'Date', source: 'Source', row_number: 'Excel row', excluded: 'Excluded / reason', fetched_at: 'Downloaded', instrument: 'Index', remaining_cost: 'Remaining cost', market_value: 'Market value', nav_date: 'NAV date', nav_source: 'Price source', tri: 'TRI', tri_date: 'TRI date', cashflow: 'Investor cash flow', unit_change: 'Unit change', origin: 'Original transaction ID', cost: 'Original cost', basis: 'Ownership basis', name: 'Fund / Index', kind: 'Type', status: 'Coverage', first_date: 'First date', last_date: 'Last date', observations: 'Observations', index: 'Index' };
function DuplicateReview({ groups, blockingIssues, status, setStatus, reload, notify, onToggle, onInspect }: Row) {
  const [error, setError] = useState('');
  const [saving, setSaving] = useState('');
  const counts = reviewCounts(groups, blockingIssues);
  const visible = filterReviewGroups(groups, status);
  const visibleBlocks = status === 'resolved' ? [] : blockingIssues;
  const choose = async (group: Row, ids: string[]) => {
    setSaving(group.id); setError('');
    try {
      const result = await api('/review/resolve', { method: 'POST', body: JSON.stringify({ group_id: group.id, keep_ids: ids }) });
      reload(); notify(result.excluded ? `${result.excluded} duplicate entries excluded. This choice persists on refresh.` : 'Entries confirmed as separate orders. Your choice is saved.');
    } catch (e: any) { setError(e.message); }
    finally { setSaving(''); }
  };
  return <>
    <div className="review-status-filter"><div className="segmented" aria-label="Review issue status">{[['unresolved','Unresolved'],['resolved','Resolved'],['all','All']].map(([id,label]) => <button key={id} className={status === id ? 'active' : ''} aria-pressed={status === id} onClick={() => setStatus(id)}>{label} ({counts[id]})</button>)}</div><span className="muted">CAS-confirmed entries are reconciled together.</span></div>
    <div className="notice"><Info size={16}/><span>Start with Unresolved to find entries needing attention. CAS distinguishes separate orders, unit gifts and folio consolidations. Other matching purchases or redemptions can be reviewed below. Changes that would break the unit balance are rejected without saving.</span></div>
    {error && <div className="notice warning">{error}</div>}
    {visibleBlocks.map((issue: Row) => <section className="panel review-blocker" key={issue.event_id}><div className="panel-header"><div><h2>{shortFund(issue.fund)}</h2><p>{dateLabel(issue.date)} · Unit balance blocks portfolio calculations</p></div><span className="badge amber-badge">Unresolved</span></div><div className="notice warning"><TriangleAlert size={16}/><span>{issue.message}. Required: {exactNumber(issue.requested)} units; available: {exactNumber(issue.available)} units. Review the purchase, redemption and transfer entries together.</span><button onClick={() => onInspect(issue.scheme)}>View transactions <ArrowRight size={14}/></button></div></section>)}
    {visible.map((group: Row) => <section className="panel" key={group.id}>
      <div className="panel-header"><div><h2>{shortFund(group.fund)}</h2><p>{group.person_name} · {group.type} · {group.same_date ? 'Matching rows on the same date' : 'Matching figures on different dates'}</p></div><span className={'badge ' + (group.unresolved ? 'amber-badge' : '')}>{group.unresolved ? 'Unresolved' : 'Resolved'}</span></div>
      {group.resolution_note && <div className="notice"><ShieldCheck size={15}/><span>{group.resolution_note}</span></div>}<div className="table-scroll"><table><thead><tr><th>Date</th><th>Units</th><th>NAV</th><th>Amount</th><th>Source / row</th><th>Status</th><th>Action</th></tr></thead><tbody>{group.records.map((r: Row) => <tr key={r.id} className={r.excluded ? 'excluded-row' : ''}><td>{dateLabel(r.date)}</td><td title={r.statement_units !== r.units ? `Original statement: ${exactNumber(r.statement_units)}` : undefined}>{exactNumber(r.units)}</td><td>{money(r.nav, 2)}</td><td>{money(r.amount)}</td><td title={r.source}>{r.source.split('/').pop()} · {r.row_number}</td><td title={r.excluded || ''}>{r.consolidation_role === 'original' ? 'Original purchase' : r.consolidation_id ? 'Internal folio movement' : r.excluded ? 'Excluded' : r.transfer_id ? 'Linked transfer' : 'Included'}</td><td>{group.cas_proof ? <span className="badge">CAS verified</span> : <><button className="text-button" disabled={saving === group.id || (!r.transfer_id && group.records.some((entry: Row) => entry.transfer_id))} onClick={() => choose(group, [r.id])}>Keep this entry</button>{r.excluded && <button className="text-button" style={{ marginLeft: 12 }} onClick={() => onToggle(r)}>Include again</button>}</>}</td></tr>)}</tbody></table></div>
      <div className="panel-header"><span className="muted">{group.cas_proof ? 'Verified against CAS. Original cash purchases and internal movements are treated separately.' : 'Only use Keep all for actual separate orders.'}</span>{!group.cas_proof && <button className="text-button" disabled={saving === group.id} onClick={() => choose(group, group.records.map((r: Row) => r.id))}>Keep all entries</button>}</div>
    </section>)}
    {visible.length === 0 && visibleBlocks.length === 0 && <Empty icon={<ShieldCheck size={30}/>} title={status === 'unresolved' ? 'No unresolved issues' : status === 'resolved' ? 'No resolved issues' : 'No review issues found'} text={status === 'unresolved' ? 'Use Resolved or All to see saved decisions and CAS reconciliations.' : 'This review respects your selected people, fund and date filters.'}/>}
  </>;
}

function DataDetails({ meta, data, query, fund, setFund, kind, setKind, revision, reload, notify }: Row) {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState('date');
  const [direction, setDirection] = useState('desc');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [csvOpen, setCsvOpen] = useState(false);
  const [mapping, setMapping] = useState<Row | null>(null);
  const [review, setReview] = useState<Row[]>([]);
  const [reviewIssues, setReviewIssues] = useState<Row[]>([]);
  const [reviewStatus, setReviewStatus] = useState('unresolved');
  const p = new URLSearchParams(query);
  if (from) p.set('start', from);
  if (to) p.set('end', to);
  p.set('search', search); p.set('sort', sort); p.set('direction', direction); p.set('offset', String(offset)); p.set('limit', '50');
  const sq = p.toString();
  useEffect(() => { setOffset(0); setSort(kind === 'status' ? 'name' : 'date'); setSearch(''); }, [kind, fund]);
  useEffect(() => {
    let active = true;
    setBusy(true);
    if (kind === 'review') setReview([]);
    api((kind === 'review' ? '/review?' : '/data/' + kind + '?') + sq)
      .then(r => { if (active) { if (kind === 'review') { setReview(r.groups); setReviewIssues(r.blocking_issues || []); } else { setRows(r.rows); setTotal(r.total); } setError(''); } })
      .catch(e => { if (active) setError(e.message); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [kind, sq, revision]);
  const currency = new Set(['amount', 'nav', 'remaining_cost', 'market_value', 'cost', 'basis', 'cashflow']);
  const cols = tableColumns[kind] || [];
  const action = async (tx: Row) => { try { if (tx.excluded) { await api('/transactions/' + tx.id + '/exclude', { method: 'DELETE' }); } else { await api('/transactions/' + tx.id + '/exclude', { method: 'PUT', body: JSON.stringify({ reason: 'Possible duplicate · manually excluded after review' }) }); } reload(); notify(tx.excluded ? 'Transaction included again.' : 'Transaction excluded. Source workbook unchanged.'); } catch (e: any) { setError(e.message); } };
  return <><div className="detail-tabs">{[['transactions', 'Transactions'], ['navs', 'Daily NAVs'], ['indices', 'Index levels'], ['valuations', 'Daily valuations'], ['benchmarks', 'Benchmark ledger'], ['lots', 'Purchase lots'], ['cashflows', 'XIRR cash flows'], ['status', 'Data status'], ['gaps', 'Price gaps'], ['review', 'Review issues']].map(([id, label]) => <button key={id} className={kind === id ? 'active' : ''} onClick={() => setKind(id)}>{label}</button>)}</div>
    {kind === 'review' ? <>
      <div className="data-tools"><select aria-label="Filter duplicate review by fund" value={fund} onChange={e => setFund(e.target.value)}><option value="">All funds</option>{meta.schemes.map((s: Row) => <option key={s.id} value={s.id}>{shortFund(s.name)}</option>)}</select><input aria-label="Review from date" type="date" value={from} onChange={e => setFrom(e.target.value)}/><span>—</span><input aria-label="Review to date" type="date" value={to} onChange={e => setTo(e.target.value)}/></div>
      {error && <div className="notice warning">{error}</div>}
      {busy ? <div className="notice"><LoaderCircle size={16} className="spin"/>Checking the selected history…</div> : !error && <DuplicateReview groups={review} blockingIssues={reviewIssues} status={reviewStatus} setStatus={setReviewStatus} reload={reload} notify={notify} onToggle={action} onInspect={(id: string) => { setFund(id); setKind('transactions'); }}/>}
    </> : <>
      <div className="data-tools"><div className="search-input"><Search size={15}/><input placeholder="Search these records…" aria-label="Search data records" value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }}/></div><select aria-label="Filter by fund" value={fund} onChange={e => { setFund(e.target.value); setOffset(0); }}><option value="">All funds</option>{meta.schemes.map((s: Row) => <option key={s.id} value={s.id}>{shortFund(s.name)}</option>)}</select><input aria-label="From date" type="date" value={from} onChange={e => { setFrom(e.target.value); setOffset(0); }}/><span>—</span><input aria-label="To date" type="date" value={to} onChange={e => { setTo(e.target.value); setOffset(0); }}/><a className="button secondary" href={'/api/export/' + kind + '.csv?' + sq}><Download size={14}/> CSV</a>{kind === 'indices' && <button className="secondary" onClick={() => setCsvOpen(true)}><Plus size={14}/> Import TRI CSV</button>}</div>
      {['status', 'gaps'].includes(kind) && <div className="notice"><Info size={16}/><span>Potential gaps are dates with a reference-market reading but no stored quote for this fund or index. Fund holidays and special exchange sessions can differ, so these are dates to verify, not confirmed download failures. Valuations use the last published NAV and retain its date. Refresh retries the flagged date ranges.</span>{kind === 'status' && <button onClick={() => setKind('gaps')}>View flagged dates <ArrowRight size={14}/></button>}</div>}
      {kind === 'valuations' && <div className="note inline-note">Valuations combine the selected people. Choose one person above for individual daily holdings. NAV date identifies carried-forward prices.</div>}
      {kind === 'status' && <><div className="status-summary"><div><Database size={18}/><strong>{meta.sources.reduce((a: number, s: Row) => a + s.records, 0)}</strong><span>source rows</span></div><div><FileSpreadsheet size={18}/><strong>{meta.sources.length}</strong><span>imported files</span></div><div><RefreshCw size={18}/><span>Last refresh</span><strong className="small-number">{dateLabel(meta.last_refresh)}</strong></div></div>{meta.refresh_errors?.length > 0 && <details className="error-log"><summary>{meta.refresh_errors.length} download issues from the last refresh</summary>{meta.refresh_errors.map((x: string, i: number) => <p key={i}>{x}</p>)}</details>}{meta.schemes.filter((s: Row) => !s.code).map((s: Row) => <div className="notice warning" key={s.id}><TriangleAlert size={15}/><span>Mapping needed: {shortFund(s.name)}</span><button onClick={() => setMapping(s)}>Choose AMFI scheme <ArrowRight size={13}/></button></div>)}</>}
      {error && <div className="notice warning">{error}</div>}<section className="panel data-panel"><div className="data-table-header"><span>{num(total, 0)} records</span>{busy && <LoaderCircle size={14} className="spin"/>}<span className="muted">Click a column to sort</span></div><div className="table-scroll"><table className="data-table"><thead><tr>{cols.map(k => <th key={k}><button onClick={() => { setSort(k); setDirection(sort === k && direction === 'desc' ? 'asc' : 'desc'); }}>{labels[k] || k}{sort === k && <ChevronDown size={11}/>}</button></th>)}{kind === 'transactions' && <th>Action</th>}</tr></thead><tbody>{rows.map((r, i) => <tr key={r.id || i} className={r.excluded ? 'excluded-row' : ''}>{cols.map(k => <td key={k} title={typeof r[k] === 'number' ? exactNumber(r[k]) : String(r[k] ?? '')}>{r[k] == null ? '—' : currency.has(k) ? money(r[k], 2) : typeof r[k] === 'number' ? exactNumber(r[k]) : ['date', 'nav_date', 'tri_date', 'first_date', 'last_date', 'fetched_at'].includes(k) ? dateLabel(r[k]) : String(r[k])}</td>)}{kind === 'transactions' && <td>{r.consolidation_id ? <span className="badge">CAS verified</span> : r.transfer_id ? <span className="badge">Linked transfer</span> : <button className="text-button" onClick={() => action(r)}>{r.excluded ? 'Include' : 'Exclude'}</button>}</td>}</tr>)}</tbody></table>{!busy && !rows.length && <Empty icon={<Database size={26}/>} title="No records yet" text={kind === 'navs' || kind === 'indices' ? 'Click Refresh data to download historical prices.' : 'Try another person, fund or date range.'}/>}</div><div className="pagination"><span>{total ? `${offset + 1}–${Math.min(offset + 50, total)} of ${num(total, 0)}` : '0 records'}</span><button aria-label="Previous page" className="icon-btn" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}><ChevronLeft size={17}/></button><button aria-label="Next page" className="icon-btn" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}><ChevronRight size={17}/></button></div></section>
      {kind === 'status' && <section className="panel"><div className="panel-header"><h2>Reconciliation notes</h2></div><div className="issue-list">{[...data.issues, ...(meta.provider_notes || []).map((n: Row) => n.message)].length ? [...data.issues, ...(meta.provider_notes || []).map((n: Row) => n.message)].map((s: string, i: number) => <p key={i}><Info size={14}/>{s}</p>) : <p>No reconciliation issues found.</p>}</div><div className="panel-header"><h2>Source files</h2></div><div className="source-list">{meta.sources.map((s: Row) => <div key={s.path}><FileSpreadsheet size={16}/><span>{s.path}</span><strong>{s.records} rows</strong>{s.error && <span className="negative">{s.error}</span>}</div>)}</div></section>}
    </>}
    {csvOpen && <Modal title="Import official TRI history" close={() => setCsvOpen(false)}><form className="form" onSubmit={async e => { e.preventDefault(); const form = new FormData(e.currentTarget); const file = form.get('file') as File; try { const r = await api('/index-csv', { method: 'POST', body: JSON.stringify({ index: form.get('index'), csv: await file.text() }) }); setCsvOpen(false); reload(); notify(`${r.imported} TRI observations imported.`); } catch (e: any) { setError(e.message); } }}><p className="note">Download Total Returns Index Values from <a target="_blank" rel="noreferrer" href="https://www.niftyindices.com/reports/historical-data">NSE Indices</a>. Use this when their automated endpoint is unavailable. A price-index Close column will not be accepted.</p><label>Index<select name="index">{(meta.indices || []).map((index: Row) => <option key={index.id} value={index.id}>{index.name}</option>)}</select></label><label>CSV file<input name="file" type="file" accept=".csv" required/></label><button className="primary">Import history</button></form></Modal>}
    {mapping && <Modal title="Confirm AMFI scheme" close={() => setMapping(null)}><form className="form" onSubmit={async e => { e.preventDefault(); const f = new FormData(e.currentTarget); try { const result = await api('/schemes/' + mapping.id, { method: 'PUT', body: JSON.stringify({ code: f.get('code') }) }); setMapping(null); reload(); notify('Mapped to ' + result.name + '. Refresh to backfill.'); } catch (e: any) { setError(e.message); } }}><p>{mapping.name}</p>{JSON.parse(mapping.candidates || '[]').map((c: Row) => <label className="checkbox" key={c.code}><input required type="radio" name="code" value={c.code}/><span>{c.name}<small>AMFI {c.code}</small></span></label>)}<button className="primary">Confirm scheme mapping</button></form></Modal>}
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
