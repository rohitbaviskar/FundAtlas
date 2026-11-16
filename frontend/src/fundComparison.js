export const fundColors = ['#17634b', '#2f7d9b', '#b66b91', '#7764b0', '#8a7b35', '#526b3d', '#a45c49', '#5a8295'];
export const indexColors = { 'NIFTY 50':'#4c8dce', 'NIFTY LARGEMIDCAP 250':'#9673c8', 'NIFTY 500':'#c69b3f', 'NIFTY MIDCAP 150':'#cf7360' };
const unique = items => [...new Set(items.filter(Boolean))];

export function readNavigation(hash) {
  const [path, search = ''] = hash.replace(/^#\/?/, '').split('?');
  if (path.startsWith('fund/')) {
    try { return { tab:'Fund details', funds:[decodeURIComponent(path.slice(5))] }; } catch { return { tab:'Funds', funds:[] }; }
  }
  if (path === 'compare') return { tab:'Fund details', funds:unique((new URLSearchParams(search).get('funds') || '').split(',')) };
  const tabs = { overview:'Overview', funds:'Funds', yearly:'Yearly', transfers:'Transfers', data:'Data details' };
  return { tab:tabs[path] || 'Overview', funds:[] };
}

export function navigationHash(route) {
  if (route.tab === 'Fund details') return route.funds.length === 1 ? '#/fund/' + encodeURIComponent(route.funds[0]) : '#/compare' + (route.funds.length ? '?funds=' + encodeURIComponent(unique(route.funds).join(',')) : '');
  return '#/' + ({Overview:'overview',Funds:'funds',Yearly:'yearly',Transfers:'transfers','Data details':'data'}[route.tab] || 'overview');
}

export function comparisonQuery(query, funds, indexes) {
  const p = new URLSearchParams(query);
  p.delete('fund');
  p.set('funds',unique(funds).join(','));
  p.set('indices',unique(indexes).join(','));
  return p.toString();
}

export function comparisonTraces(data, method, percent, fundIds) {
  const line = (x,y,name,color,width=1.7) => ({x,y,name,type:'scatter',mode:'lines',connectgaps:false,line:{color,width}});
  if (method === 'market') return (data.performance.series || []).map(r => line(r.series.map(p=>p.date),r.series.map(p=>percent ? p.return == null ? null : p.return*100 : p.value == null ? null : p.value - data.performance.initial_value),r.name,r.kind === 'index' ? indexColors[r.id] : fundColors[fundIds.indexOf(r.id)%fundColors.length],r.kind === 'fund' ? 2.3 : 1.5));
  return investmentTraces(data.investment, percent, fundIds.length===1 ? data.funds[0].name : 'Selected funds combined', fundColors[0], indexColors);
}
import { investmentTraces } from './performance.js';
