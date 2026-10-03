// 텔레메트리 렌더 — 서버 상태를 화면 텍스트로 옮기는 함수들과 교통 정책 패널.
// app.js 에서 분리된 모듈(D-362 P1): dom/client/triage/settings/ros-network 외
// 셸 의존이 없어 어떤 셸 함수도 import 하지 않는다. 이 파일이 셸 싱글턴
// (fieldMap·teleop·hostCards) 을 필요로 하게 되면 그 함수는 여기 있을 수 없다.
import {
  bytes,
  duration,
  elements,
  metricNumber,
  number,
  percent,
  rate,
  setEnabled,
  setOff,
  setMeter,
  setTagState,
  setText,
  svgText,
} from "./dom.js";
import { api, session } from "./client.js";
import {
  CONFIGURED_REASONS,
  CORE_ONLY_TEXT,
  DRIVE_DISABLED_TEXT,
  estopFault,
  reasonText,
  triage,
} from "./triage.js";
import { fillIdentityForm } from "./settings.js";
import { createRosNetwork } from "./ros-network.js";
import { HeadlessState, EVIDENCE_LABEL } from "/common/core_ui_logic.js";

const CAPABILITY_LABEL = Object.freeze({
  "mobility.move": "이동",
  "mobility.navigate": "목표 주행",
  "mobility.follow": "따라가기",
  "mobility.lead": "선도",
  "mobility.dock": "도킹",
  "perception.localize": "위치 추정",
});
const PRESENTATION_LABEL = Object.freeze({
  available: "쓸 수 있음",
  constrained: "제한",
  degraded_fallback: "대체 동작",
  blocked: "막힘",
  not_provided: "없음",
});
const LINE_WORD = Object.freeze({
  OFF: "꺼짐",
  mode_off: "꺼짐",
  policy_disabled: "정책 꺼짐",
});

function knownWord(table, value) {
  return Object.hasOwn(table, value) ? table[value] : String(value ?? "");
}

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

export function evidenceOf(state, channel) {
  return new HeadlessState(state).evidenceOf(channel);
}

export function motionEvidenceBlocks(state) {
  const hs = new HeadlessState(state);
  return !hs.isFresh("pose") || !hs.isFresh("velocity");
}

export function renderRobotInfo(info) {
  session.runtimeMode = info.runtime_mode || "";
  renderSafetyHero();
  const name = info.robot_name || info.name || "Rosy";
  setText("robot-name", name);
  // 계보줄: 누구인지·무엇으로 돌아가는지를 한 줄로. 버전은 정체성의 일부다 —
  // "지금 뭘 돌리고 있나"는 운용 첫 화면에서 답해야 한다(D-280).
  const lineage = [
    info.robot_id || "—",
    info.hardware_model || "unknown model",
    info.software_version ? `v${info.software_version}` : null,
    info.runtime_mode || "core",
  ].filter(Boolean);
  setText("robot-id", lineage.join(" / "));
  fillIdentityForm(info);
}

let triageSeen = {};

// 라인 추종 버튼 상태 — 대기 중 플래그는 셸의 클릭 핸들러가 바꾼다.
export const lineFollow = { pending: false };

export function updateLineFollowButtons() {
  const navigationAvailable = session.capabilities?.navigation?.goal_navigation === true;
  const emergency = session.robotState?.safety?.estop === true;
  document.querySelectorAll("[data-line-mode]").forEach((button) => {
    const enabling = button.dataset.lineMode !== "OFF";
    // 요청 중(lineFollow.pending)은 짧은 잠금이라 사유 없이 끈다.
    setOff(button, lineFollow.pending || (enabling && (!navigationAvailable || emergency)),
      !enabling || lineFollow.pending ? "" : emergency ? "비상정지 중" : "내비게이션을 쓸 수 없음");
  });
}

