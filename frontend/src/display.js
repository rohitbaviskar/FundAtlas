// Formatting never changes the values used in portfolio calculations.
const digits = value => Math.max(0, Math.min(2, value));
export const money = (value, places = 2) => value == null ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: digits(places) }).format(value);
export const num = (value, places = 2) => value == null ? '—' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: digits(places) }).format(value);
export const pct = value => value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;

// Group digits without imposing a decimal limit on quantities or index levels.
export function exactNumber(value) {
  if (value == null) return '—';
  const text = String(value);
  if (!/^-?\d+(\.\d+)?(e[+-]?\d+)?$/i.test(text)) return text;
  const negative = text.startsWith('-');
  const [coefficient, exponent = '0'] = text.replace(/^-/, '').toLowerCase().split('e');
  const [whole, fraction = ''] = coefficient.split('.');
  const digits = whole + fraction;
  const point = whole.length + Number(exponent);
  const expanded = point <= 0 ? '0.' + '0'.repeat(-point) + digits : point >= digits.length ? digits + '0'.repeat(point - digits.length) : digits.slice(0, point) + '.' + digits.slice(point);
  const [integer, decimals] = expanded.split('.');
  return (negative ? '-' : '') + new Intl.NumberFormat('en-IN').format(BigInt(integer)) + (decimals ? '.' + decimals : '');
}

export function tooltipPosition(pointer, bounds, size) {
  const gap = 14, edge = 8;
  const x = pointer.x + gap + size.width <= bounds.width - edge ? pointer.x + gap : pointer.x - size.width - gap;
  const y = pointer.y + gap + size.height <= bounds.height - edge ? pointer.y + gap : pointer.y - size.height - gap;
  return { left: Math.max(edge, Math.min(x, bounds.width - size.width - edge)), top: Math.max(edge, Math.min(y, bounds.height - size.height - edge)) };
}

export const chartPointKey = value => {
  if (value instanceof Date) return value.toISOString().slice(0, 19);
  const text = String(value).replace(' ', 'T');
  return (text.length === 10 ? text + 'T00:00:00' : text).slice(0, 19);
};

export function readoutRows(traces, point) {
  const key = chartPointKey(point);
  return traces.filter(trace => trace.visible !== 'legendonly' && trace.visible !== false).map(trace => {
    // Every trace has its own dates. Never pair different dates by array index,
    // and never turn a missing valuation into zero or an interpolated quote.
    let lo = 0, hi = trace.x.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (chartPointKey(trace.x[mid]) < key) lo = mid + 1;
      else hi = mid;
    }
    const value = chartPointKey(trace.x[lo]) === key ? trace.y[lo] : null;
    return { name: trace.name, value: typeof value === 'number' && Number.isFinite(value) ? value : null, color: trace.line?.color || '#17634b' };
  });
}

export function hoverReducer(state, action) {
  if (['close', 'reset', 'leave'].includes(action.type)) return { day: null, x: 0, y: 0 };
  if (action.type === 'hover') return { ...state, day: action.day, ...action.pointer };
  if (action.type === 'move' && state.day) return { ...state, ...action.pointer };
  return state;
}

export function reviewCounts(groups, blockingIssues = []) {
  const unresolved = groups.filter(group => group.unresolved).length + blockingIssues.length;
  const resolved = groups.filter(group => !group.unresolved).length;
  return { unresolved, resolved, all: unresolved + resolved };
}

export function filterReviewGroups(groups, status) {
  return groups.filter(group => status === 'all' || (status === 'unresolved' ? group.unresolved : !group.unresolved));
}
