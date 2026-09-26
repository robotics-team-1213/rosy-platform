import { createFieldMap } from "./map.js";
import { createHostCards } from "./host-cards.js";
import { createRosNetwork } from "./ros-network.js";
import { createVisionPreview } from "./vision.js";
import { createStatusSummary } from "./status-summary.js";
import { CORE_ONLY_REASON, CORE_ONLY_TEXT, triage } from "./triage.js";
import { HeadlessState } from "/common/core_ui_logic.js";
import { createHoldTicker } from "/common/hold-ticker.js";
import {
  bindFormSave,
  bytes,
  duration,
  elements,
  metricNumber,
  number,
  percent,
  rate,
  setEnabled,
  setFieldMessage,
  setMeter,
  markRequested,
  setText,
  svgText,
} from "./dom.js";
import {
  PAIRED_SOURCES,
  api,
  apiMaybe,
  authHeaders,
  expiryLabel,
  forgetToken,
  isAdmin,
  logout,
  normalizeLoginCode,
  pairWithCode,
  rememberToken,
  session,
  setConnection,
  sourceLabel,
} from "./client.js";
import {
  fillIdentityForm,
  fillSafetyForm,
  initSettings,
  refreshDocks,
  refreshTokens,
  refreshWaypoints,
  renderDockingStatus,
  renderDocks,
  renderTokens,
  renderWaypoints,
} from "./settings.js";

const fieldMap = createFieldMap({
  canvas: elements["map-canvas"],
  empty: elements["map-empty"],
  status: elements["map-status"],
  layerRoot: document.getElementById("field-map-panel"),
  api,
  apiMaybe,
  getPose: () => session.robotState?.pose,
  getNavigation: () => session.robotState?.navigation,
  canGoal: () => session.capabilities?.navigation?.goal_navigation === true
    && new HeadlessState(session.robotState).isFresh("pose"),
  setAction: (text) => setText("action-message", text),
});

export const TELEMETRY_CHANNELS = Object.freeze({
  "pose-x": "pose",
  "pose-y": "pose",
  "pose-yaw": "pose",
  "velocity-linear": "velocity",
  "velocity-angular": "velocity",
  "battery-value": "battery",
  "battery-voltage": "battery",
  "navigation-state": "navigation",
});

function evidenceOf(state, channel) {
  return new HeadlessState(state).evidenceOf(channel);
}

function motionEvidenceBlocks(state) {
  const hs = new HeadlessState(state);
  return !hs.isFresh("pose") || !hs.isFresh("velocity");
}

function renderRobotInfo(info) {
  session.runtimeMode = info.runtime_mode || "";
  renderSafetyHero();
  const name = info.robot_name || info.name || "Rosy";
  setText("robot-name", name);
  setText("robot-id", `${info.robot_id || "—"} / ${info.hardware_model || "unknown model"} / ${info.runtime_mode || "core"}`);
  fillIdentityForm(info);
}

let triageSeen = {};
let lineFollowPending = false;
let trafficPolicyPending = false;

// D-262: 카메라 미리보기는 vision.js 팩토리가 가진다. 셸은 시작·정지만 부른다.
const visionPreview = createVisionPreview({
  elements,
  setText,
  api,
  authHeaders,
  hasToken: () => !!session.token,
  isHidden: () => document.hidden,
});
const stopVisionPreview = (message) => visionPreview.stop(message);
const startVisionPreview = () => visionPreview.start();
let trafficPolicyReadback = null;
let trafficFormDirty = false;

function updateLineFollowButtons() {
  const navigationAvailable = session.capabilities?.navigation?.goal_navigation === true;
  const emergency = session.robotState?.safety?.estop === true;
  document.querySelectorAll("[data-line-mode]").forEach((button) => {
    const enabling = button.dataset.lineMode !== "OFF";
    button.disabled = lineFollowPending || (enabling && (!navigationAvailable || emergency));
  });
}

function renderLineFollow(status = {}) {
  const mode = status.mode || "OFF";
  setText("line-follow-state", status.state || "OFF");
  setText("line-follow-source", status.source || "없음");
  setText("line-follow-error", Number.isFinite(Number(status.error)) ? number(status.error, 3) : "—");
  setText("line-follow-confidence", percent((Number(status.confidence) || 0) * 100));
  setText("line-follow-linear", `${number(status.linear || 0, 3)} m/s`);
  setText("line-follow-angular", `${number(status.angular || 0, 3)} rad/s`);
  setText("line-follow-reason", status.reason || "mode_off");
  document.querySelectorAll("[data-line-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.lineMode === mode);
  });
  updateLineFollowButtons();
}

function renderTrafficStatus(status = {}) {
  setText("traffic-policy-state", status.state || "DISABLED");
  setText("traffic-policy-reason", status.reason || "policy_disabled");
  setText("traffic-policy-signal", status.signal_conflict ? "CONFLICT" : (status.signal_colour || "—"));
  setText(
    "traffic-policy-stop-distance",
    Number.isFinite(Number(status.stop_line_distance_m))
      ? `${number(status.stop_line_distance_m, 3)} m`
      : "—",
  );
  setText("traffic-policy-scene", status.scene_revision || "—");
  setText("traffic-policy-revision", status.policy_revision || "—");
}

function updateTrafficPolicyControls() {
  setEnabled("traffic-policy-stage", !trafficPolicyPending);
  setEnabled("traffic-policy-apply", !trafficPolicyPending && Boolean(trafficPolicyReadback?.staged));
  const signalAvailable = trafficPolicyReadback?.simulation_signal?.available === true;
  document.querySelectorAll("[data-simulation-signal]").forEach((button) => {
    button.disabled = trafficPolicyPending || !signalAvailable;
    button.dataset.active = String(
      button.dataset.simulationSignal === trafficPolicyReadback?.simulation_signal?.colour,
    );
  });
}