export function renderLineFollow(status = {}) {
  const mode = status.mode || "OFF";
  setText("line-follow-state", knownWord(LINE_WORD, status.state || "OFF"));
  setText("line-follow-source", status.source || "없음");
  setText("line-follow-error", Number.isFinite(Number(status.error)) ? number(status.error, 3) : "—");
  setText("line-follow-confidence", percent((Number(status.confidence) || 0) * 100));
  setText("line-follow-linear", `${number(status.linear || 0, 3)} m/s`);
  setText("line-follow-angular", `${number(status.angular || 0, 3)} rad/s`);
  setText("line-follow-reason", knownWord(LINE_WORD, status.reason || "mode_off"));
  document.querySelectorAll("[data-line-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lineMode === mode));
  });
  updateLineFollowButtons();
}

export function renderTrafficStatus(status = {}) {
  setText("traffic-policy-state", status.state || "DISABLED");
  setText("traffic-policy-reason", knownWord(LINE_WORD, status.reason || "policy_disabled"));
  setText("traffic-policy-signal", status.signal_conflict ? "CONFLICT" : (status.signal_colour || "—"));
  setText(
    "traffic-policy-stop-distance",
    Number.isFinite(Number(status.stop_line_distance_m))
      ? `${number(status.stop_line_distance_m, 3)} m`
      : "—",
  );
  setText("traffic-policy-rule", status.junction_rule || "signal_controlled");
  setText("traffic-policy-source", status.signal_head_frozen ? "frozen" : (status.signal_source_kind || "camera"));
  setText("traffic-policy-scene", status.scene_revision || "—");
  setText("traffic-policy-revision", status.policy_revision || "—");
}

let trafficPolicyReadback = null;
let trafficFormDirty = false;
let trafficPolicyPending = false;
const actionHooks = {runConfirmed: async () => {}, captureLifetime: () => ({current: () => false})};
export function initTelemetry(overrides) { Object.assign(actionHooks, overrides); }
let trafficOwner = null;
function trafficPending(pending) { trafficPolicyPending = pending; updateTrafficPolicyControls(); }
function trafficInputSnapshot() {
  return JSON.stringify(["traffic-policy-mode", "traffic-policy-revision-input", "traffic-approach-distance", "traffic-stop-distance", "traffic-stop-dwell", "traffic-min-confidence"].map(id => elements[id].value));
}

function updateTrafficPolicyControls() {
  setEnabled("traffic-policy-stage", !trafficPolicyPending);
  setEnabled("traffic-policy-apply", !trafficPolicyPending && !trafficFormDirty && Boolean(trafficPolicyReadback?.staged),
    trafficPolicyPending ? "" : trafficFormDirty ? "입력 변경: 검토본을 다시 저장하세요" : "저장된 검토본 없음");
  const signalAvailable = trafficPolicyReadback?.simulation_signal?.available === true;
  document.querySelectorAll("[data-simulation-signal]").forEach((button) => {
    setOff(button, trafficPolicyPending || !signalAvailable, trafficPolicyPending ? "" : "시뮬레이션 신호 없음");
    button.dataset.active = String(
      button.dataset.simulationSignal === trafficPolicyReadback?.simulation_signal?.colour,
    );
  });
}

