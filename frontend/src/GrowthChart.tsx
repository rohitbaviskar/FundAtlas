import React, { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import Plotly from 'plotly.js-cartesian-dist-min';
import { RotateCcw } from 'lucide-react';
import { hoverReducer, money, num, readoutRows, tooltipPosition, chartPointKey } from './display.js';
import { traceKey, traceIsVisible, applyLegendVisibility, changeLegendVisibility } from './chartLegend.js';

type Row = Record<string, any>;
const HEIGHT = 370;

export default React.memo(function GrowthChart({ traces, percent, viewportKey, showLegend = true, externalLegend = false }: { traces: Row[], percent: boolean, viewportKey: string, showLegend?: boolean, externalLegend?: boolean }) {
  const plot = useRef<any>(null);
  const area = useRef<HTMLDivElement>(null);
  const tooltip = useRef<HTMLElement>(null);
  const attached = useRef(false);
  const pointer = useRef({ x: 0, y: 0 });
  const dragging = useRef(false);
  const inside = useRef(false);
  const [selection, dispatch] = useReducer(hoverReducer, { day: null, x: 0, y: 0 });
  const [size, setSize] = useState({ width: 330, height: 210 });
  const [visibility, setVisibility] = useState<Row>({});
  const [visibilityRevision, updateVisibility] = useReducer((n: number) => n + 1, 0);
  const legendEntries = traces.filter(trace => trace.showlegend !== false && trace.visible !== false);
  const legendKeys = JSON.stringify(legendEntries.map(traceKey));
  const displayTraces = useMemo(() => externalLegend ? applyLegendVisibility(traces, visibility) : traces, [traces, visibility, externalLegend]);
  const readout = useMemo(() => selection.day ? readoutRows(externalLegend ? displayTraces : plot.current?.data || traces, selection.day) : [], [traces, displayTraces, externalLegend, selection.day, visibilityRevision]);

  useEffect(() => {
    const keys = new Set(JSON.parse(legendKeys));
    setVisibility(previous => Object.keys(previous).some(key => !keys.has(key)) ? Object.fromEntries(Object.entries(previous).filter(([key]) => keys.has(key))) : previous);
  }, [legendKeys]);

  useEffect(() => { dispatch({ type: 'reset' }); }, [viewportKey]);
  useLayoutEffect(() => {
    if (tooltip.current) {
      const bounds = tooltip.current.getBoundingClientRect();
      setSize(old => old.width === bounds.width && old.height === bounds.height ? old : { width: bounds.width, height: bounds.height });
    }
  }, [selection.day, percent, readout.length]);

  useEffect(() => {
    const element = plot.current;
    const container = area.current;
    if (!element || !container) return;
    let frame = 0;
    // Observe width only. Never derive the plot height from its own temporary
    // dimensions or a hidden panel during Plotly's resize cycle.
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const width = Math.floor(container.clientWidth);
        if (width > 0 && element._fullLayout && Math.abs(element._fullLayout.width - width) >= 1) {
          Plotly.relayout(element, { width, height: HEIGHT, autosize: false });
        }
      });
    });
    observer.observe(container);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); attached.current = false; Plotly.purge(element); };
  }, []);

  useEffect(() => {
    const element = plot.current;
    if (!element) return;
    let active = true;
    const rendered = displayTraces.map(trace => ({ ...trace, hoverinfo: 'none', hovertemplate: null }));
    Plotly.react(element, rendered, {
      autosize: false, width: area.current?.clientWidth || undefined, height: HEIGHT, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { family: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif', size: 11, color: '#758079' },
      margin: { l: 85, r: 22, t: 35, b: showLegend ? 65 : 40 }, showlegend: showLegend,
      legend: { orientation: 'h', x: 0, y: -0.19, font: { size: 10 } },
      xaxis: { type: 'date', gridcolor: '#f0f2ef', zeroline: false, nticks: 8, hoverformat: '%d %b %Y', uirevision: viewportKey },
      yaxis: { gridcolor: '#edf0ed', zeroline: false, tickformat: percent ? '.2f' : '.3~s', tickprefix: percent ? '' : '₹', ticksuffix: percent ? '%' : '', automargin: true },
      hovermode: 'x', hoverdistance: -1, dragmode: 'zoom', uirevision: viewportKey,
    }, {
      responsive: false, displayModeBar: true, displaylogo: false, scrollZoom: true, doubleClick: 'reset',
      modeBarButtonsToRemove: ['select2d', 'lasso2d', 'toImage', 'toggleSpikelines', 'hoverClosestCartesian', 'hoverCompareCartesian'],
    }).then(() => {
      if (!active || attached.current) return;
      element.on('plotly_hover', (event: Row) => {
        if (inside.current && !dragging.current && event.points?.length) dispatch({ type: 'hover', day: chartPointKey(event.points[0].x), pointer: pointer.current });
      });
      // A transient Plotly unhover must not dismiss values under a stationary
      // pointer. Pointer exit clears them; no pinning or manual close action.
      element.on('plotly_relayouting', () => dispatch({ type: 'close' }));
      element.on('plotly_restyle', () => updateVisibility());
      attached.current = true;
    });
    return () => { active = false; };
  }, [displayTraces, percent, viewportKey, showLegend]);

  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (tooltip.current?.contains(event.target as Node)) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    pointer.current = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    const box = plot.current?._fullLayout?._size;
    inside.current = Boolean(!event.buttons && box && pointer.current.x >= box.l && pointer.current.x <= box.l + box.w && pointer.current.y >= box.t && pointer.current.y <= box.t + box.h);
    if (!inside.current) {
      dispatch({ type: 'leave' });
    } else dispatch({ type: 'move', pointer: pointer.current });
  };
  const position = tooltipPosition(selection, { width: area.current?.clientWidth || 330, height: HEIGHT }, size);
  const reset = () => {
    dispatch({ type: 'reset' });
    if (plot.current?._fullLayout) Plotly.relayout(plot.current, { 'xaxis.autorange': true, 'yaxis.autorange': true, height: HEIGHT });
  };
  return <div className="growth-chart">
    <div ref={area} className="growth-plot-area" onPointerMove={move} onPointerLeave={() => { inside.current = false; dragging.current = false; dispatch({ type: 'leave' }); }} onPointerDown={event => { if (!tooltip.current?.contains(event.target as Node)) { dragging.current = true; dispatch({ type: 'close' }); } }} onPointerUp={() => { dragging.current = false; }}>
      <div ref={plot} className="plot growth-plot" style={{ height: HEIGHT, minHeight: HEIGHT }} aria-label="Portfolio growth. Hover for values; drag or scroll to zoom."/>
      {selection.day && readout.length > 0 && <aside ref={tooltip} className="chart-readout" role="tooltip" style={position}>
        <div className="readout-heading"><strong>{new Date(selection.day.slice(0, 10) + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}{selection.day.endsWith('T00:00:00') && traces.some(t => t.x?.some((x: string) => String(x).endsWith('T23:59:59'))) ? ' · Opening' : ''}</strong></div>
        <dl>{readout.map((row: Row) => <div key={row.name}><dt><i style={{ background: row.color }}/>{row.name}</dt><dd>{row.value == null ? '—' : percent ? num(row.value) + '%' : money(row.value)}</dd></div>)}</dl>
      </aside>}
    </div>
    {externalLegend && <div className="fund-comparison-legend" role="group" aria-label="Chart legend. Click to show or hide a series; double-click to isolate it.">{legendEntries.map(trace => {
      const key = traceKey(trace);
      const visible = traceIsVisible(trace, visibility);
      return <button type="button" key={key} className={visible ? 'chart-legend-item' : 'chart-legend-item is-hidden'} aria-pressed={visible} aria-label={(visible ? 'Hide ' : 'Show ') + trace.name} title="Click to show or hide. Double-click to show only this series; double-click again to show all." onClick={() => setVisibility(previous => changeLegendVisibility(traces, previous, key))} onDoubleClick={() => setVisibility(previous => changeLegendVisibility(traces, previous, key, true))}><i style={{ background: trace.line?.color || '#17634b' }}/>{trace.name}</button>;
    })}</div>}
    <div className="growth-chart-tools"><span>Drag or scroll to zoom. Calculations stay fixed to your selected period.</span><button className="text-button" onClick={reset}><RotateCcw size={13}/> Reset zoom</button></div>
  </div>;
});