function renderTrafficPolicy(readback = {}) {
  trafficPolicyReadback = readback;
  renderTrafficStatus(readback.status || {});
  const draft = readback.staged || readback.active || {};
  if (!trafficFormDirty) {
    elements["traffic-policy-mode"].value = draft.mode || "DISABLED";
    elements["traffic-policy-revision-input"].value = draft.policy_revision || "";
    elements["traffic-approach-distance"].value = draft.approach_distance_m ?? "";
    elements["traffic-stop-distance"].value = draft.stop_distance_m ?? "";
    elements["traffic-stop-dwell"].value = draft.stop_dwell_s ?? "";
    elements["traffic-min-confidence"].value = draft.min_confidence ?? "";
  }
  const message = readback.staged
    ? `검토 대기: ${readback.staged.policy_revision}`
    : `적용됨: ${readback.active?.policy_revision || "—"}`;
  setText("traffic-policy-message", message);
  updateTrafficPolicyControls();
}

// 두 문법은 한 화면에 섞이지 않는다(concept 16 §4 L2). 운용은 공간이고
// 스크롤하지 않으며, 점검은 절차이고 스크롤이 곧 절차다.
function showView(view) {
  const operate = view !== "inspect";
  elements["view-operate-panel"].hidden = !operate;
  elements["view-inspect-panel"].hidden = operate;
  elements["view-operate"].setAttribute("aria-pressed", String(operate));
  elements["view-inspect"].setAttribute("aria-pressed", String(!operate));
  document.body.dataset.view = operate ? "operate" : "inspect";
}

function renderTriage() {
  const node = elements["triage"];
  if (!node) return;
  const { headline, context, seenAt } = triage({
    state: session.robotState,
    inventory: session.inventory,
    seenAt: triageSeen,
  });
  triageSeen = seenAt;

  // 고장이 없으면 자리를 비운다 — "이상 없음"을 초록으로 칠하지 않는다.
  node.hidden = !headline;
  if (!headline) {
    elements["triage-context"].replaceChildren();
    return;
  }
  node.dataset.category = headline.category;
  setText("triage-title", headline.title);
  setText("triage-detail", headline.detail);

  const list = elements["triage-context"];
  list.replaceChildren();
  context.forEach((fault) => {
    const item = document.createElement("li");
    item.dataset.category = fault.category;
    const title = document.createElement("b");
    title.textContent = fault.title;
    const detail = document.createElement("span");
    detail.textContent = fault.detail;
    item.append(title, detail);
    list.append(item);
  });
}

function renderRobotState(state) {
  session.robotState = state;
  elements["hitl-escalation"].hidden = state.hitl_requested !== true;
  setText("robot-id", state.robot_id || "—");
  setText("robot-mode", state.mode);
  setText("state-sequence", `SEQ ${state.seq ?? "—"}`);
  setText("pose-x", number(state.pose?.x, 3), "—", state.evidence?.pose);
  setText("pose-y", number(state.pose?.y, 3), "—", state.evidence?.pose);
  setText("pose-yaw", number(state.pose?.yaw, 3), "—", state.evidence?.pose);
  setText("velocity-linear", number(state.velocity?.linear, 3), "—", state.evidence?.velocity);
  setText("velocity-angular", number(state.velocity?.angular, 3), "—", state.evidence?.velocity);
  setText("battery-value", percent(state.battery?.percent), "—", state.evidence?.battery);
  setText("battery-voltage", metricNumber(state.battery?.voltage) === null ? "voltage —" : `${number(state.battery.voltage, 2)} V`, "—", state.evidence?.battery);
  setText("navigation-state", state.navigation, "—", state.evidence?.navigation);
  setText("map-id", `map ${state.map_id || "—"}`);
  setText("state-age", state.timestamp ? new Date(state.timestamp).toLocaleTimeString("ko-KR") : "—");
  setText("hero-message", state.online === false ? "로봇이 오프라인 상태를 보고했습니다." : "로봇 런타임과 상태 스트림이 연결되었습니다.");

  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === state.mode);
  });
  renderLineFollow(state.line_follow);
  renderTrafficStatus(state.traffic_policy);

  renderSafetyHero();
  setConnection("online", "상태 스트림 연결");
  setText("last-sync", `마지막 동기화 ${new Date().toLocaleTimeString("ko-KR")}`);
  renderTriage();
  if (holdTicker.active && !teleopEligible()) stopTeleop("운전 조건이 변경되어 정지했습니다.");
  updateTeleopControls();
  fieldMap.setPose();
}

// The hero and the triage banner read the same server evidence, so they cannot
// disagree: READY only while the safety channel is fresh. A channel with no
// source at all (CORE-only, D-161) says why instead of claiming a live circuit.
function safetyHero(state, runtimeMode, source) {
  if (state?.safety?.estop) {
    return { tone: "danger", label: "STOPPED", source: source || "비상정지 활성" };
  }
  const judged = evidenceOf(state, "safety");
  if (judged === "fresh") return { tone: "safe", label: "READY", source: "주행 회로 정상" };
  if (judged === "unavailable") {
    return runtimeMode === "core"
      ? { tone: "unverified", label: "HW OFF", source: CORE_ONLY_TEXT }
      : { tone: "unverified", label: "NO SOURCE", source: "안전 회로 출처 없음" };
  }
  return {
    tone: "unverified",
    label: "UNVERIFIED",
    source: judged === "delayed" ? "안전 회로 지연" : "안전 회로 수신 끊김",
  };
}

function renderSafetyHero() {
  if (!session.robotState) return;
  const hero = safetyHero(session.robotState, session.runtimeMode, session.safetySource);
  elements["safety-indicator"].className = `hero-safety ${hero.tone}`;
  setText("safety-label", hero.label);
  setText("safety-source", hero.source);
}

function renderSafety(safety) {
  session.robotState = {
    ...(session.robotState || {}),
    safety: { ...(session.robotState?.safety || {}), estop: Boolean(safety.estop) },
  };
  session.safetySource = safety.source || null;
  renderSafetyHero();
  fillSafetyForm(safety);
  updateTeleopControls();
  updateLineFollowButtons();
}


