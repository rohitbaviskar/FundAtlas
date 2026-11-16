// Calendar dates, independent of the browser's timezone (including leap days).
export function periodRange(period, today) {
  if (period === 'All') return { start: '', end: '' };
  const years = { '1Y': 1, '3Y': 3, '5Y': 5 }[period];
  if (!years) throw Error('Unknown performance period');
  const [year, month, day] = today.split('-').map(Number);
  const lastDay = new Date(Date.UTC(year - years, month, 0)).getUTCDate();
  return { start: `${year - years}-${String(month).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`, end: '' };
}

export function rangeError({ start, end }, today) {
  const valid = day => /^\d{4}-\d{2}-\d{2}$/.test(day) && !Number.isNaN(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
  if (!valid(start) || !valid(end)) return 'Choose valid start and end dates.';
  if (start > end) return 'Start date must be on or before end date.';
  if (end > today) return 'End date cannot be in the future.';
  return '';
}

export function periodPoints(series, percent, start, openingAvailable = true) {
  if (!series.length) return { x: [], y: [] };
  // The opening is immediately before that day's transactions and returns.
  // Separate timestamps retain the first day's gain instead of overwriting it.
  return {
    x: [(start || series[0].date) + 'T00:00:00', ...series.map(p => p.date + 'T23:59:59')],
    y: [openingAvailable ? 0 : null, ...series.map(p => percent ? p.twr == null ? null : p.twr * 100 : p.gain ?? null)],
  };
}

export function investmentTraces(investment, percent, name, color, indexColors) {
  const line = (points, name, color, width) => ({ ...points, name, type: 'scatter', mode: 'lines', connectgaps: false, line: { color, width } });
  const start = investment.summary.start;
  return [
    line(periodPoints(investment.series, percent, start, investment.summary.opening_value != null), name, color, 2.6),
    ...investment.benchmarks.filter(b => !b.error).map(b => line(periodPoints(b.series, percent, start, b.opening_value != null), b.name, indexColors[b.id], 1.5)),
  ];
}
