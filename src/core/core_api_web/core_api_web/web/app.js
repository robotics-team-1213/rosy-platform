import { createFieldMap } from "./map.js";
import { CORE_ONLY_REASON, CORE_ONLY_TEXT, triage } from "./triage.js";
import { HeadlessState } from "/common/core_ui_logic.js";
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
import { api, apiMaybe, authHeaders, isAdmin, session, setConnection } from "./client.js";
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
  fillIdentityForm(info.robot_id, name);
}

let triageSeen = {};
let lineFollowPending = false;
let trafficPolicyPending = false;
let visionPending = false;
let visionSequence = null;
let visionObjectUrl = null;
let visionTimer = null;
let visionGeneration = 0;
let visionAbortController = null;

function releaseVisionObjectUrl() {
  if (visionObjectUrl) URL.revokeObjectURL(visionObjectUrl);
  visionObjectUrl = null;
}

function renderVisionUnavailable(status = {}, message = "카메라 프레임 수신 대기") {
  const stale = status.stale === true;
  elements["vision-stage"].dataset.state = stale ? "stale" : "waiting";
  elements["vision-frame"].hidden = true;
  elements["vision-empty"].hidden = false;
  setText("vision-empty", message);
  setText("vision-status", stale ? "STALE" : "WAITING");
  setText("vision-source", status.source || "—");
  setText("vision-resolution", status.width && status.height
    ? `${status.width}×${status.height}` : "—");
  setText("vision-age", Number.isFinite(Number(status.age_ms))
    ? `${Math.round(Number(status.age_ms))} ms` : "—");
  setText("vision-captured", Number.isFinite(Number(status.captured_at))
    ? `${Number(status.captured_at).toFixed(3)} s` : "—");
}

async function refreshVisionPreview() {
  if (visionPending || !session.token) return;
  visionPending = true;
  const generation = visionGeneration;
  const controller = new AbortController();
  visionAbortController = controller;
  try {
    const status = await api("/api/v1/vision/front/status", {
      signal: controller.signal, cache: "no-store",
    });
    if (generation !== visionGeneration || !session.token) return;
    if (!status.available) {
      visionSequence = null;
      releaseVisionObjectUrl();
      renderVisionUnavailable(
        status, status.stale ? "카메라 프레임 만료 · HOLD" : "카메라 프레임 수신 대기");
      return;
    }
    if (visionSequence !== status.sequence) {
      const response = await fetch(
        `/api/v1/vision/front/frame?sequence=${encodeURIComponent(status.sequence)}`,
        {
          headers: authHeaders(), cache: "no-store", signal: controller.signal,
        },
      );
      if (response.status === 409 || response.status === 429) {
        visionSequence = null;
        releaseVisionObjectUrl();
        renderVisionUnavailable(
          status,
          response.status === 429
            ? "카메라 속도 제한 · 재동기화 대기"
            : "카메라 프레임 변경 · 재동기화 대기",
        );
        return;
      }
      if (!response.ok) throw new Error(`camera frame ${response.status}`);
      if (response.headers.get("X-Rosy-Camera-Sequence") !== String(status.sequence)) {
        return;
      }
      const nextUrl = URL.createObjectURL(await response.blob());
      const candidate = new Image();
      candidate.src = nextUrl;
      try {
        await candidate.decode();
      } catch (error) {
        URL.revokeObjectURL(nextUrl);
        throw error;
      }
      if (generation !== visionGeneration || !session.token) {
        URL.revokeObjectURL(nextUrl);
        return;
      }
      elements["vision-frame"].src = nextUrl;
      releaseVisionObjectUrl();
      visionObjectUrl = nextUrl;
      visionSequence = status.sequence;
    }
    if (generation !== visionGeneration || !session.token) return;
    setText("vision-source", status.source || "UNKNOWN");
    setText("vision-resolution", `${status.width || 0}×${status.height || 0}`);
    setText("vision-age", `${Math.round(Number(status.age_ms) || 0)} ms`);
    setText("vision-captured", Number.isFinite(Number(status.captured_at))
      ? `${Number(status.captured_at).toFixed(3)} s` : "—");
    elements["vision-frame"].hidden = false;
    elements["vision-empty"].hidden = true;
    elements["vision-stage"].dataset.state = "live";
    setText("vision-status", "LIVE");
  } catch (error) {
    if (error.name === "AbortError" || generation !== visionGeneration) return;
    visionSequence = null;
    releaseVisionObjectUrl();
    renderVisionUnavailable({}, `카메라 연결 확인 · ${error.message}`);
  } finally {
    if (visionAbortController === controller) {
      visionAbortController = null;
      visionPending = false;
    }
  }
}

