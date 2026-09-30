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

/** Korean word for an enum value; an unknown value is shown as received, never hidden. */
export function enumLabel(labels, value, fallback = "—") {
  if (value === undefined || value === null || value === "") return fallback;
  return Object.hasOwn(labels, value) ? labels[value] : String(value);
}
