/**
 * Framework-free access to server-judged evidence states (D-999, D-157).
 *
 * The server owns freshness thresholds. This adapter deliberately contains no
 * clock math; every surface consumes the same per-channel evidence enum while
 * retaining its own visual grammar.
 */

const EVIDENCE_STATES = new Set(["fresh", "delayed", "disconnected", "unavailable"]);

export class HeadlessState {
  constructor(statePayload) {
    this.state = statePayload || {};
  }

  evidenceOf(channel) {
    const judged = this.state.evidence?.[channel]?.evidence;
    return EVIDENCE_STATES.has(judged) ? judged : "disconnected";
  }

  isFresh(channel) {
    return this.evidenceOf(channel) === "fresh";
  }

  isDelayed(channel) {
    return this.evidenceOf(channel) === "delayed";
  }

  isDisconnected(channel) {
    return this.evidenceOf(channel) === "disconnected";
  }

  getValue(fieldPath, evidenceField, fallback = "?") {
    if (!this.isFresh(evidenceField)) return fallback;

    let value = this.state;
    for (const key of fieldPath.split(".")) {
      if (value === undefined || value === null) return fallback;
      value = value[key];
    }
    return value !== undefined && value !== null ? value : fallback;
  }
}

// D-359 US-009 — operator words for CORE protocol enums (API Ref §4, schemas.py).
// One map for the robot dashboard and the Fleet console; both load this file
// from /common/ without a bundler. The enum itself stays in `title` only.
export const MODE_LABEL = Object.freeze({
  IDLE: "대기",
  MANUAL: "수동",
  NAVIGATION: "내비게이션",
  DOCKING: "도킹",
  EMERGENCY: "비상 정지",
});

export const ROLE_LABEL = Object.freeze({
  viewer: "관찰자", operator: "운용자", administrator: "관리자",
});

// Traffic supervision enums (traffic_policy/manager.py); permission stays on CORE.
export const TRAFFIC_MODE_LABEL = Object.freeze({
  DISABLED: "사용 안 함", MONITOR_ONLY: "관찰만", ENFORCED: "정책 준수",
});
export const TRAFFIC_STATE_LABEL = Object.freeze({
  DISABLED: "사용 안 함", HOLD: "대기", FOLLOW: "주행", APPROACH: "정지선 접근",
  STOP_REQUIRED: "정지 필요", WAIT_SIGNAL: "신호 대기", PROCEED: "진입 가능",
});
export const TRAFFIC_REASON_LABEL = Object.freeze({
  policy_disabled: "정책 사용 안 함", no_road_evidence: "도로 정보 없음",
  road_evidence_stale: "도로 정보 지연", map_mismatch: "지도 불일치",
  scene_mismatch: "도로 장면 불일치", signal_conflict: "신호 충돌",
  clear_road: "도로 통과 가능", stop_line_low_confidence: "정지선 신뢰도 부족",
  stop_distance_unavailable: "정지선 거리 정보 없음", stop_line_far: "정지선 멀리 있음",
  stop_line_approach: "정지선 접근 중", stop_dwell: "정지 대기 시간 확인",
  unsignalized_proceed: "무신호 교차로 진입 가능", signal_unexpected: "예상하지 않은 신호",
  signal_source_conflict: "신호원 정보 충돌", signal_low_confidence: "신호 신뢰도 부족",
  signal_green: "초록 신호", signal_red: "빨강 신호", signal_yellow: "노랑 신호",
  signal_dark: "신호 꺼짐", signal_unknown: "신호 정보 없음",
});
export const TRAFFIC_SIGNAL_LABEL = Object.freeze({
  RED: "빨강", YELLOW: "노랑", GREEN: "초록", DARK: "꺼짐", UNKNOWN: "정보 없음", CONFLICT: "충돌",
});
export const TRAFFIC_SOURCE_LABEL = Object.freeze({camera: "카메라", fused: "통합 신호"});
export const TRAFFIC_RULE_LABEL = Object.freeze({
  signal_controlled: "신호 제어", stop_and_go: "무신호: 정지 후 진입",
});

export const NAVIGATION_LABEL = Object.freeze({
  IDLE: "대기",
  PLANNING: "경로 계획 중",
  NAVIGATING: "주행 중",
  ARRIVED: "도착",
  CANCELED: "취소됨",
  FAILED: "실패",
  BLOCKED: "막힘",
});