function stopVisionPreview(message = "카메라 인증 대기") {
  visionGeneration += 1;
  visionAbortController?.abort();
  visionAbortController = null;
  clearInterval(visionTimer);
  visionTimer = null;
  visionPending = false;
  visionSequence = null;
  releaseVisionObjectUrl();
  renderVisionUnavailable({}, message);
}

function startVisionPreview() {
  stopVisionPreview("카메라 프레임 수신 대기");
  if (!session.token || document.hidden) return;
  refreshVisionPreview();
  visionTimer = setInterval(refreshVisionPreview, 500);
}
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
  if (session.teleopActive && !teleopEligible()) stopTeleop("운전 조건이 변경되어 정지했습니다.");
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
  renderRosNetwork(runtime);
}


function pushNetworkSample(series, value) {
  const amount = metricNumber(value);
  if (amount === null) return;
  series.push(amount);
  if (series.length > 30) series.splice(0, series.length - 30);
}

function renderSparkline(id, values) {
  const svg = elements[id];
  if (!svg) return;
  svg.replaceChildren();
  if (!values.length) return;
  const width = 120;
  const height = 36;
  const peak = Math.max(...values, 1);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => (
    `${(index * step).toFixed(2)},${(height - (value / peak) * (height - 4) - 2).toFixed(2)}`
  )).join(" ");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points);
  line.setAttribute("vector-effect", "non-scaling-stroke");
  svg.append(line);
}


function renderRosGraph(graph) {
  const svg = elements["ros-graph-map"];
  if (!svg) return;
  svg.replaceChildren();
  const nodes = (graph.nodes || []).slice(0, 12);
  const topics = (graph.topics || []).slice(0, 12);
  if (!nodes.length && !topics.length) {
    svg.append(svgText("ROS 그래프 데이터 없음", 400, 164, "graph-empty"));
    return;
  }

  const nodePositions = new Map();
  const topicPositions = new Map();
  const positionRows = (items, x) => items.map((item, index) => ({
    item,
    x,
    y: ((index + 1) * 300) / (items.length + 1) + 10,
  }));
  const nodeRows = positionRows(nodes, 150);
  const topicRows = positionRows(topics, 650);
  nodeRows.forEach(({ item, x, y }) => nodePositions.set(item.name, { x, y }));
  topicRows.forEach(({ item, x, y }) => topicPositions.set(item.name, { x, y }));

  (graph.edges || []).slice(0, 48).forEach((edge) => {
    const start = nodePositions.get(edge.source) || topicPositions.get(edge.source);
    const end = nodePositions.get(edge.target) || topicPositions.get(edge.target);
    if (!start || !end) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", start.x);
    line.setAttribute("y1", start.y);
    line.setAttribute("x2", end.x);
    line.setAttribute("y2", end.y);
    line.setAttribute("class", `graph-edge ${edge.kind}`);
    svg.append(line);
  });

  nodeRows.forEach(({ item, x, y }) => {
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    marker.setAttribute("x", x - 108);
    marker.setAttribute("y", y - 13);
    marker.setAttribute("width", 216);
    marker.setAttribute("height", 26);
    marker.setAttribute("rx", 3);
    marker.setAttribute("class", `graph-node${item.foreign ? " foreign" : ""}`);
    svg.append(marker, svgText(item.name, x, y + 4, "graph-node-label"));
  });
  topicRows.forEach(({ item, x, y }) => {
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    marker.setAttribute("cx", x);
    marker.setAttribute("cy", y);
    marker.setAttribute("r", 8);
    marker.setAttribute("class", "graph-topic");
    svg.append(marker, svgText(item.name, x - 14, y - 14, "graph-topic-label"));
  });
}

