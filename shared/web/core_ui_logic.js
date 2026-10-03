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
const MODE_ALIAS = Object.freeze({ SAFE_STOP: "안전 정지" });

export function operatorModeLabel(value, fallback = "—") {
  if (Object.hasOwn(MODE_ALIAS, value)) return MODE_ALIAS[value];
  return enumLabel(MODE_LABEL, value, fallback);
}
