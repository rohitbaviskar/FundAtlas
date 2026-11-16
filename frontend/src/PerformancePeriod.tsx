import React, { useEffect, useState } from 'react';
import { periodRange, rangeError } from './performance.js';

type Range = { start: string, end: string };
export default function PerformancePeriod({ today, range, onChange }: { today: string, range: Range, onChange: (range: Range) => void }) {
  const [period, setPeriod] = useState('All');
  const [draft, setDraft] = useState<Range>({ start: '', end: '' });
  const [error, setError] = useState('');
  useEffect(() => { if (period !== 'Custom') onChange(periodRange(period, today)); }, [period, today, onChange]);
  const choose = (next: string) => {
    if (next === 'Custom') setDraft({ start: range.start || periodRange('1Y', today).start, end: range.end || today });
    setError('');
    setPeriod(next);
  };
  const apply = (event: React.FormEvent) => {
    event.preventDefault();
    const message = rangeError(draft, today);
    setError(message);
    if (!message) onChange({ ...draft });
  };
  return <div className="performance-period">
    <select aria-label="Performance period" value={period} onChange={e => choose(e.target.value)}><option value="All">Since inception</option><option value="1Y">Last 1 year</option><option value="3Y">Last 3 years</option><option value="5Y">Last 5 years</option><option value="Custom">Custom dates</option></select>
    {period === 'Custom' && <form className="custom-period" onSubmit={apply}>
      <label>From<input type="date" aria-label="Period start date" required max={today} value={draft.start} onChange={e => { setError(''); setDraft({ ...draft, start: e.target.value }); }}/></label>
      <label>To<input type="date" aria-label="Period end date" required min={draft.start || undefined} max={today} value={draft.end} onChange={e => { setError(''); setDraft({ ...draft, end: e.target.value }); }}/></label>
      <button type="submit" className="secondary" disabled={draft.start === range.start && draft.end === range.end}>Apply dates</button>
      {error && <span className="period-error" role="alert">{error}</span>}
    </form>}
  </div>;
}