function renderRuntime(runtime) {
  setText("host-name", runtime.hostname);
  setText("os-name", runtime.os?.pretty_name || runtime.os?.name);
  setText("kernel-name", [runtime.kernel, runtime.architecture].filter(Boolean).join(" / "));
  setText("network-address", runtime.network?.addresses?.join(", "));
  setText("uptime", duration(runtime.uptime_seconds));

  setText("cpu-value", percent(runtime.cpu?.usage_percent));
  setText("cpu-detail", `load ${number(runtime.cpu?.load_1, 2)} / ${runtime.cpu?.logical_count ?? "—"} cores`);
  setMeter("cpu-bar", runtime.cpu?.usage_percent);

  setText("memory-value", percent(runtime.memory?.used_percent));
  setText("memory-detail", `${bytes(runtime.memory?.available_bytes)} available`);
  setMeter("memory-bar", runtime.memory?.used_percent);

  setText("storage-value", percent(runtime.storage?.used_percent));
  setText("storage-detail", `${bytes(runtime.storage?.free_bytes)} free · ${runtime.storage?.path || "—"}`);
  setMeter("storage-bar", runtime.storage?.used_percent);

  const temperature = runtime.temperature_c;
  setText("temperature", Number.isFinite(Number(temperature)) ? `${number(temperature, 1)}°` : null);
  setText("temperature-state", temperature == null ? "센서 없음" : temperature >= 80 ? "고온 경고" : temperature >= 70 ? "주의" : "정상 범위");
  const tempCard = elements.temperature?.closest(".temperature-card");
  if (tempCard) {
    if (!Number.isFinite(Number(temperature))) delete tempCard.dataset.level;
    else if (temperature >= 80) tempCard.dataset.level = "crit";
    else if (temperature >= 70) tempCard.dataset.level = "warn";
    else delete tempCard.dataset.level;
  }
  setText("runtime-warning", runtime.unavailable?.length ? `읽을 수 없는 항목: ${runtime.unavailable.join(", ")}` : "");
  rosNetwork.render(runtime);
}

// D-262: 아래 pushNetworkSample/renderSparkline/renderRosGraph/renderRosNetwork는
// ros-network.js로 옮겼다. 셸은 rosNetwork.render(runtime) 한 줄만 부른다.

// D-262: ROS 통신 격리·연결 지도는 ros-network.js 팩토리가 그린다.
const rosNetwork = createRosNetwork({
  elements,
  setText,
  metricNumber,
  rate,
  svgText,
  history: session.networkHistory,
});

function renderCapabilities(capabilities) {
  session.capabilities = capabilities;
  const slamOn = capabilities?.slam === true;
  const slamChip = elements["slam-capability"];
  if (slamChip) {
    slamChip.dataset.mode = slamOn ? "AVAILABLE" : "HOLD";
    slamChip.textContent = slamOn ? "AVAILABLE" : "HOLD";
  }
  setEnabled("slam-start", slamOn);
  setEnabled("slam-stop", slamOn);
  setEnabled("slam-save", slamOn);
  updateModeButtons();
  updateTeleopControls();
  updateLineFollowButtons();
}

function renderInventory(inventory) {
  session.inventory = inventory;
  const rows = (inventory?.descriptors || []).filter(
    (row) => row.state && row.state !== "not_provided",
  );
  elements["capability-list"].replaceChildren();
  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "capability-item";
    item.dataset.state = row.state;
    if (row.reason === CORE_ONLY_REASON) item.dataset.cause = "runtime";
    const label = document.createElement("span");
    label.textContent = row.id;
    const state = document.createElement("b");
    state.textContent = row.state;
    item.append(label, state);
    if (row.reason) {
      const reason = document.createElement("small");
      reason.textContent = row.reason === CORE_ONLY_REASON ? CORE_ONLY_TEXT : row.reason;
      item.append(reason);
    }
    elements["capability-list"].append(item);
  });
  const usable = rows.filter((row) => row.state === "available" || row.state === "constrained");
  setText("capability-count", `${usable.length} / ${rows.length}`);
  renderTriage();
}

function teleopEligible() {
  return Boolean(
    session.token
    && session.capabilities?.teleop === true
    && session.robotState?.mode === "MANUAL"
    && session.robotState?.safety?.estop !== true
    && elements["bench-safety-confirmed"]?.checked
    && !motionEvidenceBlocks(session.robotState),
  );
}

function updateTeleopControls() {
  const enabled = teleopEligible();
  document.querySelectorAll("[data-teleop]").forEach((button) => {
    button.disabled = !enabled;
  });
  if (!session.token) {
    setText("teleop-message", "operator 접속 키가 필요합니다.");
  } else if (session.capabilities && session.capabilities.teleop !== true) {
    // D-247 7: a runtime mode that holds the motors is not a permission problem.
    const byMode = String(session.capabilities.withheld?.reason || "").startsWith("runtime_mode:");
    setText("teleop-message", byMode && session.motionReason
      ? session.motionReason
      : "현재 하드웨어 프로필에서 teleop을 사용할 수 없습니다.");
  } else if (session.robotState?.safety?.estop) {
    setText("teleop-message", "비상정지가 활성화되어 있습니다.");
  } else if (motionEvidenceBlocks(session.robotState)) {
    const pose = evidenceOf(session.robotState, "pose") || "unavailable";
    const velocity = evidenceOf(session.robotState, "velocity") || "unavailable";
    setText("teleop-message", `pose ${pose} · velocity ${velocity}`);
  } else if (session.robotState?.mode !== "MANUAL") {
    setText("teleop-message", "MANUAL 모드로 전환해야 합니다.");
  } else if (!elements["bench-safety-confirmed"]?.checked) {
    setText("teleop-message", "벤치 안전 확인이 필요합니다.");
  } else if (!holdTicker.active) {
    setText("teleop-message", "버튼을 누르고 있는 동안만 저속 명령을 보냅니다.");
  }
}

function sendTeleop(linear, angular, keepalive = false) {
  return api("/api/v1/teleop", {
    method: "POST",
    body: JSON.stringify({ linear, angular }),
    keepalive,
  });
}

function queueTerminalZero(immediate = false) {
  const prior = session.teleopPending || Promise.resolve();
  if (immediate) {
    const immediateZero = sendTeleop(0, 0, true);
    immediateZero.catch(() => null);
  }
  const terminal = prior
    .catch(() => null)
    .then(() => sendTeleop(0, 0, true));
  session.teleopPending = terminal;
  terminal
    .catch((error) => {
      setText("teleop-message", `정지 전송 실패 · watchdog 대기: ${error.message}`);
    })
    .finally(() => {
      if (session.teleopPending === terminal) session.teleopPending = null;
    });
}

function stopTeleop(message = "정지 명령을 전송했습니다.", immediate = false) {
  // D-250: interval 수명과 zero 1회는 티커가 소유한다. 자격·전송·문구는 셸의 몫이다.
  holdTicker.stop(immediate);
  document.querySelectorAll("[data-teleop]").forEach((button) => button.classList.remove("active"));
  setText("teleop-message", message);
  updateTeleopControls();
}

