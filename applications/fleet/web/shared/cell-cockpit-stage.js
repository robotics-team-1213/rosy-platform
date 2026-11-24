// D-960 / D-136 — ARM-CELL Primary Stage & shared Workcell Observation Normalizer.
// Fetches read-only /api/fleet/workcell-observations on both R and ARM-CELL and renders the primary
// workcell camera wall + 3-arm EICAS strip when this control unit owns arms without drive (!owns("drive") && owns("arms")).
// DOM construction is declarative htm/preact; only the host <section> is created imperatively.
import { html, render as renderDom, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { patchHidden } from "/common/control-dom.js";
import { createMotorHealthState, renderMotorHealthSummary } from "/common/motor-health.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { owns } from "/console/assets/unit-scope.js";

const JOINT_ORDER = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"];
const JOINT_SHORT = ["J1", "J2", "J3", "J4", "J5", "G"];
const RAD_TO_DEG = 180 / Math.PI;
const CAMERA_RANK = { overhead: 0, side: 1, wrist: 2 };
const VISION_REFRESH_MS = 15000;

export function canonicalArmId(raw) {
  return String(raw || "").trim().toLowerCase().replace(/^omx_/, "").replace(/_follower$/, "");
}

function readArmMetrics(arm, fresh, positions) {
  const health = arm?.motor_health?.schema_version === "rosy.motor-health.v1" ? arm.motor_health : null;
  const motors = Array.isArray(health?.motors) ? health.motors : [];
  let maxTempC = null;
  let maxPwmPct = null;
  let maxCurrentMa = null;
  let hwFaultMotors = 0;
  let warnMotors = 0;
  for (const m of motors) {
    if (Number.isInteger(m?.hardware_error) && m.hardware_error > 0) hwFaultMotors += 1;
    if (Array.isArray(m?.warnings) && m.warnings.length > 0) warnMotors += 1;
    if (typeof m?.temperature_c === "number" && Number.isFinite(m.temperature_c)) {
      maxTempC = maxTempC === null ? m.temperature_c : Math.max(maxTempC, m.temperature_c);
    }
    const util = typeof m?.pwm_utilization === "number" && Number.isFinite(m.pwm_utilization)
      ? Math.round(m.pwm_utilization * 100)
      : (typeof m?.pwm === "number" && Number.isFinite(m.pwm) && typeof m?.pwm_limit === "number" && m.pwm_limit > 0
          ? Math.round((Math.abs(m.pwm) / m.pwm_limit) * 100)
          : null);
    if (util !== null) maxPwmPct = maxPwmPct === null ? util : Math.max(maxPwmPct, util);
    if (typeof m?.current_ma === "number" && Number.isFinite(m.current_ma)) {
      const ma = Math.round(Math.abs(m.current_ma));
      maxCurrentMa = maxCurrentMa === null ? ma : Math.max(maxCurrentMa, ma);
    }
  }
  const jointsDeg = positions
    ? JOINT_ORDER.map((k) => (typeof positions[k] === "number" && Number.isFinite(positions[k]) ? positions[k] * RAD_TO_DEG : null))
    : null;
  const jointsText = jointsDeg && jointsDeg.some((v) => v !== null)
    ? jointsDeg.map((deg, idx) => (deg === null ? `${JOINT_SHORT[idx]}:—` : `${JOINT_SHORT[idx]}:${deg.toFixed(1)}°`)).join(" ")
    : null;
  return { health, motors, maxTempC, maxPwmPct, maxCurrentMa, hwFaultMotors, warnMotors, jointsDeg, jointsText, fresh };
}

export function normalizeWorkcellObservations(payload, receivedAtMs = Date.now()) {
  const workcells = Array.isArray(payload?.workcells) ? payload.workcells : [];
  const arms = [];
  const cameras = [];

  for (const cell of workcells) {
    for (const arm of Array.isArray(cell?.arms) ? cell.arms : []) {
      const id = canonicalArmId(arm?.arm_id || arm?.source_id);
      if (!id) continue;
      const rawPos = arm?.positions && typeof arm.positions === "object" ? arm.positions : null;
      const cleanEntries = rawPos
        ? Object.entries(rawPos).filter(([, v]) => typeof v === "number" && Number.isFinite(v))
        : [];
      const fresh = Boolean(arm?.fresh) && cleanEntries.length > 0;
      const positions = fresh ? Object.fromEntries(cleanEntries) : null;
      const metrics = readArmMetrics(arm, fresh, positions);
      const incidents = Array.isArray(arm?.incidents) ? arm.incidents : [];
      const openIncidents = incidents.filter((inc) => inc?.state !== "cleared");
      const heldIncidents = openIncidents.filter((inc) => inc?.decision?.hold !== false);
      const ageS = typeof arm?.source_age_s === "number" && Number.isFinite(arm.source_age_s)
        ? arm.source_age_s
        : (typeof arm?.receipt_age_s === "number" && Number.isFinite(arm.receipt_age_s) ? arm.receipt_age_s : null);
      arms.push({
        id,
        sourceId: String(arm?.source_id || id),
        armId: String(arm?.arm_id || id),
        label: String(arm?.label || id),
        fresh,
        positions,
        jointsDeg: metrics.jointsDeg,
        jointsText: metrics.jointsText,
        motorHealth: metrics.health,
        maxTempC: metrics.maxTempC,
        maxPwmPct: metrics.maxPwmPct,
        maxCurrentMa: metrics.maxCurrentMa,
        hwFaultMotors: metrics.hwFaultMotors,
        warnMotors: metrics.warnMotors,
        incidents,
        openIncidents,
        heldIncidents,
        held: heldIncidents.length > 0,
        faults: Array.isArray(arm?.faults) ? arm.faults : [],
        ageS,
        sequence: typeof arm?.sequence === "number" ? arm.sequence : 0,
      });
    }
    for (const cam of Array.isArray(cell?.cameras) ? cell.cameras : []) {
      if (!cam?.source_id) continue;
      cameras.push({
        source_id: String(cam.source_id),
        label: String(cam.label || cam.source_id),
        role: String(cam.role || "wrist"),
        stream: cam.stream ? String(cam.stream) : "color",
        arm_id: cam.arm_id ? canonicalArmId(cam.arm_id) : null,
        fresh: Boolean(cam.fresh),
        frame_seq: typeof cam.frame_seq === "number" ? cam.frame_seq : null,
        age_s: typeof cam.age_s === "number" && Number.isFinite(cam.age_s) ? cam.age_s : null,
      });
    }
  }

  cameras.sort((a, b) => {
    const ra = (CAMERA_RANK[a.role] ?? 2) + (a.stream === "depth" ? 0.5 : 0);
    const rb = (CAMERA_RANK[b.role] ?? 2) + (b.stream === "depth" ? 0.5 : 0);
    return ra - rb;
  });

  const summary = {
    armsTotal: arms.length,
    armsFresh: arms.filter((a) => a.fresh).length,
    camsTotal: cameras.length,
    camsLive: cameras.filter((c) => c.fresh).length,
    heldCount: arms.filter((a) => a.held).length,
    openIncidentCount: arms.reduce((n, a) => n + a.openIncidents.length, 0),
    faultArmCount: arms.filter((a) => a.hwFaultMotors > 0 || a.motorHealth?.status === "fault").length,
    warnArmCount: arms.filter((a) => a.warnMotors > 0).length,
    receivedAtMs,
  };
  return { receivedAtMs, arms, cameras, summary };
}

/** One camera tile. frames.bind runs once per camera identity; the feed keeps painting between polls. */
function CameraTile({ cam, frames, liveOn }) {
  const imgRef = useRef(null);
  const statusRef = useRef(null);
  const standbyRef = useRef(null);
  useLayoutEffect(() => {
    frames.bind(imgRef.current, { source: cam.source_id }, statusRef.current, cam.label);
  }, [cam.source_id, cam.label, frames]);
  // No dep list: sync the standby text after every poll render like the pre-preact version did.
  useLayoutEffect(() => {
    const img = imgRef.current;
    const standby = standbyRef.current;
    if (!img || !standby) return;
    if (!liveOn) {
      standby.hidden = false;
      standby.textContent = "영상 일시정지";
    } else if (!img.getAttribute("src")) {
      standby.hidden = false;
      standby.textContent = img.dataset.frameStateText || "첫 프레임 대기 — 스트림 연결 확인";
    }
  });
  const toggleZoom = () => imgRef.current?.classList.toggle("focused");
  const onKeyDown = (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      toggleZoom();
    } else if (ev.key === "Escape") {
      imgRef.current?.classList.remove("focused");
    }
  };
  return html`<article class="cell-stage-cam" data-camera-source=${cam.source_id} tabIndex=${0} onKeyDown=${onKeyDown}>
    <div class="cell-stage-cam-head">
      <strong>${cam.stream === "depth" ? `${cam.label} · 깊이` : cam.label}</strong>
      <small ref=${statusRef} class="omx-inspector-cam-badge">영상 확인 중</small>
    </div>
    <div class="omx-inspector-cam-frame">
      <img ref=${imgRef} class="omx-inspector-main-cam omx-inspector-cam" alt=${`${cam.label} 실시간 카메라`} loading="lazy"
        onClick=${toggleZoom} onLoad=${() => { if (standbyRef.current) standbyRef.current.hidden = true; }} />
      <span ref=${standbyRef} class="omx-inspector-cam-standby" role="status">영상 대기</span>
    </div>
  </article>`;
}

