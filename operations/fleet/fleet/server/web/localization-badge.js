// D-395 P2-6 — 로봇 카드의 위치 확정 배지. 서버가 준 row.localization(문구 포함)을
// 태그 어휘로 옮긴다: 확정은 중립, 미확정·미보고는 warn, 사람 확인 필요는 crit.
// DOM 없는 순수 함수만 둔다(node 시험 대상).

export function localizationTag(loc) {
  if (!loc) return null;
  const cls = loc.needs_human ? "crit" : loc.legacy || !loc.trusted ? "warn" : "";
  const title = loc.legacy ? "localization: null" : `${loc.state} · ${loc.pose_frame}`;
  return { text: loc.label, cls, title };
}

export function localizationUrgent(loc) {
  return Boolean(loc && loc.needs_human);
}

export function untrustedQueuedReason(who) {
  return `${who} 위치를 확인할 수 없어 대기 중 — 위치가 확정되거나 경로에서 멀어지면 자동 출발합니다`;
}

// Field check 2026-10-10: the card's "위치 0.90, 0.05" was odom and read as a map coordinate.
// The robot pose names its frame; Fleet's site map pose (D-536 guide row) is a separate line.
const SITE_POSE_STATE = { LOCALIZED: "확정", DEGRADED: "추정" };
const SITE_POSE_SOURCE = { sighting: "카메라", bridged: "odom 이음" };

/** "odom 0.90, 0.05": a row with no reported frame is odom unless the robot reports a map. */
export function robotPoseText(state, localization) {
  const pose = state?.pose;
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return "—";
  const frame = localization?.pose_frame || state.localization?.pose_frame || (state.map_id ? "map" : "odom");
  return `${frame} ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}`;
}

/** Fleet's site map pose: "지도 0.69, -0.44 · 확정·카메라", "지도 위치 모름", or null without a guide row. */
export function sitePoseText(guideRow) {
  if (!guideRow) return null;
  const pose = guideRow.pose;
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return "지도 위치 모름";
  const words = [SITE_POSE_STATE[pose.state] || pose.state, SITE_POSE_SOURCE[pose.source] || pose.source]
    .filter(Boolean).join("·");
  return `지도 ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}${words ? ` · ${words}` : ""}`;
}
