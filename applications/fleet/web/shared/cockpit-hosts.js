/**
 * Preact leaf host wrappers around imperative Three.js C15 3D view, uPlot telemetry trace,
 * and declarative panel key/value lists (D-220, D-766).
 */
import { html, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { createRobotView } from "/console/assets/robot-3d.js";
import { createTelemetryTrace } from "/console/assets/cockpit-telemetry.js";

/** Round mobile pose and arm joint angles so unchanged poll jitter never triggers redundant Three.js draws. */
function roundPose(pose) {
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return "";
  const yaw = Number.isFinite(pose.yaw) ? pose.yaw.toFixed(2) : "";
  return `${pose.x.toFixed(2)},${pose.y.toFixed(2)},${yaw}`;
}

function roundJoints(joints) {
  if (!joints || typeof joints !== "object") return "";
  return Object.keys(joints).sort()
    .map((key) => `${key}:${typeof joints[key] === "number" && Number.isFinite(joints[key]) ? joints[key].toFixed(3) : ""}`)
    .join(",");
}

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
  const lastStateSigRef = useRef("");

  const linkState = profile?.link?.state || "";
  const linkText = linkState && linkState !== "fresh" ? (profile?.link?.text || "") : "";
  const stateSig = JSON.stringify([
    name || profile?.name || "",
    Boolean(selected),
    linkState,
    linkText,
    roundPose(pose),
    roundJoints(joints),
    skill || "",
  ]);

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
    lastStateSigRef.current = stateSig;
    return () => {
      skipFirstStateRef.current = false;
      lastStateSigRef.current = "";
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
    if (lastStateSigRef.current === stateSig) return;
    lastStateSigRef.current = stateSig;
    viewRef.current?.setState({ profile, name, selected, pose, joints, skill });
  }, [stateSig]);

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
  battery = null,
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

  const batterySig = battery ? `${battery.percent}:${battery.charging}:${battery.online}` : "";
  useLayoutEffect(() => {
    const trace = traceRef.current;
    if (!trace) return;
    if (!active || !id) {
      trace.clear();
      return;
    }
    trace.update({ id, title, readout, value, unit, minBound, maxBound, tone, battery });
  }, [active, id, title, readout, value, unit, minBound, maxBound, tone, batterySig, sampleSeq]);

  return html`<div ref=${hostRef} />`;
}

/** Render a two-column inspector definition list cleanly via Preact. */
export function PanelKvList({ rows = [], className = "robot-panel-kv" }) {
  return html`<dl class=${className}>
    ${rows.map(([label, value]) => html`<dt key=${label}>${label}</dt><dd>${value || EVIDENCE_LABEL.unavailable}</dd>`)}
  </dl>`;
}
