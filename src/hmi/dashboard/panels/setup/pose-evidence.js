import { HeadlessState } from "/common/core_ui_logic.js";

export function poseUnavailableReason(state) {
  const evidence = new HeadlessState(state).evidenceOf("pose");
  if (evidence === "disconnected") return "위치 연결 끊김";
  if (evidence === "unavailable") return "위치 정보 없음";
  const stamp = Date.parse(state?.evidence?.pose?.received_at || "");
  const age = Number.isFinite(stamp)
    ? ` · 마지막 수신 ${Math.max(0, Math.floor((Date.now() - stamp) / 1000))}초 전`
    : " · 마지막 수신 시각 없음";
  return `위치 지연${age}`;
}