/** One arm card. mhState is created once per arm id by the stage and accepted again on every render. */
function ArmCard({ arm, selected, mhState, selection, receivedAtMs }) {
  const mhRef = useRef(null);
  useLayoutEffect(() => {
    mhState.accept(arm.motorHealth, { receivedAtMs });
    renderMotorHealthSummary(mhRef.current, mhState.read(Date.now()));
  });
  const badge = arm.held ? { status: "crit", text: `보류 ${arm.heldIncidents.length}건` }
    : arm.openIncidents.length ? { status: "warn", text: `사건 ${arm.openIncidents.length}건` }
    : arm.fresh ? { status: "active", text: "실시간" }
    : { status: "warn", text: "대기 · 만료" };
  return html`<button type="button" class=${`cell-stage-arm${selected ? " selected" : ""}`} data-arm-id=${arm.id}
    onClick=${() => selection?.set?.(arm.id, { source: "roster" })}>
    <div class="cell-stage-arm-head">
      <strong>${arm.label}</strong>
      <ui-tag status=${badge.status}>${badge.text}</ui-tag>
    </div>
    <p ref=${mhRef} />
    ${arm.jointsDeg && arm.jointsDeg.some((v) => v !== null)
      ? html`<dl class="cell-stage-joints-grid">
          ${JOINT_SHORT.map((name, idx) => {
            const deg = arm.jointsDeg[idx];
            return html`<div class="cell-stage-joint" key=${name}><dt>${name}</dt><dd>${deg === null ? "—" : `${deg.toFixed(1)}°`}</dd></div>`;
          })}
        </dl>`
      : html`<p class="cell-stage-joints">엔코더 최신 피드백 없음</p>`}
  </button>`;
}