async function transmitTeleop(linear, angular) {
  if (!holdTicker.active || session.teleopPending) return;
  const request = sendTeleop(linear, angular);
  session.teleopPending = request;
  try {
    await request;
  } catch (error) {
    if (holdTicker.active) stopTeleop(`주행 명령 실패: ${error.message}`);
  } finally {
    if (session.teleopPending === request) session.teleopPending = null;
  }
}

let teleopCommand = { linear: 0, angular: 0 };
// D-250: 홀드-티커는 100ms 운율과 해제 zero만 낸다. 자격은 teleopEligible,
// 전송은 transmitTeleop, zero 절차는 queueTerminalZero가 가진다.
const holdTicker = createHoldTicker({
  intervalMs: session.teleopIntervalMs,
  onTick: () => transmitTeleop(teleopCommand.linear, teleopCommand.angular),
  onZero: (immediate) => {
    if (session.token) queueTerminalZero(immediate);
  },
});

function startTeleop(button, event) {
  event.preventDefault();
  if (!teleopEligible() || holdTicker.active) return;
  const linear = Number(button.dataset.linear);
  const angular = Number(button.dataset.angular);
  if (!Number.isFinite(linear) || !Number.isFinite(angular)) return;

  teleopCommand = { linear, angular };
  button.classList.add("active");
  setText("teleop-message", `${button.querySelector("small")?.textContent || "주행"} 명령 전송 중…`);
  holdTicker.start();
}

function updateModeButtons() {
  const navigationAvailable = session.capabilities?.navigation?.goal_navigation === true;
  document.querySelectorAll("[data-mode]").forEach((button) => {
    const unsupported = button.dataset.mode === "NAVIGATION" && !navigationAvailable;
    button.disabled = session.modeChangePending || unsupported;
    button.title = unsupported ? "이 프로필에서는 내비게이션이 비활성화되어 있습니다." : "";
  });
}

function renderEvents(payload) {
  const events = [...(payload.events || [])].reverse().slice(0, 10);
  elements["event-list"].replaceChildren();
  if (!events.length) {
    const empty = document.createElement("li");
    const note = document.createElement("ui-empty");
    note.textContent = "수신된 이벤트가 없습니다.";
    empty.append(note);
    elements["event-list"].append(empty);
    return;
  }
  events.forEach((event) => {
    const row = document.createElement("li");
    const time = document.createElement("time");
    time.className = "event-time";
    time.textContent = event.ts ? new Date(event.ts).toLocaleTimeString("ko-KR") : "—";
    const type = document.createElement("span");
    type.className = "event-type";
    type.textContent = event.type || "unknown.event";
    const severity = document.createElement("span");
    severity.className = `event-severity ${event.severity || "info"}`;
    severity.textContent = (event.severity || "info").toUpperCase();
    row.append(time, type, severity);
    elements["event-list"].append(row);
  });
}




// D-262: 호스트 카드 렌더는 host-cards.js 팩토리가 가진다. 역할 판단은
// 셸의 isAdmin, 커미셔닝 후속(운전 불가 사유+teleop 갱신)은 셸이 주입한다.
const hostCards = createHostCards({
  elements,
  setText,
  setEnabled,
  isAdmin,
  onCommissioningRendered: (reason) => {
    session.motionReason = reason;
    updateTeleopControls();
  },
});
const {
  renderHostNetwork,
  renderHostRelease,
  renderCommissioning,
  renderHardware,
} = hostCards;

// D-260 5: the summary line. A device opens the inspect view at its card row.
const statusSummary = createStatusSummary({
  elements,
  onOpenDevice: (deviceId) => {
    showView("inspect");
    const row = deviceId
      ? elements["hardware-list"]?.querySelector(`[data-device="${CSS.escape(deviceId)}"]`)
      : null;
    const target = row || elements["hardware-card"];
    target?.scrollIntoView({ block: "center" });
    if (target) {
      target.tabIndex = -1;
      target.focus({ preventScroll: true });
    }
  },
});

function updateAdminControls() {
  setEnabled("limits-save", isAdmin());
  setEnabled("dock-register", isAdmin());
  setEnabled("identity-save", isAdmin());
  setEnabled("token-add", isAdmin());
  setEnabled("hardware-refresh", isAdmin());
  const networkCard = document.getElementById("network-card");
  const networkOn = isAdmin() && networkCard?.dataset.available === "true";
  setEnabled("network-apply", networkOn);
  setEnabled("network-ap-off", networkOn);
  setEnabled("network-ap-on", networkOn);
  setEnabled("network-connect", networkOn);
}

// D-193 5: the server says who this browser is (role, label, source, expiry) on a
// route every role may read. Probing an admin-only route instead cost every
// viewer a 403 in the console on each load (US-010).
async function detectRole() {
  session.role = "";
  session.identity = null;
  try {
    const me = await api("/api/v1/auth/whoami");
    session.identity = me || null;
    session.role = me?.role || "";
  } catch (_error) {
    session.role = "";
  }
  renderIdentity();
  updateAdminControls();
}

function renderIdentity() {
  const me = session.identity;
  const badge = elements["whoami-badge"];
  const button = elements["logout"];
  if (!me) {
    if (badge) badge.hidden = true;
    if (button) button.hidden = true;
    return;
  }
  setText("whoami-role", me.role || "—");
  const who = me.label || me.id || "";
  setText("whoami-detail", [who, sourceLabel(me.source), expiryLabel(me.expires_at)]
    .filter(Boolean).join(" · "));
  if (badge) {
    badge.hidden = false;
    badge.title = `${me.role} · ${who} · ${sourceLabel(me.source)} · ${expiryLabel(me.expires_at)}`;
  }
  if (button) {
    button.hidden = false;
    // Only a paired token can log itself out (API Ref v1.19); any other token
    // is only forgotten by this browser and stays valid on the robot.
    button.textContent = PAIRED_SOURCES.has(me.source) ? "로그아웃" : "이 브라우저에서 잊기";
  }
}

