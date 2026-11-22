// D-960 / D-136 — ARM-CELL Primary Stage & shared Workcell Observation Normalizer.
// Fetches read-only /api/fleet/workcell-observations on both R and ARM-CELL and renders the primary
// workcell camera wall + 3-arm EICAS strip when this control unit owns arms without drive (!owns("drive") && owns("arms")).
import { node } from "/common/control-dom.js";
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

export function createCellCockpitStage({ scope, call, view, auth, selection, onChanged, onVisionSample }) {
  const gate = createPollGate({ slowCodes: { WORKCELL_OBSERVATIONS_UNAVAILABLE: 30000 } });
  const frames = createCellFrameFeed({ call, scope, intervalMs: 2000 });
  const section = document.createElement("section");
  section.className = "panel cell-cockpit-stage";
  section.id = "cell-cockpit-stage";
  section.setAttribute("aria-labelledby", "cell-stage-heading");
  section.hidden = true;

  const head = document.createElement("div");
  head.className = "cell-stage-head";
  const titleWrap = document.createElement("div");
  const title = document.createElement("h2");
  title.id = "cell-stage-heading";
  title.textContent = "셀 작업대 관제";
  const meta = node("p", "작업 셀 실시간 관측 연결 대기", "cell-stage-meta");
  titleWrap.append(title, meta);

  const actions = document.createElement("div");
  actions.className = "cell-stage-actions";
  const liveTag = document.createElement("ui-tag");
  liveTag.setAttribute("status", "neutral");
  liveTag.textContent = "확인 중";
  const streamToggle = document.createElement("ui-button");
  streamToggle.setAttribute("kind", "quiet");
  streamToggle.setAttribute("type", "button");
  streamToggle.setAttribute("data-work-read", "");
  streamToggle.textContent = "영상 자동갱신 ON";
  const workLink = node("a", "셀 작업 화면", "ui-action-link");
  workLink.dataset.kind = "quiet";
  workLink.href = "/console/cell";
  actions.append(liveTag, streamToggle, workLink);
  head.append(titleWrap, actions);

  const camGrid = document.createElement("div");
  camGrid.className = "cell-stage-cameras";
  camGrid.setAttribute("role", "region");
  camGrid.setAttribute("aria-label", "셀 실시간 카메라");

  const armGrid = document.createElement("div");
  armGrid.className = "cell-stage-arms";
  armGrid.setAttribute("role", "region");
  armGrid.setAttribute("aria-label", "셀 팔 상태 요약");

  section.append(head, camGrid, armGrid);

  let areaHidden = false;
  let inFlight = false;
  let liveOn = true;
  let controlUnitFetched = false;
  let visionCheckedAt = 0;
  let camLayoutKey = "";

  const isStageActive = () => !areaHidden && !owns("drive") && owns("arms");

  const syncFeedState = () => {
    frames.setRunning(liveOn && isStageActive() && !auth.locked && !document.hidden);
  };

  streamToggle.addEventListener("click", () => {
    liveOn = !liveOn;
    streamToggle.textContent = liveOn ? "영상 자동갱신 ON" : "영상 일시정지";
    syncFeedState();
    render();
  });

    const offSel = selection?.subscribe?.(() => render());
    scope.onDispose?.(offSel);
  scope.listen(document, "visibilitychange", syncFeedState);

  function renderCameras(obs) {
    const cams = obs?.cameras || [];
    const nextKey = cams.map((c) => `${c.source_id}:${c.label}:${c.arm_id || ""}`).join("|");
    if (nextKey !== camLayoutKey) {
      camLayoutKey = nextKey;
      if (!cams.length) {
        const empty = node("p", "등록된 셀 카메라가 없습니다.", "hint");
        camGrid.replaceChildren(empty);
      } else {
        const cards = cams.map((cam) => {
          const card = document.createElement("article");
          card.className = "cell-stage-cam";
          card.dataset.cameraSource = cam.source_id;
          const camHead = document.createElement("div");
          camHead.className = "cell-stage-cam-head";
          const camTitle = node("strong", cam.stream === "depth" ? `${cam.label} · 깊이` : cam.label);
          const camStatus = node("small", "영상 확인 중", "omx-inspector-cam-badge");
          camHead.append(camTitle, camStatus);
          const frameBox = document.createElement("div");
          frameBox.className = "omx-inspector-cam-frame";
          const img = document.createElement("img");
          img.className = "omx-inspector-main-cam omx-inspector-cam";
          img.alt = `${cam.label} 실시간 카메라`;
          img.loading = "lazy";
          const standby = node("span", "영상 대기", "omx-inspector-cam-standby");
          standby.setAttribute("role", "status");
          img.addEventListener("load", () => { standby.hidden = true; });
          frameBox.append(img, standby);
          const toggleZoom = () => img.classList.toggle("focused");
          img.addEventListener("click", toggleZoom);
          card.tabIndex = 0;
          card.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault();
              toggleZoom();
            } else if (ev.key === "Escape") {
              img.classList.remove("focused");
            }
          });
          card.append(camHead, frameBox);
          frames.bind(img, { source: cam.source_id }, camStatus, cam.label);
          return card;
        });
        camGrid.replaceChildren(...cards);
      }
    }
    for (const s of camGrid.querySelectorAll(".omx-inspector-cam-standby")) {
      if (!liveOn) {
        s.hidden = false;
        s.textContent = "영상 일시정지";
      } else if (!s.previousElementSibling?.getAttribute("src")) {
        s.hidden = false;
        s.textContent = "영상 수신 대기";
      }
    }
  }

  function renderArms(obs) {
    const arms = obs?.arms || [];
    if (!arms.length) {
      armGrid.replaceChildren(node("p", auth.locked ? "접속 후 팔 관측을 표시합니다." : "관측 중인 팔이 없습니다.", "hint"));
      return;
    }
    const selectedId = selection?.get?.();
    const cards = arms.map((arm) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = `cell-stage-arm${selectedId === arm.id ? " selected" : ""}`;
      card.dataset.armId = arm.id;
      const top = document.createElement("div");
      top.className = "cell-stage-arm-head";
      const name = node("strong", arm.label);
      const badge = document.createElement("ui-tag");
      if (arm.held) {
        badge.setAttribute("status", "crit");
        badge.textContent = `보류 ${arm.heldIncidents.length}건`;
      } else if (arm.openIncidents.length) {
        badge.setAttribute("status", "warn");
        badge.textContent = `사건 ${arm.openIncidents.length}건`;
      } else if (arm.fresh) {
        badge.setAttribute("status", "active");
        badge.textContent = "실시간";
      } else {
        badge.setAttribute("status", "warn");
        badge.textContent = "대기 · 만료";
      }
      top.append(name, badge);
      const joints = node("p", arm.jointsText || "엔코더 최신 피드백 없음", "cell-stage-joints");
      const mhWrap = document.createElement("p");
      const mhState = createMotorHealthState();
      mhState.accept(arm.motorHealth, { receivedAtMs: obs.receivedAtMs });
      renderMotorHealthSummary(mhWrap, mhState.read(Date.now()));
      card.append(top, joints, mhWrap);
      card.addEventListener("click", () => selection?.set?.(arm.id, { source: "roster" }));
      return card;
    });
    armGrid.replaceChildren(...cards);
  }

  function render() {
    const show = isStageActive();
    section.hidden = !show;
    syncFeedState();
    if (!show) return;
    const obs = view.workcellObs;
    const cu = view.controlUnit;
    const unitId = cu?.unit_id || "ARM-CELL";
    title.textContent = `${unitId} 작업 셀 관제`;
    const parentText = cu?.parent ? `상위 관제: ${cu.parent}` : "독립 셀 관제";
    const revText = cu?.config_revision ? `구성 ${cu.config_revision}` : "";
    const sum = obs?.summary;
    const statText = sum ? `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간 · 카메라 ${sum.camsTotal}대` : "관측 대기";
    meta.textContent = [parentText, revText, statText].filter(Boolean).join(" · ");
    if (!sum || !sum.armsTotal) {
      liveTag.setAttribute("status", "neutral");
      liveTag.textContent = "수신 대기";
    } else if (sum.heldCount > 0 || sum.faultArmCount > 0) {
      liveTag.setAttribute("status", "crit");
      liveTag.textContent = sum.heldCount ? `보류 ${sum.heldCount}건` : "고장 확인";
    } else if (sum.armsFresh > 0) {
      liveTag.setAttribute("status", "active");
      liveTag.textContent = `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간`;
    } else {
      liveTag.setAttribute("status", "warn");
      liveTag.textContent = "피드백 대기";
    }
    renderCameras(obs);
    renderArms(obs);
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
      view.workcellObs = normalizeWorkcellObservations(payload, Date.now());
      render();
      onChanged?.();
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (typeof err?.status === "number") gate.fail(err.status, err.code);
      if (err?.status === 503 || err?.status === 404) {
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
      gate.reset();
      syncFeedState();
    },
  };
}