export function renderTrafficPolicy(readback = {}) {
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
export function showView(view) {
  const operate = view !== "inspect";
  elements["view-operate-panel"].hidden = !operate;
  elements["view-inspect-panel"].hidden = operate;
  elements["view-operate"].setAttribute("aria-pressed", String(operate));
  elements["view-inspect"].setAttribute("aria-pressed", String(!operate));
  document.body.dataset.view = operate ? "operate" : "inspect";
}

export function renderTriage() {
  const node = elements["triage"];
  if (!node) return;
  const { headline, context, seenAt } = triage({
    state: session.robotState,
    inventory: session.inventory,
    safetySource: session.safetySource,
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

// The hero and the triage banner read the same server evidence, so they cannot
// disagree: READY only while the safety channel is fresh. A channel with no
// source at all says why instead of claiming a live circuit. Whether hardware
// runs comes from live evidence (`capabilities.runtime`, v1.21), not from the
// configured mode string: rosy-io is started by hand under `core` (D-192).
export function safetyHero(state, runtimeMode, source, runtime) {
  if (state?.safety?.estop) {
    return { tone: "danger", label: "STOPPED", source: estopFault(source).title };
  }
  const judged = evidenceOf(state, "safety");
  if (judged === "fresh") return { tone: "safe", label: "READY", source: "주행 회로 정상" };
  if (judged === "unavailable") {
    const hardware = runtime?.hardware ?? (runtimeMode === "core" ? "off" : "on");
    if (hardware === "off") return { tone: "unverified", label: "HW OFF", source: CORE_ONLY_TEXT };
    if (hardware === "silent") {
      return { tone: "unverified", label: "HW SILENT", source: "하드웨어 런타임 신호 끊김" };
    }
    if (runtime?.drive === "disabled") {
      return { tone: "unverified", label: "NO DRIVE", source: DRIVE_DISABLED_TEXT };
    }
    return { tone: "unverified", label: "NO SOURCE", source: "안전 회로 출처 없음" };
  }
  return {
    tone: "unverified",
    label: "UNVERIFIED",
    source: judged === "delayed" ? `안전 회로 ${EVIDENCE_LABEL.delayed}` : "안전 회로 수신 끊김",
  };
}

export function renderSafetyHero() {
  if (!session.robotState) return;
  const hero = safetyHero(
    session.robotState, session.runtimeMode, session.safetySource, session.capabilities?.runtime,
  );
  elements["safety-indicator"].className = `hero-safety ${hero.tone}`;
  setText("safety-label", hero.label);
  setText("safety-source", hero.source);
}

/* 편대 역할 — 대형에 속해 있을 때만 계기 셋에 네 번째 칸으로 나타난다.
   role은 스냅샷의 swarm.role(leader/follower/none)이고 formation은 대형 이름.
   none이면 칸 전체가 사라진다: 편대 밖 로봇에게 이 칸은 잡음이다. */
export function renderFormationHero(swarm = {}) {
  const cell = elements["hero-formation"];
  const role = swarm?.role;
  if (!cell) return;
  const known = role === "leader" || role === "follower";
  cell.hidden = !known;
  if (!known) return;
  setText("robot-role", role === "leader" ? "리더" : "팔로워");
  setText("robot-formation", swarm?.formation || "");
}

export function renderCapabilityPanels(capabilities) {
  session.capabilities = capabilities;
  renderSafetyHero();
  const slamOn = capabilities?.slam === true;
  const slamChip = elements["slam-capability"];
  if (slamChip) {
    setTagState(slamChip, "mode", slamOn ? "AVAILABLE" : "HOLD");
    slamChip.textContent = slamOn ? "AVAILABLE" : "HOLD";
  }
  setEnabled("slam-start", slamOn, "SLAM을 쓸 수 없음");
  setEnabled("slam-stop", slamOn, "SLAM을 쓸 수 없음");
  setEnabled("slam-save", slamOn, "SLAM을 쓸 수 없음");
}

export function renderInventory(inventory) {
  session.inventory = inventory;
  const rows = (inventory?.descriptors || []).filter(
    (row) => row.state && row.state !== "not_provided",
  );
  elements["capability-list"].replaceChildren();
  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "capability-item";
    item.dataset.state = row.state;
    if (CONFIGURED_REASONS[row.reason]) item.dataset.cause = "runtime";
    const label = document.createElement("span");
    label.textContent = knownWord(CAPABILITY_LABEL, row.id);
    label.title = row.id;
    const state = document.createElement("b");
    state.textContent = knownWord(PRESENTATION_LABEL, row.state);
    state.title = row.state;
    item.append(label, state);
    if (row.reason) {
      const reason = document.createElement("small");
      // Every reason, most basic first (v1.21): a robot without a drive stays
      // without one after the e-stop is released.
      const reasons = row.reasons?.length ? row.reasons : [row.reason];
      reason.textContent = reasons.map(reasonText).join(" · ");
      item.append(reason);
    }
    elements["capability-list"].append(item);
  });
  const usable = rows.filter((row) => row.state === "available" || row.state === "constrained");
  setText("capability-count", `${usable.length} / ${rows.length}`);
  renderTriage();
}

// D-262: pushNetworkSample/renderSparkline/renderRosGraph/renderRosNetwork는
// ros-network.js로 옮겼다. 여기서는 rosNetwork.render(runtime) 한 줄만 부른다.
// D-262: ROS 통신 격리·연결 지도는 ros-network.js 팩토리가 그린다.
// renderRuntime 이 유일한 소비자다(D-362 P1 이동).
const rosNetwork = createRosNetwork({
  elements,
  setText,
  metricNumber,
  rate,
  svgText,
  history: session.networkHistory,
});

export function renderRuntime(runtime) {
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

export function renderEvents(payload) {
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
    // D-396: 심각도 색 — 위험은 채움, 주의는 텍스트 색, info 는 뮤트.
    if (event.severity === "critical" || event.severity === "error") {
      severity.dataset.severity = "crit";
    } else if (event.severity === "warning") {
      severity.dataset.severity = "warn";
    }
    row.append(time, type, severity);
    elements["event-list"].append(row);
  });
}

// 교통 정책 패널의 입력·단계·적용·SIM 신호 바인딩 — 상태와 렌더가 한 곳에 산다.
[
  "traffic-policy-mode",
  "traffic-policy-revision-input",
  "traffic-approach-distance",
  "traffic-stop-distance",
  "traffic-stop-dwell",
  "traffic-min-confidence",
].forEach((id) => elements[id]?.addEventListener("input", () => {
  trafficFormDirty = true;
  updateTrafficPolicyControls();
}));

elements["traffic-policy-stage"]?.addEventListener("click", async () => {
  if (trafficPolicyPending) return;
  const owner = actionHooks.captureLifetime();
  if (!owner.current()) return;
  trafficOwner = owner;
  const clear = () => { if (trafficOwner === owner) { trafficOwner = null; trafficPending(false); } };
  owner.signal.addEventListener("abort", clear, {once: true});
  trafficPending(true);
  const inputSnapshot = trafficInputSnapshot();
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
      signal: owner.signal,
    });
    if (trafficOwner !== owner || !owner.current()) return;
    trafficFormDirty = inputSnapshot !== trafficInputSnapshot();
    renderTrafficPolicy(readback);
    setText("traffic-policy-message", `검토본 저장됨: ${body.policy_revision}`);
  } catch (error) {
    if (trafficOwner === owner && owner.current()) setText("traffic-policy-message", `정책 검증 실패: ${error.message}`);
  } finally {
    owner.signal.removeEventListener("abort", clear); clear();
  }
});

elements["traffic-policy-apply"]?.addEventListener("click", async () => {
  const staged = JSON.stringify(trafficPolicyReadback?.staged);
  const snapshot = trafficInputSnapshot();
  await actionHooks.runConfirmed("로봇이 완전히 정지했습니까? 검토 중인 교통 정책을 적용합니다.", elements["traffic-policy-apply"],
    () => !trafficPolicyPending && !trafficFormDirty && Boolean(trafficPolicyReadback?.staged) && staged === JSON.stringify(trafficPolicyReadback.staged) && snapshot === trafficInputSnapshot(), async (active, owner) => {
    const readback = await api("/api/v1/traffic/policy/apply", {
      method: "POST", signal: owner.signal,
    });
    if (!active()) return;
    renderTrafficPolicy(readback);
    setText("traffic-policy-message", "정지 상태에서 정책을 적용했습니다.");
  }, error => setText("traffic-policy-message", `정책 적용 실패: ${error.message}`), trafficPending);
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