async function refreshSlowData() {
  const required = [
    [api("/api/v1/system/runtime"), renderRuntime],
    [api("/api/v1/system/info"), renderRobotInfo],
    [api("/api/v1/system/capabilities"), renderCapabilities],
    [api("/api/v1/system/inventory"), renderInventory],
    [api("/api/v1/safety/state"), renderSafety],
    [api("/api/v1/events?limit=10"), renderEvents],
    [api("/api/v1/traffic"), renderTrafficPolicy],
    [api("/api/v1/host/network"), renderHostNetwork],
    [api("/api/v1/host/release"), renderHostRelease],
    [api("/api/v1/host/commissioning"), renderCommissioning],
  ];
  const optional = [
    [api("/api/v1/waypoints"), renderWaypoints],
    [api("/api/v1/docking/status"), renderDockingStatus],
    [api("/api/v1/host/hardware"), renderHardware],
    [api("/api/v1/host/status-summary"), statusSummary.render],
    [api("/api/v1/docking/docks"), renderDocks],
    [isAdmin() ? api("/api/v1/system/tokens") : Promise.resolve({tokens: []}), renderTokens],
    [fieldMap.refresh(), () => {}],
  ];
  const [requiredResults, optionalResults] = await Promise.all([
    Promise.allSettled(required.map((item) => item[0])),
    Promise.allSettled(optional.map((item) => item[0])),
  ]);
  requiredResults.forEach((result, index) => {
    if (result.status === "fulfilled") required[index][1](result.value);
  });
  optionalResults.forEach((result, index) => {
    if (result.status === "fulfilled") optional[index][1](result.value);
  });
  const failed = requiredResults.find((result) => result.status === "rejected");
  if (failed) throw failed.reason;
}

async function refreshRobotState() {
  const state = await api("/api/v1/robot/state");
  // 이제부터는 빈 값이 "물었는데 없다"를 뜻한다 — em dash를 쓸 수 있다.
  markRequested();
  renderRobotState(state);
}

// Reconnect backoff. It grows on every close and resets only once a socket has
// stayed live for RECONNECT_STABLE_MS, so a server that accepts, sends one frame
// and closes (4401, 1013, a restart loop) never gets a hot loop.
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const RECONNECT_STABLE_MS = 10000;

function closeStateSocket() {
  const socket = session.socket;
  session.socket = null;
  session.socketLive = false;
  clearTimeout(session.stableTimer);
  session.stableTimer = null;
  socket?.close();
}

function stopStateSocket() {
  clearTimeout(session.reconnectTimer);
  session.reconnectTimer = null;
  clearInterval(session.fallbackTimer);
  session.fallbackTimer = null;
  closeStateSocket();
}

function startRestFallback() {
  if (session.fallbackTimer) return;
  setConnection("error", "REST 폴링 전환");
  session.fallbackTimer = setInterval(() => refreshRobotState().catch(showConnectionError), 2000);
}

function scheduleReconnect() {
  clearTimeout(session.reconnectTimer);
  const delay = session.reconnectDelayMs;
  session.reconnectDelayMs = Math.min(delay * 2, RECONNECT_MAX_MS);
  const jitter = Math.round(delay * 0.2 * Math.random());
  session.reconnectTimer = setTimeout(() => {
    session.reconnectTimer = null;
    if (session.token && !session.socket) connectStateSocket();
  }, delay + jitter);
}

// 4401 means the token is missing, wrong, revoked, logged out or expired, or the
// first message came too late. Ask REST which: 401 there ends the session,
// anything else is retried with backoff.
async function verifyAfterSocketRefusal() {
  try {
    await api("/api/v1/auth/whoami");
  } catch (error) {
    if (error.status === 401) {
      signOut("세션이 만료되었거나 회수되었습니다. 다시 로그인하세요.");
      return;
    }
  }
  if (session.token) scheduleReconnect();
}

function connectStateSocket() {
  // REST polling, if running, keeps going until the new socket delivers state.
  clearTimeout(session.reconnectTimer);
  session.reconnectTimer = null;
  closeStateSocket();
  if (!session.token) return;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  // D-193 10: the token goes in the first message, never in the URL.
  const socket = new WebSocket(`${scheme}://${window.location.host}/ws/state`);
  session.socket = socket;
  socket.addEventListener("open", () => {
    if (socket !== session.socket || !session.token) return;
    socket.send(JSON.stringify({ type: "auth", token: session.token }));
  });
  socket.addEventListener("message", (event) => {
    if (socket !== session.socket) return;
    if (!session.socketLive) {
      session.socketLive = true;
      session.stableTimer = setTimeout(() => {
        if (socket === session.socket) session.reconnectDelayMs = RECONNECT_MIN_MS;
      }, RECONNECT_STABLE_MS);
      clearInterval(session.fallbackTimer);
      session.fallbackTimer = null;
      setConnection("online", "상태 스트림 연결");
    }
    try { renderRobotState(JSON.parse(event.data)); } catch (_error) { setConnection("error", "상태 해석 실패"); }
  });
  socket.addEventListener("close", (event) => {
    if (socket !== session.socket) return;
    session.socket = null;
    session.socketLive = false;
    clearTimeout(session.stableTimer);
    session.stableTimer = null;
    if (!session.token) return;
    startRestFallback();
    if (event.code === 4401) {
      verifyAfterSocketRefusal();
    } else if (event.code === 4403) {
      // Authenticated but not allowed: retrying cannot change that.
      setConnection("error", "상태 스트림 권한 없음 · REST 폴링");
    } else {
      // 1013 (first-message slots full) arrives as 1006 before accept; both wait.
      scheduleReconnect();
    }
  });
}

/** End this browser's session locally: stop everything that uses the token, then forget it. */
function signOut(message) {
  stopTeleop("로그아웃으로 정지했습니다.");
  stopStateSocket();
  clearInterval(session.refreshTimer);
  session.refreshTimer = null;
  stopVisionPreview("카메라 인증 대기");
  forgetToken();
  session.reconnectDelayMs = RECONNECT_MIN_MS;
  renderIdentity();
  updateAdminControls();
  setConnection("unknown", "인증 대기");
  setText("auth-notice", message);
  elements["auth-drawer"].classList.add("open");
}