function obsSignature(obs) {
  if (!obs) return "";
  return JSON.stringify({
    arms: (obs.arms || []).map((a) => ({
      id: a.id,
      label: a.label,
      fresh: a.fresh,
      held: a.heldIncidents.length,
      open: a.openIncidents.length,
      faults: a.faults,
      hw: a.hwFaultMotors,
      warn: a.warnMotors,
      temp: a.maxTempC,
      pwm: a.maxPwmPct,
      ma: a.maxCurrentMa,
      mhStatus: a.motorHealth?.status || "",
      mhEv: a.motorHealth?.evidence || "",
      joints: a.jointsDeg ? a.jointsDeg.map((d) => (d === null ? null : d.toFixed(1))) : null,
    })),
    cams: (obs.cameras || []).map((c) => [c.source_id, c.label, c.role, c.stream, c.arm_id, c.fresh]),
  });
}

export function createCellCockpitStage({ scope, call, view, auth, selection, onChanged, onVisionSample }) {
  const gate = createPollGate({ slowCodes: { WORKCELL_OBSERVATIONS_UNAVAILABLE: 30000 } });
  const frames = createCellFrameFeed({ call, scope, intervalMs: 2000 });
  const section = document.createElement("section");
  section.className = "panel cell-cockpit-stage";
  section.id = "cell-cockpit-stage";
  section.setAttribute("aria-labelledby", "cell-stage-heading");
  section.hidden = true;

  // One motor-health state per arm id, kept across polls so evidence age is continuous.
  const mhStates = new Map();
  const mhStateFor = (id) => {
    let state = mhStates.get(id);
    if (!state) mhStates.set(id, (state = createMotorHealthState()));
    return state;
  };

  let areaHidden = false;
  let inFlight = false;
  let liveOn = true;
  let controlUnitFetched = false;
  let visionCheckedAt = 0;
  let lastStageSig = "";
  let lastObsSig = "";
  let notifiedOnce = false;

  const isStageActive = () => !areaHidden && !owns("drive") && owns("arms");

  const syncFeedState = () => {
    frames.setRunning(liveOn && isStageActive() && !auth.locked && !document.hidden);
  };

  const onToggleLive = () => {
    liveOn = !liveOn;
    syncFeedState();
    render();
  };

  const offSel = selection?.subscribe?.(() => render());
  scope.onDispose?.(offSel);
  scope.onDispose?.(() => {
    lastStageSig = "";
    lastObsSig = "";
    renderDom(null, section);
  });
  scope.listen(document, "visibilitychange", syncFeedState);

  function render() {
    const show = isStageActive();
    patchHidden(section, !show);
    syncFeedState();
    if (!show) {
      lastStageSig = "";
      return;
    }
    const obs = view.workcellObs;
    const cu = view.controlUnit;
    const sum = obs?.summary;
    const unitId = cu?.unit_id || "ARM-CELL";
    const parentText = cu?.parent ? `상위 관제: ${cu.parent}` : "독립 셀 관제";
    const revText = cu?.config_revision ? `구성 ${cu.config_revision}` : "";
    const statText = sum ? `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간 · 카메라 ${sum.camsTotal}대` : "관측 대기";
    let liveStatus = "neutral";
    let liveText = "수신 대기";
    if (sum?.armsTotal) {
      if (sum.heldCount > 0 || sum.faultArmCount > 0) {
        liveStatus = "crit";
        liveText = sum.heldCount ? `보류 ${sum.heldCount}건` : "고장 확인";
      } else if (sum.armsFresh > 0) {
        liveStatus = "active";
        liveText = `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간`;
      } else {
        liveStatus = "warn";
        liveText = "피드백 대기";
      }
    }
    const cams = obs?.cameras || [];
    const arms = obs?.arms || [];
    const selectedId = selection?.get?.() ?? null;
    const stageSig = JSON.stringify([
      unitId, parentText, revText, statText, liveStatus, liveText,
      view.fleet?.name === "샘플 현장", liveOn, selectedId, Boolean(auth.locked), obsSignature(obs),
    ]);
    if (stageSig === lastStageSig) return;
    lastStageSig = stageSig;
    renderDom(html`
      <div class="cell-stage-head">
        <div>
          <h2 id="cell-stage-heading">${unitId} 작업 셀 관제</h2>
          <p class="cell-stage-meta">${[parentText, revText, statText].filter(Boolean).join(" · ")}</p>
        </div>
        <div class="cell-stage-actions">
          <ui-tag class="cell-stage-sample-tag" status="warn" hidden=${view.fleet?.name !== "샘플 현장"}>샘플 데이터</ui-tag>
          <ui-tag status=${liveStatus}>${liveText}</ui-tag>
          <${UiButton} kind="segment" type="button" data-work-read="" aria-pressed=${liveOn ? "true" : "false"} onClick=${onToggleLive}
          >${liveOn ? "영상 자동갱신 ON" : "영상 일시정지"}</${UiButton}>
          <a class="ui-action-link" data-kind="quiet" href="/console/cell">셀 작업 화면</a>
        </div>
      </div>
      <div class="cell-stage-cameras" role="region" aria-label="셀 실시간 카메라">
        ${cams.length
          ? cams.map((cam) => html`<${CameraTile} key=${cam.source_id} cam=${cam} frames=${frames} liveOn=${liveOn} />`)
          : html`<p class="hint">등록된 셀 카메라가 없습니다.</p>`}
      </div>
      <div class="cell-stage-arms" role="region" aria-label="셀 팔 상태 요약">
        ${arms.length
          ? arms.map((arm) => html`<${ArmCard} key=${arm.id} arm=${arm} selected=${selectedId === arm.id} mhState=${mhStateFor(arm.id)} selection=${selection} receivedAtMs=${obs.receivedAtMs} />`)
          : html`<p class="hint">${auth.locked ? "접속 후 팔 관측을 표시합니다." : "관측 중인 팔이 없습니다."}</p>`}
      </div>
    `, section);
  }

  async function refreshControlUnit(signal) {
    if (controlUnitFetched || owns("drive")) return;
    try {
      view.controlUnit = await call("/api/fleet/control-unit", { signal });
      controlUnitFetched = true;
    } catch (err) {
      if (err?.name !== "AbortError") view.controlUnit = view.controlUnit || null;
    }
  }

  async function refreshVisionSummary(signal) {
    if (owns("drive") || !owns("arms")) return;
    const now = Date.now();
    if (now - visionCheckedAt < VISION_REFRESH_MS) return;
    visionCheckedAt = now;
    try {
      const res = await call("/api/fleet/vision/sources", { signal });
      const sources = Array.isArray(res?.sources) ? res.sources : [];
      onVisionSample?.({ finished: true, status: 200, names: sources });
    } catch (err) {
      if (err?.name === "AbortError") return;
      onVisionSample?.(typeof err?.status === "number"
        ? { finished: true, status: err.status }
        : { finished: false });
    }
  }

  async function refresh() {
    if (auth.locked || inFlight || !gate.due() || !owns("arms")) return;
    const life = scope.capture();
    inFlight = true;
    try {
      const [payload] = await Promise.all([
        call("/api/fleet/workcell-observations", { signal: life.signal }),
        refreshControlUnit(life.signal),
        isStageActive() ? refreshVisionSummary(life.signal) : Promise.resolve(),
      ]);
      life.check();
      gate.ok();
      const nextObs = normalizeWorkcellObservations(payload, Date.now());
      view.workcellObs = nextObs;
      for (const arm of nextObs.arms) mhStateFor(arm.id).accept(arm.motorHealth, { receivedAtMs: nextObs.receivedAtMs });
      const nextSig = obsSignature(nextObs);
      if (!notifiedOnce || nextSig !== lastObsSig) {
        lastObsSig = nextSig;
        notifiedOnce = true;
        render();
        onChanged?.();
      }
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (typeof err?.status === "number") gate.fail(err.status, err.code);
      if (err?.status === 503 || err?.status === 404) {
        lastObsSig = "";
        notifiedOnce = false;
        view.workcellObs = null;
        render();
      }
    } finally {
      inFlight = false;
    }
  }

  return {
    element: section,
    refresh,
    render,
    setAreaHidden(nextHidden) {
      areaHidden = Boolean(nextHidden);
      render();
    },
    pause() {
      controlUnitFetched = false;
      lastObsSig = "";
      notifiedOnce = false;
      gate.reset();
      syncFeedState();
    },
  };
}