function renderRosNetwork(runtime) {
  const graph = runtime.ros || {};
  const throughput = runtime.network?.throughput || {};
  const status = graph.status || "UNAVAILABLE";
  setText("ros-graph-status", status);
  elements["ros-graph-status"]?.setAttribute("data-status", status);
  setText("ros-domain-id", graph.domain_id);
  setText("ros-namespace", graph.namespace);
  const isolationLabels = {
    localhost_only: "LOOPBACK ONLY",
    network_visible: "NETWORK VISIBLE",
    unknown: "UNKNOWN",
  };
  setText("dds-isolation", isolationLabels[graph.isolation?.mode] || "—");
  setText("dds-interface", graph.isolation?.interface ? `interface ${graph.isolation.interface}` : "인터페이스 확인 불가");
  setText("dds-rmw", graph.rmw || "—");
  setText("ros-node-count", graph.node_count);
  setText("ros-topic-count", graph.topic_count);
  setText("network-rx-rate", rate(throughput.rx_bytes_per_second));
  setText("network-tx-rate", rate(throughput.tx_bytes_per_second));

  pushNetworkSample(session.networkHistory.rx, throughput.rx_bytes_per_second);
  pushNetworkSample(session.networkHistory.tx, throughput.tx_bytes_per_second);
  renderSparkline("network-sparkline-rx", session.networkHistory.rx);
  renderSparkline("network-sparkline-tx", session.networkHistory.tx);
  renderRosGraph(graph);

  const riskList = elements["ros-risk-list"];
  if (!riskList) return;
  riskList.replaceChildren();
  const risks = graph.risks || [];
  if (status === "UNAVAILABLE") {
    const item = document.createElement("li");
    item.className = "risk-unavailable";
    item.textContent = "ROS 그래프 수집 불가 — 충돌 상태를 확인할 수 없습니다.";
    riskList.append(item);
    return;
  }
  if (!risks.length) {
    const item = document.createElement("li");
    item.className = "risk-clear";
    item.textContent = "감지된 충돌 지표 없음";
    riskList.append(item);
    return;
  }
  risks.forEach((risk) => {
    const item = document.createElement("li");
    const code = document.createElement("strong");
    const message = document.createElement("span");
    code.textContent = risk.code || "UNKNOWN";
    message.textContent = risk.message || "상세 정보 없음";
    item.append(code, message);
    riskList.append(item);
  });
}

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
    setText("teleop-message", "현재 하드웨어 프로필에서 teleop을 사용할 수 없습니다.");
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
  } else if (!session.teleopActive) {
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
  const wasActive = session.teleopActive;
  session.teleopActive = false;
  clearInterval(session.teleopTimer);
  session.teleopTimer = null;
  document.querySelectorAll("[data-teleop]").forEach((button) => button.classList.remove("active"));
  if (wasActive && session.token) {
    queueTerminalZero(immediate);
  }
  setText("teleop-message", message);
  updateTeleopControls();
}

async function transmitTeleop(linear, angular) {
  if (!session.teleopActive || session.teleopPending) return;
  const request = sendTeleop(linear, angular);
  session.teleopPending = request;
  try {
    await request;
  } catch (error) {
    if (session.teleopActive) stopTeleop(`주행 명령 실패: ${error.message}`);
  } finally {
    if (session.teleopPending === request) session.teleopPending = null;
  }
}

