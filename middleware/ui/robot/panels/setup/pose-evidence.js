import { HeadlessState, EVIDENCE_LABEL, evidenceAgeText } from "/common/core_ui_logic.js";

export function poseUnavailableReason(state) {
  const evidence = new HeadlessState(state).evidenceOf("pose");
  if (evidence === "disconnected") return `위치 ${EVIDENCE_LABEL.disconnected}`;
  if (evidence === "unavailable") return `위치 ${EVIDENCE_LABEL.unavailable}`;
  const stamp = Date.parse(state?.evidence?.pose?.received_at || "");
  const age = Number.isFinite(stamp)
    ? Math.max(0, Math.floor((Date.now() - stamp) / 1000))
    : null;
  // D-398 — 나이 뒤처리도 규격 규칙을 따른다: `위치 지연 · N초 전`.
  return `위치 ${EVIDENCE_LABEL.delayed}${evidenceAgeText(age)}`;
}
