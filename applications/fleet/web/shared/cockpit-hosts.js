/**
 * Preact leaf host wrappers around imperative Three.js C15 3D view, uPlot telemetry trace,
 * and declarative panel key/value lists (D-220, D-766).
 */
import { html, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { createRobotView } from "/console/assets/robot-3d.js";
import { createTelemetryTrace } from "/console/assets/cockpit-telemetry.js";

/** Mount createRobotView once per robot identity and push state updates without WebGL churn. */
export function Robot3dHost({
  kind,
  robotId,
  selection,
  profile,
  name,
  selected = true,
  pose,
  joints,
  skill,
  preset = "iso",
  className = "robot-panel-twin",
}) {
  const hostRef = useRef(null);
  const viewRef = useRef(null);
  const skipFirstStateRef = useRef(false);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host || !kind) return undefined;
    const instance = createRobotView(host, {
      kind,
      robotId,
      selection,
      profile,
      name,
      selected,
      pose,
      joints,
      skill,
      preset,
    });
    viewRef.current = instance;
    skipFirstStateRef.current = true;
    return () => {
      skipFirstStateRef.current = false;
      viewRef.current = null;
      instance.dispose?.();
      host.replaceChildren();
    };
  }, [kind, robotId, selection]);

  useLayoutEffect(() => {
    if (skipFirstStateRef.current) {
      skipFirstStateRef.current = false;
      return;
    }
    viewRef.current?.setState({ profile, name, selected, pose, joints, skill });
  }, [profile, name, selected, pose, joints, skill]);

  return html`<div class=${className} ref=${hostRef} />`;
}

/** Mount createTelemetryTrace once per panel session and keep uPlot size synced across drawer opens. */
export function TelemetryChartHost({
  active = false,
  id = null,
  title = "TELEMETRY",
  readout = "—",
  value = null,
  unit = "",
  minBound = null,
  maxBound = null,
  tone = "primary",
  sampleSeq = 0,
}) {
  const hostRef = useRef(null);
  const traceRef = useRef(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const trace = createTelemetryTrace();
    traceRef.current = trace;
    host.replaceChildren(trace.root);
    return () => {
      traceRef.current = null;
      trace.dispose();
      host.replaceChildren();
    };
  }, []);

  useLayoutEffect(() => {
    const trace = traceRef.current;
    if (!trace) return;
    if (!active || !id) {
      trace.clear();
      return;
    }
    trace.update({ id, title, readout, value, unit, minBound, maxBound, tone });
  }, [active, id, title, readout, value, unit, minBound, maxBound, tone, sampleSeq]);

  return html`<div ref=${hostRef} />`;
}

/** Render a two-column inspector definition list cleanly via Preact. */
export function PanelKvList({ rows = [], className = "robot-panel-kv" }) {
  return html`<dl class=${className}>
    ${rows.map(([label, value]) => html`<dt key=${label}>${label}</dt><dd>${value || EVIDENCE_LABEL.unavailable}</dd>`)}
  </dl>`;
}
