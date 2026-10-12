// 지도 위 기기 보기. Fleet 이 이미 모은 상태와, 막힘 큐가 받아 둔 전방 사진만 보여 준다.
// 로봇 API 를 부르지 않고, 천장 원본은 camera-backdrop 이 둔 #map-birdseye 한 장이다.

import {
  HEALTH_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL, enumLabel,
} from "/common/core_ui_logic.js";
import { CAUSE_LABEL, PHASE_LABEL } from "./line-stuck.js";

const BOUNDARY_LABEL = Object.freeze({
  unknown: "관측 불가", baseline: "기준 설정", confirming: "변화 확인 중", confirmed: "변화 확인됨",
});
const RANGE_LABEL = Object.freeze({ lidar: "라이다", ultrasonic: "초음파" });
const TRAFFIC_MODE_LABEL = Object.freeze({
  MONITOR_ONLY: "교통 관찰", ENFORCED: "교통 적용", ADVISORY: "교통 참고",
});
const FACT_KIND_LABEL = Object.freeze({
  wait_cycle_confirmed: "대기 주기 확인",
  wait_cycle_stale_input: "대기 입력 오래됨",
  waiting_but_moving: "대기 중 이동",
  livelock: "서로 막힘",
  stalled: "진행 멈춤",
  unknown_occupancy_long: "점유 오래 불명",
  lane_obs_vs_range: "차선·거리 불일치",
  lane_conf_collapse: "차선 확신 낮음",
  shadow_active_drift: "그림자 판단 어긋남",
  pose_vs_paint: "위치·차선 불일치",
  pose_sources_disagree: "위치 출처 불일치",
  obstacle_identity: "장애물 정체",
  rear_blocked: "뒤 막힘",
  path_blocked_by_robot: "경로에 로봇",
  incident_context: "상황 맥락",
  trip_route_check: "운행 경로 확인",
});
const NUMBER_FIELDS = Object.freeze([
  ["error", "오차"],
  ["confidence", "확신"],
  ["age_s", "나이 s"],
  ["linear", "전진"],
  ["angular", "회전"],
  ["clearance_m", "전방 m"],
  ["body_gap_m", "몸 m"],
  ["stop_gap_m", "정지 간격 m"],
]);

function tag(text, status = "neutral", title = "") {
  return title ? { text, status, title } : { text, status };
}

function finiteText(value) {
  if (typeof value === "boolean" || typeof value !== "number" || !Number.isFinite(value)) return null;
  return String(Math.round(value * 1000) / 1000);
}

function cameraTag(capabilities) {
  const camera = capabilities?.line_follow?.camera;
  if (!camera || typeof camera !== "object" || typeof camera.available !== "boolean") {
    return tag("전방 미확인");
  }
  if (!camera.available) return tag("전방 없음", "warn");
  const title = [camera.source, Number.isFinite(camera.age_ms) ? `${Math.round(camera.age_ms)} ms` : ""]
    .filter(Boolean).join(" · ");
  return tag("전방 카메라", "neutral", title);
}

function lidarTag(power) {
  if (!power || typeof power !== "object") return null;
  if (power.lidar_ready === true) return tag("라이다 준비");
  if (power.lidar_spinning === true) return tag("라이다 기동", "warn");
  if (power.lidar_ready === false || power.lidar_spinning === false) return tag("라이다 정지", "warn");
  return null;
}

function lineTags(lane) {
  if (!lane || lane.mode === "OFF" || lane.mode == null || lane.mode === "") return [];
  const lost = lane.state === "LOST" || lane.state === "HOLD";
  const tags = [tag(
    `${enumLabel(LINE_FOLLOW_MODE_LABEL, lane.mode)} · ${enumLabel(LINE_STATE_LABEL, lane.state)}`,
    lost ? "warn" : "neutral",
    lane.reason ? String(lane.reason) : "",
  )];
  const source = lane.clearance_source ? enumLabel(RANGE_LABEL, lane.clearance_source, String(lane.clearance_source)) : "";
  const front = finiteText(lane.clearance_m);
  const body = finiteText(lane.body_gap_m);
  if (front != null) tags.push(tag(`전방 ${front} m`, "neutral", source));
  if (body != null) tags.push(tag(`몸 ${body} m`, "neutral", source));
  return tags;
}

function trafficTags(policy) {
  if (!policy || typeof policy !== "object" || !policy.mode || policy.mode === "DISABLED") return [];
  const tags = [tag(enumLabel(TRAFFIC_MODE_LABEL, policy.mode), policy.mode === "ENFORCED" ? "active" : "neutral", String(policy.mode))];
  if (policy.stop_line_visible === true) tags.push(tag("정지선", "warn"));
  if (policy.crosswalk_visible === true) tags.push(tag("횡단보도", "warn"));
  if (policy.signal_colour) tags.push(tag(`신호 ${policy.signal_colour}`, policy.signal_conflict === true ? "crit" : "neutral"));
  return tags;
}

function diagnosticTags(summary) {
  if (!summary || typeof summary !== "object") return [];
  return Object.entries(summary)
    .filter(([, status]) => status === "WARNING" || status === "ERROR" || status === "UNKNOWN")
    .map(([name, status]) => tag(`${name} ${enumLabel(HEALTH_LABEL, status)}`, status === "ERROR" ? "crit" : "warn", String(status)));
}