export const DOCK_STATE_LABEL = Object.freeze({
  UNDOCKED: "도크 밖",
  DOCKING: "도킹 중",
  DOCKED: "도크 접촉 · 충전 미확인",
  CHARGING: "충전 중",
  UNDOCKING: "도크에서 나오는 중",
  DOCK_FAILED: "도킹 실패",
});

// PowerMode on StateSnapshot.power. The enum stays in title. IDLE here is the
// dimmed power mode, so the word is not the robot-mode word for IDLE ("대기").
export const POWER_MODE_LABEL = Object.freeze({
  ACTIVE: "상시",
  IDLE: "유휴",
  STANDBY: "절전",
});

// BatteryLevel. ok stays off the attention queue. The other three are the
// existing triage names, used as the queue state.
export const BATTERY_LEVEL_LABEL = Object.freeze({
  ok: "정상",
  warning: "배터리 부족",
  critical: "배터리 위험",
  deep: "배터리 고갈",
});

// Host Agent network modes (API Ref host/network). The enum stays in the request body.
export const NETWORK_MODE_LABEL = Object.freeze({
  SITE_STA: "사업장 Wi-Fi",
  RELAY_AP_STA: "릴레이(AP+STA)",
});

// D-398 — operator words for the four evidence states (DESIGN.md 운용자 말).
// 증거 상태의 한국어는 이 표 하나다. 표면이 문장을 지을 때 주어(릴레이·위치)를
// 앞에 붙이고 나이 뒤처리는 evidenceAgeText()를 쓴다. 노드 순수 시험이 돌아야 해서
// /common import를 못 하는 fleet 순수 계산 모듈(site-layer.js)만 예외로 같은 문구를
// 로컬에 두고 이 표를 참조한다.
export const HEALTH_LABEL = Object.freeze({OK: "정상", WARNING: "주의", ERROR: "오류", UNKNOWN: "확인 전"});
export const SEVERITY_LABEL = Object.freeze({info: "정보", warning: "주의", error: "오류", critical: "심각"});
export const SAFETY_POLICY_LABEL = Object.freeze({STOP: "정지", HOLD: "대기", RETURN_HOME: "복귀", CONTINUE: "계속"});
export const TOKEN_SOURCE_LABEL = Object.freeze({card: "카드", manual: "수동", "pair-physical": "로봇 화면 코드", "pair-admin": "관리자 등록 코드", legacy: "설정 파일"});
export const LINE_STATE_LABEL = Object.freeze({
  OFF: "꺼짐", mode_off: "추종 꺼짐", WAITING: "선 찾는 중", TRACKING: "추종 중", LOST: "선 놓침",
  HOLD: "멈춤", RECOVERING: "복구 중",
});
// line_follow.mode (CORE /line-follow). "차선 추종" is the one operator word for it on every surface.
export const LINE_FOLLOW_MODE_LABEL = Object.freeze({
  CAMERA_LINE: "카메라 차선 추종", IR_LINE: "IR 차선 추종", OFF: "차선 추종 꺼짐",
});

// D-20 formation (Fleet swarm session). The enum stays in title and in the request body.
export const FORMATION_STATE_LABEL = Object.freeze({
  IDLE: "대기", ARMING: "시작 중", RUNNING: "진행 중", HOLDING: "멈춤 · 재개 대기", STOPPED: "해제됨",
});
export const FORMATION_SHAPE_LABEL = Object.freeze({
  COLUMN: "종대 · 한 줄로 뒤따름", LINE: "횡대 · 옆으로 나란히", V: "V자", GRID: "격자", CIRCLE: "원형",
  FOLLOW: "한 대 뒤따름 · 팔로워 1대", TRAIL: "자취 따라가기 · 리더가 간 길로",
});

export const EVIDENCE_LABEL = Object.freeze({
  fresh: "최신",
  delayed: "지연",
  disconnected: "연결 끊김",
  unavailable: "정보 없음",
});

/** Canonical age suffix for a delayed value: ` · N초 전`.
 * `seconds` is a server-given age (received_at/age_ms/age_s) — this only formats
 * it; judging staleness is the server's job (HeadlessState, no clock math). */
export function evidenceAgeText(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const age = Number.isInteger(seconds) ? seconds : Math.round(seconds * 10) / 10;
  return ` · ${age}초 전`;
}

/** Korean word for an enum value; an unknown value is shown as received, never hidden. */
export function enumLabel(labels, value, fallback = "—") {
  if (value === undefined || value === null || value === "") return fallback;
  return Object.hasOwn(labels, value) ? labels[value] : String(value);
}