function showConnectionError(error) {
  if (error?.status === 401 && session.token) {
    // The robot no longer knows this token (expired, revoked, logged out elsewhere).
    signOut("세션이 만료되었거나 회수되었습니다. 다시 로그인하세요.");
    return;
  }
  stopTeleop("연결 오류로 정지했습니다.");
  setConnection("error", "연결 확인 필요");
  setText("hero-message", error.message || "Rosy API에 연결할 수 없습니다.");
}

async function connect() {
  session.reconnectDelayMs = RECONNECT_MIN_MS;
  setText("auth-notice", "");
  setConnection("unknown", "연결 중");
  await detectRole();
  await Promise.all([refreshRobotState(), refreshSlowData()]);
  connectStateSocket();
  clearInterval(session.refreshTimer);
  session.refreshTimer = setInterval(() => refreshSlowData().catch(showConnectionError), 5000);
  startVisionPreview();
  elements["auth-drawer"].classList.remove("open");
}

elements["auth-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  stopVisionPreview("카메라 재인증 중");
  // A pasted token (card or manual) has no expiry: this tab only (D-193 6).
  rememberToken(elements["token-input"].value.trim());
  elements["token-input"].value = "";
  setText("auth-message", "연결 확인 중…");
  try {
    await connect();
    setText("auth-message", "연결되었습니다.");
  } catch (error) {
    forgetToken();
    stopStateSocket();
    renderIdentity();
    stopVisionPreview("카메라 인증 실패");
    setText("auth-message", error.message);
    showConnectionError(error);
  }
});

let codeRetryTimer = null;

elements["code-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  if (elements["code-submit"].disabled) return;
  const code = normalizeLoginCode(elements["code-input"].value);
  if (code.error) {
    setText("code-message", code.error);
    return;
  }
  setText("code-message", "코드 확인 중…");
  elements["code-submit"].disabled = true;
  let identity = null;
  try {
    identity = await pairWithCode(code.value, {
      label: elements["code-label"].value.trim(),
      persist: elements["code-remember"].checked,
    });
  } catch (error) {
    setText("code-message", error.message || "로봇에 닿지 못했습니다.");
    // 429: keep the button off until the server's Retry-After has passed.
    clearTimeout(codeRetryTimer);
    codeRetryTimer = setTimeout(() => {
      elements["code-submit"].disabled = false;
    }, (error.retryAfter || 0) * 1000);
    return;
  }
  elements["code-submit"].disabled = false;
  elements["code-input"].value = "";
  stopVisionPreview("카메라 재인증 중");
  try {
    await connect();
    setText("code-message", `${identity.role} 로 로그인했습니다 · ${expiryLabel(identity.expires_at)}`);
  } catch (error) {
    setText("code-message", `로그인은 되었지만 연결하지 못했습니다: ${error.message}`);
    showConnectionError(error);
  }
});

function showAuthTab(which) {
  const code = which === "code";
  elements["auth-tab-code"].setAttribute("aria-selected", String(code));
  elements["auth-tab-token"].setAttribute("aria-selected", String(!code));
  elements["code-form"].hidden = !code;
  elements["auth-form"].hidden = code;
  elements[code ? "code-input" : "token-input"].focus();
}

elements["auth-tab-code"].addEventListener("click", () => showAuthTab("code"));
elements["auth-tab-token"].addEventListener("click", () => showAuthTab("token"));

elements["logout"].addEventListener("click", async () => {
  try {
    const deleted = await logout();
    signOut(deleted
      ? "로그아웃했습니다. 이 브라우저의 키는 로봇에서 지워졌습니다."
      : "이 브라우저에서 키를 지웠습니다. 토큰 자체는 로봇에 남아 있습니다 — 회수는 설정의 API 토큰에서 합니다.");
  } catch (error) {
    setText("hero-message", `로그아웃 실패: ${error.message}`);
  }
});

elements["open-auth"].addEventListener("click", () => elements["auth-drawer"].classList.add("open"));
elements["close-auth"].addEventListener("click", () => elements["auth-drawer"].classList.remove("open"));
elements["refresh-events"].addEventListener("click", () => api("/api/v1/events?limit=10").then(renderEvents).catch(showConnectionError));

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.disabled || session.modeChangePending) return;
    const requestedMode = button.dataset.mode;
    stopTeleop("모드 변경 전에 정지했습니다.");
    if (!window.confirm(`${requestedMode} 모드로 변경할까요? 주변 안전을 확인하세요.`)) return;
    session.modeChangePending = true;
    updateModeButtons();
    try {
      await api("/api/v1/mode", { method: "POST", body: JSON.stringify({ mode: requestedMode }) });
      setText("action-message", `${requestedMode} 모드 요청을 전송했습니다.`);
      await refreshRobotState();
    } catch (error) {
      setText("action-message", `모드 변경 실패: ${error.message}`);
    } finally {
      session.modeChangePending = false;
      updateModeButtons();
    }
  });
});

document.querySelectorAll("[data-line-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.disabled || lineFollowPending) return;
    const mode = button.dataset.lineMode;
    stopTeleop("차선 추종 모드 변경 전에 정지했습니다.");
    if (mode !== "OFF" && !window.confirm(`${button.textContent.trim()} 차선 추종을 시작할까요? 주변 안전을 확인하세요.`)) return;
    lineFollowPending = true;
    updateLineFollowButtons();
    try {
      const status = await api("/api/v1/line-follow/mode", {
        method: "PUT",
        body: JSON.stringify({ mode }),
      });
      renderLineFollow(status);
      setText("action-message", mode === "OFF" ? "차선 추종을 해제했습니다." : `${button.textContent.trim()} 차선 추종을 선택했습니다.`);
      await refreshRobotState();
    } catch (error) {
      setText("action-message", `차선 추종 변경 실패: ${error.message}`);
    } finally {
      lineFollowPending = false;
      updateLineFollowButtons();
    }
  });
});

[
  "traffic-policy-mode",
  "traffic-policy-revision-input",
  "traffic-approach-distance",
  "traffic-stop-distance",
  "traffic-stop-dwell",
  "traffic-min-confidence",
].forEach((id) => elements[id]?.addEventListener("input", () => {
  trafficFormDirty = true;
}));