function stuckTags(stuck) {
  if (!stuck || typeof stuck !== "object") return [];
  const tags = [
    tag(enumLabel(CAUSE_LABEL, stuck.cause, "원인 미확인"), "crit"),
    tag(enumLabel(PHASE_LABEL, stuck.phase, "단계 미확인"),
      stuck.phase === "BACKING" || stuck.phase === "SETTLING" ? "warn" : "neutral"),
  ];
  const boundary = stuck.inquiry?.lane_boundary;
  if (boundary && typeof boundary === "object") {
    tags.push(tag(`차선 경계 ${enumLabel(BOUNDARY_LABEL, boundary.state, "관측 불가")}`,
      boundary.state === "confirmed" ? "warn" : "neutral"));
  }
  const ai = stuck.ai;
  if (ai && typeof ai === "object") {
    const busy = ai.state === "present" && ai.owner_mode === "owner_busy";
    const present = ai.state === "present" && !busy;
    tags.push(tag(present ? "AI 판단 있음" : "AI 판단 없음", present ? "active" : "neutral", busy ? "소유자 사용 중" : ""));
  }
  for (const fact of stuck.ai_facts || []) {
    if (!fact || typeof fact !== "object" || !fact.kind) continue;
    const confidence = Number.isFinite(fact.confidence) ? `${Math.round(fact.confidence * 100)}%` : "";
    tags.push(tag(enumLabel(FACT_KIND_LABEL, fact.kind), "neutral", [confidence, fact.source].filter(Boolean).join(" · ")));
  }
  return tags;
}

function numberRows(lane) {
  if (!lane || typeof lane !== "object") return [];
  const rows = [];
  for (const [key, label] of NUMBER_FIELDS) {
    const value = finiteText(lane[key]);
    if (value != null) rows.push({ label, value });
  }
  if (typeof lane.clearance_source === "string" && lane.clearance_source) {
    rows.push({ label: "거리 출처", value: enumLabel(RANGE_LABEL, lane.clearance_source, lane.clearance_source) });
  }
  return rows;
}

/** The robot the map is already about: the open card, else the armed goal, else the only robot. */
export function shownRobot(view) {
  const robots = Array.isArray(view?.robots) ? view.robots.filter((robot) => robot && robot.robot_id) : [];
  const wanted = view?.focusRobot || view?.selected || "";
  const named = wanted ? robots.find((robot) => robot.robot_id === wanted) : null;
  if (named) return named;
  return robots.length === 1 ? robots[0] : null;
}

/** Tags and numeric rows already present on one Fleet robot. Display only. */
export function watchFacts(robot, { unavailable = false, name = "" } = {}) {
  if (unavailable) return { tags: [tag("상태 확인 불가", "warn")], numbers: [] };
  if (!robot) return { tags: [tag("로봇 미선택")], numbers: [] };
  const state = robot.state && typeof robot.state === "object" ? robot.state : null;
  const tags = [tag(name || robot.robot_id, "neutral", name && name !== robot.robot_id ? robot.robot_id : "")];
  if (!state) tags.push(tag("상태 확인 불가", "warn"));
  tags.push(cameraTag(robot.capabilities));
  const lidar = lidarTag(state?.power);
  if (lidar) tags.push(lidar);
  tags.push(...lineTags(state?.line_follow), ...trafficTags(state?.traffic_policy),
    ...diagnosticTags(state?.diagnostics_summary), ...stuckTags(robot.line_stuck));
  return { tags: tags.filter(Boolean), numbers: numberRows(state?.line_follow) };
}

export function createDeviceWatch({ scope, el, view }) {
  const ceiling = el("watch-ceiling");
  const stage = el("map-stage");

  function syncCeiling() {
    const frame = el("map-birdseye");
    const live = Boolean(frame && !frame.hidden);
    ceiling.setAttribute("aria-pressed", String(stage.dataset.watch !== "off"));
    ceiling.disabled = !live;
    if (live) ceiling.removeAttribute("reason");
    else ceiling.setAttribute("reason", "영상 대기");
  }

  function paintTags(items) {
    const box = el("watch-tags");
    const key = JSON.stringify(items);
    if (box.dataset.items === key) return;
    box.dataset.items = key;
    box.replaceChildren(...items.map((item) => {
      const node = document.createElement("ui-tag");
      node.setAttribute("status", item.status || "neutral");
      node.textContent = item.text;
      if (item.title) node.title = item.title;
      return node;
    }));
  }

  function paintNumbers(rows) {
    const box = el("watch-numbers");
    const readout = el("watch-readout");
    readout.hidden = rows.length === 0;
    const key = JSON.stringify(rows);
    if (box.dataset.items === key) return;
    box.dataset.items = key;
    box.replaceChildren();
    if (!rows.length) return;
    const list = document.createElement("dl");
    for (const row of rows) {
      const label = document.createElement("dt");
      label.textContent = row.label;
      const value = document.createElement("dd");
      value.textContent = row.value;
      list.append(label, value);
    }
    box.append(list);
  }

  function paintFront(robot) {
    const figure = el("watch-front");
    const image = el("watch-front-image");
    const id = robot?.robot_id || "";
    const source = id
      ? document.querySelector(`.stuck-item[data-robot-id="${CSS.escape(id)}"] .stuck-evidence img`)
      : null;
    if (!source?.getAttribute("src")) {
      image.removeAttribute("src");
      image.alt = "";
      figure.hidden = true;
      return;
    }
    if (image.getAttribute("src") !== source.getAttribute("src")) image.src = source.src;
    image.alt = source.alt || `${id} 전방`;
    figure.hidden = false;
  }

  function render() {
    const robot = shownRobot(view);
    const facts = watchFacts(robot, {
      unavailable: Boolean(view.stateUnavailable),
      name: robot ? (view.robotNames?.[robot.robot_id] || robot.robot_id) : "",
    });
    paintTags(facts.tags);
    paintNumbers(facts.numbers);
    paintFront(view.stateUnavailable ? null : robot);
    syncCeiling();
  }

  scope.listen(ceiling, "click", () => {
    stage.dataset.watch = stage.dataset.watch === "off" ? "pip" : "off";
    syncCeiling();
  });
  return { render };
}