// SAFE_STOP is a DeviceState string on state.mode, not a RobotMode member.
const MODE_ALIAS = Object.freeze({ SAFE_STOP: "안전 정지", LINE_FOLLOW: "차선 추종" });

export function operatorModeLabel(value, fallback = "—") {
  if (Object.hasOwn(MODE_ALIAS, value)) return MODE_ALIAS[value];
  return enumLabel(MODE_LABEL, value, fallback);
}
// Camera preview decision chain, rows 3-5 (CORE gates, stuck, Fleet/AI) from GET /line-follow; rows 1-2
// (perception, steering) are drawn into the robot's preview image from line/keep_debug. Levels are
// ui-status states: ready = passing, warning = limiting, error = stopping. Only reported fields are shown.
const PERCEPTION_REASONS = new Set(["no_observation", "stale", "observation_stale", "perception_stale", "low_confidence",
  "camera_observation_stale", "camera_line_not_visible", "camera_reselection_required", "reselection_required"]);
// Display vocabulary only; unknown protocol values remain in the camera's diagnostic readback.
const LINE_DECISION_LABEL = Object.freeze({
  ...LINE_STATE_LABEL, ...TRAFFIC_REASON_LABEL,
  tracking: "차선 추종", following: "차선 추종", lane_departure: "차선 이탈", obstacle_ahead: "전방 장애물",
  pose_stale: "위치 정보 지연", no_observation: "인식 정보 없음", stale: "정보 지연",
  observation_stale: "인식 정보 지연", perception_stale: "인식 정보 지연", low_confidence: "인식 신뢰도 부족",
  camera_observation_stale: "카메라 인식 정보 지연", camera_line_not_visible: "카메라에서 차선 확인 불가",
  camera_reselection_required: "카메라 차선 다시 선택 필요", reselection_required: "차선 다시 선택 필요",
  line_not_visible: "차선 확인 불가", invalid_observation: "인식 정보 유효하지 않음",
  motion_unconfirmed: "실제 움직임 미확인", driver_released: "주행 제어 해제", angular_limit_zero: "회전 허용량 없음",
  limit_level_too_low: "주행 허용량 부족", obstacle_sensor_stale: "장애물 센서 정보 지연", lane_guard_stale: "차로 안전 정보 지연",
  nominal_ground_requires_driver: "바닥 기준 확인을 위한 운전자 필요", low_light: "조도 부족", overexposed: "과노출",
  fleet_wrong_way: "관제 역방향 감지", fleet_off_lane: "관제 차로 이탈 감지", fleet_off_map: "관제 지도 이탈 감지",
  lane_return_fleet_required: "차로 복귀를 위한 관제 판단 필요", stuck_back_off: "막힘 복구 후진",
  stuck_yield: "막힘 복구 양보", stuck_realign: "막힘 복구 방향 정렬", stuck_asking: "막힘 해소 요청 중",
  stuck_waiting_console: "막힘 해소 관제 응답 대기", no_motion: "움직임 없음",
  lane_lost: "차선 놓침", crosswalk_blocked: "횡단보도 막힘", no_progress: "전진하지 못함", dithering: "방향 흔들림",
  ASKING: "응답 요청 중", WAITING_CONSOLE: "관제 응답 대기", BACKING: "후진 중", SETTLING: "정지 후 안정 대기",
  TURNING: "양보 회전 중", CRAWLING: "양보 서행 중", YIELDED: "양보 후 대기",
  REALIGNING: "방향 정렬 중", REALIGN_SETTLING: "방향 정렬 후 안정 대기",
  WAIT: "대기", RESUME: "재개", BACK_AND_RETRY: "후진 후 재시도", MANUAL: "수동 조작", ABORT: "중단",
  YIELD: "양보", REALIGN: "방향 정렬",
  stuck_backing: "막힘 복구 후진 중", stuck_settling: "막힘 복구 정지 후 안정 대기",
  stuck_turning: "막힘 복구 양보 회전 중", stuck_crawling: "막힘 복구 양보 서행 중", stuck_yielded: "막힘 복구 양보 후 대기",
  stuck_realigning: "막힘 복구 방향 정렬 중", stuck_realign_settling: "막힘 복구 방향 정렬 후 안정 대기",
  armed: "확인 준비", approaching: "접근 중", looking: "주변 확인 중", waiting: "대기 중", crossing: "건너는 중",
  inside: "구역 안", ahead: "전방에 있음", unknown: "확인 전", clear: "통과 가능",
  person_present: "보행자 있음", look_unknown: "주변 확인 불가", sensor_stale: "센서 정보 지연",
  zone_lost: "구역 정보 놓침", not_watched: "관측하지 않음", zone_unplaced: "구역 위치 미설정",
  FREE: "통행 가능", HOLDING: "통행 대기", EXPIRED: "기한 만료", NONE: "없음", granted: "허용",
  authority_end: "허용 구간 끝", authority_odom_stale: "주행 거리 정보 지연",
  ON_LANE: "차로 안", OFF_LANE: "차로 밖", WRONG_WAY: "역방향", OFF_MAP: "지도 밖",
  green: "초록", yellow: "노랑", red: "빨강",
});
export function lineDecisionChain(status) {
  const s = status || {}; const stuck = s.stuck; const reason = String(s.reason || "");
  const word = (value, fallback = "확인 전") => value ? LINE_DECISION_LABEL[value] || "해석되지 않은 사유 · 진단 확인 필요" : fallback;
  const diagnostic = JSON.stringify(s, null, 2);
  const fixed = (v, n = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(n) : "-");
  const gates = [`${word(s.state || "OFF")}${reason ? ` · ${word(reason)}` : ""}`, `전진 속도 ${fixed(s.linear)} m/s · 회전 속도 ${fixed(s.angular)} rad/s`];
  if (s.body_gap_m != null || s.stop_gap_m != null) gates.push(`차체 여유 거리 ${fixed(s.body_gap_m)}/정지 기준 ${fixed(s.stop_gap_m)} m`);
  if (s.crosswalk) gates.push(`횡단보도 ${word(s.crosswalk.state)}${s.crosswalk.reason ? ` · ${word(s.crosswalk.reason)}` : ""}`);
  if (s.authority) gates.push(`통행권 ${word(s.authority.state)}${s.authority.reason ? ` · ${word(s.authority.reason)}` : ""}`);
  const asking = stuck && ["ASKING", "WAITING_CONSOLE"].includes(stuck.phase);
  const fleet = [stuck?.last_answer ? `최근 응답 ${word(stuck.last_answer)}` : "막힘 해소 응답 없음",
    s.lane_cue ? `차로 정보 ${word(s.lane_cue.state)}` : "차로 정보 수신 없음", "판단 방식 수신 없음"];
  if (s.advice?.signal) fleet.push(`신호 ${word(s.advice.signal.lamp)}`);
  const fleetHold = reason.startsWith("fleet_") || reason === "lane_return_fleet_required";
  const rows = [
    {layer: "3 로봇 안전 확인", text: gates.join(" · "),
      level: s.state === "TRACKING" ? "ready" : s.state === "RECOVERING" ? "warning" : "error"},
    {layer: "4 막힘", level: !stuck ? "ready" : asking ? "error" : "warning",
      text: !stuck ? "없음" : `${word(stuck.cause)}${stuck.detail ? `/${word(stuck.detail)}` : ""} · ${word(stuck.phase)} · ${fixed(stuck.held_s, 0)}초`},
    {layer: "5 관제 판단", text: fleet.join(" · "),
      level: fleetHold ? "error" : stuck?.last_answer === "WAIT" || ["OFF_LANE", "WRONG_WAY", "OFF_MAP"].includes(s.lane_cue?.state) ? "warning" : "ready"},
  ];
  if (s.state === "OFF" || !s.state) return {headline: {level: "unavailable", text: "차선 추종 꺼짐"}, rows, diagnostic};
  if (s.state === "TRACKING") return {headline: {level: stuck ? "warning" : "ready", text: stuck ? `주행 상태 확인 필요 · 막힘 미해소: ${word(stuck.cause)}` : "주행 중 · 차선 추종"}, rows, diagnostic};
  const layer = PERCEPTION_REASONS.has(reason) ? "1–2 인식·조향 (카메라 영상)" : fleetHold ? "5 관제 판단"
    : reason.startsWith("stuck_") ? "4 막힘" : "3 로봇 안전 확인";
  const context = [stuck ? `막힘 ${fixed(stuck.held_s, 0)}초` : "", stuck?.last_answer ? `관제 ${word(stuck.last_answer)}` : ""].filter(Boolean);
  return {headline: {level: s.state === "RECOVERING" ? "warning" : "error",
    text: `${s.state === "RECOVERING" ? "복구 중" : "정지 사유"}: ${layer} - ${word(reason)}${context.length ? ` (${context.join(", ")})` : ""}`}, rows, diagnostic};
}
