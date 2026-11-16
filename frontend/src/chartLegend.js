export const traceKey = trace => trace.uid || trace.name;
export const traceIsVisible = (trace, visibility = {}) => Object.hasOwn(visibility, traceKey(trace)) ? visibility[traceKey(trace)] : trace.visible !== false && trace.visible !== 'legendonly';

export function changeLegendVisibility(traces, visibility, key, isolate = false) {
  const entries = traces.filter(trace => trace.showlegend !== false && trace.visible !== false);
  const target = entries.find(trace => traceKey(trace) === key);
  if (!target) return visibility;
  if (!isolate) return { ...visibility, [key]: !traceIsVisible(target, visibility) };
  const onlyTarget = entries.every(trace => traceIsVisible(trace, visibility) === (traceKey(trace) === key));
  return { ...visibility, ...Object.fromEntries(entries.map(trace => [traceKey(trace), onlyTarget || traceKey(trace) === key])) };
}

export function applyLegendVisibility(traces, visibility) {
  return traces.map(trace => ({ ...trace, visible: trace.visible === false ? false : traceIsVisible(trace, visibility) ? true : 'legendonly' }));
}