elements["traffic-policy-stage"]?.addEventListener("click", async () => {
  if (trafficPolicyPending) return;
  trafficPolicyPending = true;
  updateTrafficPolicyControls();
  const body = {
    mode: elements["traffic-policy-mode"].value,
    policy_revision: elements["traffic-policy-revision-input"].value.trim(),
    approach_distance_m: Number(elements["traffic-approach-distance"].value),
    stop_distance_m: Number(elements["traffic-stop-distance"].value),
    stop_dwell_s: Number(elements["traffic-stop-dwell"].value),
    min_confidence: Number(elements["traffic-min-confidence"].value),
  };
  try {
    const readback = await api("/api/v1/traffic/policy/stage", {
      method: "POST",
      body: JSON.stringify(body),
    });
    trafficFormDirty = false;
    renderTrafficPolicy(readback);
    setText("traffic-policy-message", `검토본 저장됨: ${body.policy_revision}`);
  } catch (error) {
    setText("traffic-policy-message", `정책 검증 실패: ${error.message}`);
  } finally {
    trafficPolicyPending = false;
    updateTrafficPolicyControls();
  }
});

elements["traffic-policy-apply"]?.addEventListener("click", async () => {
  if (trafficPolicyPending || !trafficPolicyReadback?.staged) return;
  if (!window.confirm("로봇이 완전히 정지했습니까? 검토 중인 교통 정책을 적용합니다.")) return;
  trafficPolicyPending = true;
  updateTrafficPolicyControls();
  try {
    const readback = await api("/api/v1/traffic/policy/apply", {
      method: "POST",
    });
    renderTrafficPolicy(readback);
    setText("traffic-policy-message", "정지 상태에서 정책을 적용했습니다.");
  } catch (error) {
    setText("traffic-policy-message", `정책 적용 실패: ${error.message}`);
  } finally {
    trafficPolicyPending = false;
    updateTrafficPolicyControls();
  }
});

document.querySelectorAll("[data-simulation-signal]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.disabled || trafficPolicyPending) return;
    trafficPolicyPending = true;
    updateTrafficPolicyControls();
    try {
      await api("/api/v1/traffic/simulation/signal", {
        method: "PUT",
        body: JSON.stringify({ colour: button.dataset.simulationSignal }),
      });
      const readback = await api("/api/v1/traffic");
      renderTrafficPolicy(readback);
    } catch (error) {
      setText("traffic-policy-message", `SIM 신호 변경 실패: ${error.message}`);
    } finally {
      trafficPolicyPending = false;
      updateTrafficPolicyControls();
    }
  });
});

document.querySelectorAll("[data-teleop]").forEach((button) => {
  button.addEventListener("pointerdown", (event) => startTeleop(button, event));
  button.addEventListener("pointerup", () => stopTeleop());
  button.addEventListener("pointercancel", () => stopTeleop("포인터 취소로 정지했습니다."));
  button.addEventListener("pointerleave", () => stopTeleop("버튼 이탈로 정지했습니다."));
  button.addEventListener("contextmenu", (event) => event.preventDefault());
});

elements["teleop-override"].addEventListener("click", () => {
  elements["teleop-heading"].scrollIntoView({ behavior: "smooth", block: "center" });
  elements["bench-safety-confirmed"].focus();
});

elements["bench-safety-confirmed"].addEventListener("change", () => {
  if (!elements["bench-safety-confirmed"].checked) stopTeleop("안전 확인이 해제되어 정지했습니다.");
  updateTeleopControls();
});
window.addEventListener("pointerup", () => stopTeleop());
window.addEventListener("blur", () => stopTeleop("화면 포커스가 해제되어 정지했습니다."));
window.addEventListener("pagehide", () => stopTeleop("페이지를 벗어나 정지했습니다.", true));
window.addEventListener("pagehide", () => stopVisionPreview("카메라 연결 종료"));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopTeleop("화면이 숨겨져 정지했습니다.");
    stopVisionPreview("숨겨진 탭 · 카메라 일시 중지");
  } else if (session.token) {
    startVisionPreview();
  }
});

elements["view-operate"].addEventListener("click", () => showView("operate"));
elements["view-inspect"].addEventListener("click", () => showView("inspect"));
showView("operate");

elements["emergency-stop"].addEventListener("click", async () => {
  if (!window.confirm("Rosy를 즉시 정지할까요?")) return;
  stopTeleop("비상정지를 요청했습니다.");
  try {
    await api("/api/v1/safety/stop", { method: "POST" });
    setText("action-message", "비상정지가 활성화되었습니다.");
    await refreshRobotState();
  } catch (error) {
    setText("action-message", `정지 명령 실패: ${error.message}`);
  }
});

elements["release-stop"].addEventListener("click", async () => {
  if (!window.confirm("주변 안전을 확인했고 정지를 해제할까요?")) return;
  try {
    await api("/api/v1/safety/release", { method: "POST" });
    setText("action-message", "비상정지가 해제되었습니다.");
    await refreshRobotState();
  } catch (error) {
    setText("action-message", `정지 해제 실패: ${error.message}`);
  }
});



elements["dds-cyclone-apply"]?.addEventListener("click", async () => {
  if (!window.confirm("CycloneDDS를 저장하고 로봇을 재부팅할까요? 모터와 화면이 잠시 내려갑니다.")) return;
  try {
    const payload = await api("/api/v1/system/dds/cyclone", {
      method: "POST",
      body: JSON.stringify({
        confirmed: true,
        idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      }),
    });
    const reboot = payload.reboot || {};
    if (reboot.available === false) {
      setText("action-message", reboot.detail || "저장했습니다. 런타임을 다시 띄우세요.");
      return;
    }
    setText("action-message", reboot.ok ? "재부팅을 요청했습니다." : (reboot.detail || "재부팅이 거부되었습니다."));
  } catch (error) {
    setText("action-message", `Cyclone 적용 실패: ${error.message}`);
  }
});

// D-247: CORE only writes a request file; the root probe measures. The result
// lands a few seconds later, so the card is read again after a pause.
elements["hardware-refresh"]?.addEventListener("click", async () => {
  setEnabled("hardware-refresh", false);
  try {
    const reply = await api("/api/v1/host/hardware/refresh", {method: "POST"});
    setText("hardware-note", reply.detail || "장치 점검을 요청했습니다.");
    if (reply.accepted) {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      renderHardware(await api("/api/v1/host/hardware"));
    }
  } catch (error) {
    setText("hardware-note", `장치 점검 요청 실패: ${error.message}`);
  } finally {
    setEnabled("hardware-refresh", isAdmin());
  }
});

