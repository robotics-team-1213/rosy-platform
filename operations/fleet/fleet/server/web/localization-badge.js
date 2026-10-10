// D-395 P2-6 — 로봇 카드의 위치 확정 배지. 서버가 준 row.localization(문구 포함)을
// 태그 어휘로 옮긴다: 확정은 중립, 미확정·미보고는 warn, 사람 확인 필요는 crit.
// DOM 없는 순수 함수만 둔다(node 시험 대상).

// Field 2026-10-10: a motor-mode robot reports no localization (legacy) while Fleet's MapPose (the
// D-536 guide row, what trips read) places it; the badge then says that, not "위치 상태 미보고".
export function localizationTag(loc, guideRow) {
  if (!loc) return null;
  const site = loc.legacy ? guideRow?.pose : null;
  if (site && SITE_POSE_STATE[site.state]) {
    return { text: `위치 ${SITE_POSE_STATE[site.state]}`, cls: site.state === "LOCALIZED" ? "" : "warn",
      title: `Fleet MapPose · ${site.state}` };
  }
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
const SITE_POSE_SOURCE = { sighting: "카메라", operator_pin: "운영자 핀", bridged: "odom 이음" };
// D-494 3 sighting lease: odom samples newer than an anchor this fresh are the anchor, not a bridge.
const FRESH_ANCHOR_S = 1.0;

function poseFrame(state, localization) {
  return localization?.pose_frame || state.localization?.pose_frame || (state.map_id ? "map" : "odom");
}

/** "odom 0.90, 0.05": a row with no reported frame is odom unless the robot reports a map. */
export function robotPoseText(state, localization) {
  const pose = state?.pose;
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return "—";
  return `${poseFrame(state, localization)} ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}`;
}

/** The robot's own pose when it is a map pose the map may draw: map frame and LOCALIZED (a pre-D-395 robot
 * with no localization block counts when it reports a map). Never odom: a manual-only robot's odom pose
 * drawn on the map put it where it was not (field check 2026-10-10). Fleet's map pose and Rosy Cam
 * tracking have their own layers (guide circle, tracking ring). */
export function robotMapPose(robot) {
  const state = robot?.state;
  const pose = state?.pose;
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y) || !Number.isFinite(pose.yaw)) return null;
  if (poseFrame(state, robot.localization) !== "map") return null;
  const loc = state.localization;
  return loc == null || loc.state === "LOCALIZED" ? pose : null;
}

/** Fleet's site map pose: "지도 0.69, -0.44 · 확정·카메라", "지도 위치 모름", or null without a guide row. */
export function sitePoseText(guideRow) {
  if (!guideRow) return null;
  const pose = guideRow.pose;
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return "지도 위치 모름";
  const source = pose.source === "bridged" && pose.anchor_source
    && Number.isFinite(pose.anchor_age_s) && pose.anchor_age_s <= FRESH_ANCHOR_S
    ? pose.anchor_source : pose.source;
  const words = [SITE_POSE_STATE[pose.state] || pose.state, SITE_POSE_SOURCE[source] || source]
    .filter(Boolean).join("·");
  return `지도 ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}${words ? ` · ${words}` : ""}`;
}

/** The card's one position chip (2026-10-10: "위치 상태 미보고" read as a fault). Fleet's site map pose first, CORE's
 * localization only when CORE reports one, else a neutral "지도 위치 없음"; needs_human stays critical. */
export function positionTag(loc, guideRow) {
  if (loc?.needs_human) return localizationTag(loc);
  const pose = guideRow?.pose;
  if (pose && Number.isFinite(pose.x) && Number.isFinite(pose.y)) {
    const words = [SITE_POSE_STATE[pose.state] || pose.state, SITE_POSE_SOURCE[pose.source] || pose.source]
      .filter(Boolean).join(" · ");
    return { text: words ? `지도 위치 ${words}` : "지도 위치", cls: pose.state === "LOCALIZED" ? "" : "warn",
      title: `Fleet map pose: ${pose.state} · ${pose.source}` };
  }
  if (loc && !loc.legacy) return localizationTag(loc);
  if (!loc && !guideRow) return null;  // offline or no evidence at all: the card says offline already
  return { text: "지도 위치 없음", cls: "",
    title: loc?.legacy ? "Fleet map pose: none · CORE localization: null" : "Fleet map pose: none" };
}