function startTeleop(button, event) {
  event.preventDefault();
  if (!teleopEligible() || session.teleopActive) return;
  const linear = Number(button.dataset.linear);
  const angular = Number(button.dataset.angular);
  if (!Number.isFinite(linear) || !Number.isFinite(angular)) return;

  session.teleopActive = true;
  button.classList.add("active");
  setText("teleop-message", `${button.querySelector("small")?.textContent || "주행"} 명령 전송 중…`);
  const transmit = () => transmitTeleop(linear, angular);
  transmit();
  session.teleopTimer = setInterval(transmit, session.teleopIntervalMs);
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
    empty.className = "empty-state";
    empty.textContent = "수신된 이벤트가 없습니다.";
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


// --- Device Runtime cards (WP-5) -------------------------------------------
//
// The rule these three share: when the Host Agent did not answer, say so.
// Filling the fields with em dashes would render an unreachable agent and a
// healthy device identically, and an operator reads an empty field as "fine".

function setCardUnavailable(cardId, noteId, payload) {
  const card = document.getElementById(cardId);
  if (card) card.dataset.available = "false";
  const note = document.getElementById(noteId);
  if (note) {
    const recovery = payload.recovery ? ` ${payload.recovery}` : "";
    note.textContent = `${payload.detail || "정보를 가져올 수 없습니다."}${recovery}`;
  }
}

function setChip(id, value) {
  const chip = document.getElementById(id);
  if (!chip) return;
  const mode = value || "UNKNOWN";
  chip.dataset.mode = mode;
  chip.textContent = mode === "UNKNOWN" ? "—" : mode;
}

function renderHostNetwork(payload) {
  const status = document.getElementById("host-agent-status");
  if (status) {
    status.dataset.status = payload.available ? "OK" : "UNAVAILABLE";
    status.textContent = payload.available ? "Host Agent 연결됨" : "Host Agent 없음";
  }

  if (!payload.available) {
    setChip("network-mode", "UNKNOWN");
    setCardUnavailable("network-card", "network-note", payload);
    setEnabled("network-apply", false);
    setEnabled("network-ap-off", false);
    setEnabled("network-ap-on", false);
    setEnabled("network-connect", false);
    return;
  }

  const card = document.getElementById("network-card");
  if (card) card.dataset.available = "true";

  const data = payload.data || {};
  setChip("network-mode", data.mode);
  // The SSID is displayable; a PSK never is, and the agent does not send one.
  setText("network-ssid", data.ssid || "—");
  setText("network-ap", data.ap_active === true ? "켜짐" : data.ap_active === false ? "꺼짐" : "—");
  setText("network-ipv4", data.ipv4 || "—");
  setText("network-route", data.default_route || "—");
  setText("network-dns", (data.dns || []).join(", ") || "—");
  setText("network-internet", data.internet ? "도달" : "도달 못함");
  setText("network-peer", data.peer_reachable ? "가능" : "확인 필요");

  const note = document.getElementById("network-note");
  if (note) {
    // Internet and peer reachability fail separately: a router with client
    // isolation gives you the internet and no dashboard.
    note.textContent = data.internet && !data.peer_reachable
      ? "인터넷은 되지만 같은 WLAN 단말에서 접근되지 않습니다. 공유기의 client isolation 설정을 확인하십시오."
      : (payload.detail || "");
  }
  const profile = elements["network-profile-id"];
  if (profile && document.activeElement !== profile) {
    profile.value = data.profile_id || data.mode || profile.value || "rosy-site-sta";
  }
  const ssidInput = elements["network-ssid-input"];
  if (ssidInput && document.activeElement !== ssidInput && data.ssid) {
    ssidInput.value = data.ssid;
  }
  const adminOn = isAdmin() && payload.available === true;
  setEnabled("network-apply", adminOn);
  setEnabled("network-ap-off", adminOn);
  setEnabled("network-ap-on", adminOn);
  setEnabled("network-connect", adminOn);
}

function renderHostRelease(payload) {
  if (!payload.available) {
    setChip("release-state", "UNKNOWN");
    setCardUnavailable("release-card", "release-note", payload);
    setActionsEnabled(false);
    return;
  }

  const card = document.getElementById("release-card");
  if (card) card.dataset.available = "true";

  const data = payload.data || {};
  setChip("release-state", data.state);
  setText("release-current", data.current || "—");
  setText("release-previous", data.previous || "없음");
  setText("release-staged", data.staged || "없음");
  setText("release-revision", (data.git_revision || "").slice(0, 12) || "—");
  setText(
    "release-schema",
    data.config_schema != null ? `${data.config_schema} / ${data.data_schema}` : "—",
  );
  setText("release-failure", data.last_failure || "없음");

  const note = document.getElementById("release-note");
  if (note) note.textContent = data.detail || payload.detail || "";

  // Rollback needs somewhere to go; clearing a hold needs a hold.
  const held = data.state === "RECOVERY_HOLD";
  setEnabled("release-rollback", session.role === "administrator" && Boolean(data.previous) && !held);
  setEnabled("release-clear-hold", session.role === "administrator" && held);
}

function renderCommissioning(payload) {
  setChip("commissioning-mode", payload.runtime_mode);
  const note = document.getElementById("commissioning-note");
  if (note) {
    const holds = [
      payload.motor_hold ? "MOTOR_HOLD" : null,
      payload.lidar_hold ? "LIDAR_HOLD" : null,
      payload.battery_hold ? "BATTERY_HOLD" : null,
      payload.imu_hold ? "IMU_HOLD" : null,
      payload.slam_hold ? "SLAM_HOLD" : null,
      payload.fleet_hold ? "FLEET_HOLD" : null,
    ].filter(Boolean);
    const holdText = holds.length ? `${holds.join(" · ")}. ` : "";
    note.textContent = `${holdText}${payload.detail || ""}`;
  }
}


function setActionsEnabled(enabled) {
  setEnabled("release-rollback", enabled);
  setEnabled("release-clear-hold", enabled);
}


function updateAdminControls() {
  setEnabled("limits-save", isAdmin());
  setEnabled("dock-register", isAdmin());
  setEnabled("identity-save", isAdmin());
  setEnabled("token-add", isAdmin());
  const networkCard = document.getElementById("network-card");
  const networkOn = isAdmin() && networkCard?.dataset.available === "true";
  setEnabled("network-apply", networkOn);
  setEnabled("network-ap-off", networkOn);
  setEnabled("network-ap-on", networkOn);
  setEnabled("network-connect", networkOn);
}

// The server names the caller's role on a route every role may read. Probing an
// admin-only route instead cost every viewer a 403 in the console on each load.
async function detectRole() {
  session.role = "";
  try {
    const info = await api("/api/v1/system/info");
    session.role = info?.caller_role || "";
  } catch (_error) {
    session.role = "";
  }
  updateAdminControls();
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

function connectStateSocket() {
  session.socket?.close();
  clearInterval(session.fallbackTimer);
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${scheme}://${window.location.host}/ws/state?token=${encodeURIComponent(session.token)}`;
  const socket = new WebSocket(url);
  session.socket = socket;
  socket.addEventListener("open", () => setConnection("online", "상태 스트림 연결"));
  socket.addEventListener("message", (event) => {
    try { renderRobotState(JSON.parse(event.data)); } catch (_error) { setConnection("error", "상태 해석 실패"); }
  });
  socket.addEventListener("close", () => {
    if (socket !== session.socket || !session.token) return;
    setConnection("error", "REST 폴링 전환");
    session.fallbackTimer = setInterval(() => refreshRobotState().catch(showConnectionError), 2000);
  });
}

function showConnectionError(error) {
  stopTeleop("연결 오류로 정지했습니다.");
  setConnection("error", "연결 확인 필요");
  setText("hero-message", error.message || "Rosy API에 연결할 수 없습니다.");
}

async function connect() {
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
  session.token = elements["token-input"].value.trim();
  sessionStorage.setItem("rosy.dashboard.token", session.token);
  setText("auth-message", "연결 확인 중…");
  try {
    await connect();
    setText("auth-message", "연결되었습니다.");
  } catch (error) {
    sessionStorage.removeItem("rosy.dashboard.token");
    session.token = "";
    stopVisionPreview("카메라 인증 실패");
    setText("auth-message", error.message);
    showConnectionError(error);
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
  elements["token-input"].value = session.token;
  connect().catch((error) => {
    showConnectionError(error);
    elements["auth-drawer"].classList.add("open");
  });
} else {
  elements["auth-drawer"].classList.add("open");
}