// D-247 6: buzzer / lamp test and the person's answer. CORE writes a request
// file for the root rosy-hw-test; the outcome lands a moment later, so the card
// is read until it shows this request's outcome (test.request_id), at most
// HW_TEST_WAIT_MS, instead of a fixed pause that a slow run would outlast.
const HW_TEST_WAIT_MS = 12000;
const HW_TEST_POLL_MS = 1000;

async function waitForHardwareTest(requestId) {
  const deadline = Date.now() + HW_TEST_WAIT_MS;
  let payload = await api("/api/v1/host/hardware");
  while (payload?.test?.request_id !== requestId && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, HW_TEST_POLL_MS));
    payload = await api("/api/v1/host/hardware");
  }
  return payload;
}

elements["hardware-list"]?.addEventListener("click", async (event) => {
  const button = event.target.closest?.("[data-hw-action]");
  if (!button || button.disabled || !isAdmin()) return;
  const device = button.dataset.device;
  const action = button.dataset.hwAction;
  button.disabled = true;
  try {
    if (action === "test") {
      const reply = await api("/api/v1/host/hardware/test", {method: "POST", body: JSON.stringify({device})});
      setText("hardware-note", reply.detail || "시험을 요청했습니다.");
      const payload = await waitForHardwareTest(reply.request_id);
      renderHardware(payload);
      if (payload?.test?.request_id !== reply.request_id) {
        setText("hardware-note", "시험 결과가 12초 안에 오지 않았습니다. 잠시 뒤 다시 시험하세요.");
      }
      return;
    }
    const observed = action === "observed";
    await api("/api/v1/host/hardware/confirm", {method: "POST", body: JSON.stringify({device, observed})});
    renderHardware(await api("/api/v1/host/hardware"));
    setText("hardware-note", "확인 결과를 기록했습니다.");
  } catch (error) {
    setText("hardware-note", `장치 시험 실패: ${error.message}`);
    button.disabled = false;
  }
});

async function applyNetworkMode(mode, prompt) {
  if (!window.confirm(prompt)) return;
  try {
    const payload = await api("/api/v1/host/network/mode", {
      method: "POST",
      body: JSON.stringify({
        mode,
        confirmed: true,
        idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      }),
    });
    if (payload.available === false) {
      setText("network-note", payload.detail || "Host Agent가 없어 적용하지 못했습니다.");
      return;
    }
    setText("network-note", payload.ok ? `${mode} 를 적용했습니다.` : (payload.detail || "적용이 거부되었습니다."));
    const status = await api("/api/v1/host/network");
    renderHostNetwork(status);
  } catch (error) {
    setText("network-note", `네트워크 모드 변경 실패: ${error.message}`);
  }
}

elements["network-ap-off"]?.addEventListener("click", () => {
  applyNetworkMode("SITE_STA", "AP를 끌까요? 로봇은 사업장 Wi-Fi(SITE_STA)만 씁니다. 연결이 잠깐 끊길 수 있습니다.");
});

elements["network-ap-on"]?.addEventListener("click", () => {
  applyNetworkMode("RELAY_AP_STA", "AP를 켤까요? 로봇이 릴레이(AP+STA)를 엽니다. 연결이 잠깐 끊길 수 있습니다.");
});

elements["network-connect"]?.addEventListener("click", async () => {
  const ssid = elements["network-ssid-input"]?.value.trim();
  const input = elements["network-psk-input"];
  const psk = input ? input.value : "";
  if (!ssid) {
    setText("network-note", "SSID를 입력하세요.");
    return;
  }
  if (psk.length < 8) {
    setText("network-note", "암호는 8자 이상이어야 합니다.");
    return;
  }
  if (!window.confirm(`${ssid} 에 연결할까요? 연결이 잠깐 끊길 수 있습니다.`)) return;
  try {
    const payload = await api("/api/v1/host/network/connect", {
      method: "POST",
      body: JSON.stringify({
        ssid,
        psk,
        confirmed: true,
        idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      }),
    });
    if (elements["network-psk-input"]) elements["network-psk-input"].value = "";
    if (payload.available === false) {
      setText("network-note", payload.detail || "Host Agent가 없어 연결하지 못했습니다.");
      return;
    }
    setText("network-note", payload.ok ? `${ssid} 에 연결했습니다.` : (payload.detail || "연결이 거부되었습니다."));
    const status = await api("/api/v1/host/network");
    renderHostNetwork(status);
  } catch (error) {
    if (elements["network-psk-input"]) elements["network-psk-input"].value = "";
    setText("network-note", `Wi-Fi 연결 실패: ${error.message}`);
  }
});

elements["network-apply"]?.addEventListener("click", async () => {
  const profileId = elements["network-profile-id"]?.value.trim();
  if (!profileId) {
    setText("network-note", "프로파일 id를 입력하세요.");
    return;
  }
  if (!window.confirm(`${profileId} 네트워크 프로파일을 적용할까요? 연결이 잠깐 끊길 수 있습니다.`)) return;
  try {
    const payload = await api("/api/v1/host/network/apply", {
      method: "POST",
      body: JSON.stringify({
        profile_id: profileId,
        confirmed: true,
        idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      }),
    });
    if (payload.available === false) {
      setText("network-note", payload.detail || "Host Agent가 없어 적용하지 못했습니다.");
      return;
    }
    setText("network-note", payload.ok ? `${profileId} 를 적용했습니다.` : (payload.detail || "적용이 거부되었습니다."));
    const status = await api("/api/v1/host/network");
    renderHostNetwork(status);
  } catch (error) {
    setText("network-note", `프로파일 적용 실패: ${error.message}`);
  }
});

bindFormSave("network-connect-form", "network-connect");
bindFormSave("network-apply-form", "network-apply");

initSettings({
  onIdentityChanged: renderRobotInfo,
  refreshRobotState: () => refreshRobotState(),
});

setInterval(() => setText("clock", new Date().toLocaleTimeString("ko-KR", { hour12: false })), 1000);
setText("clock", new Date().toLocaleTimeString("ko-KR", { hour12: false }));

if (session.token) {
  connect().catch((error) => {
    showConnectionError(error);
    elements["auth-drawer"].classList.add("open");
  });
} else {
  elements["auth-drawer"].classList.add("open");
}
