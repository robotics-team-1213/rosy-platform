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
  const words = [SITE_POSE_STATE[pose.state] || pose.state, SITE_POSE_SOURCE[pose.source] || pose.source]
    .filter(Boolean).join("·");
  return `지도 ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}${words ? ` · ${words}` : ""}`;
}

/** The card's one position chip (field check 2026-10-10: "위치 상태 미보고" read as a fault on a lane-following
 * robot whose CORE runs without Nav2). What places the robot speaks first: Fleet's site map pose (D-536 guide
 * row, D-494 3: 확정/추정 · 카메라/odom 이음); CORE's own localization only when CORE reports one; else plainly
 * "지도 위치 없음", neutral, because a missing CORE block is not a fault. A person-needed state stays critical.
 * The words come from SITE_POSE_STATE/SITE_POSE_SOURCE above (one source with sitePoseText). */
export function positionTag(loc, guideRow) {
  if (loc?.needs_human) return localizationTag(loc);
  const pose = guideRow?.pose;
  if (pose && Number.isFinite(pose.x) && Number.isFinite(pose.y)) {
    const words = [SITE_POSE_STATE[pose.state] || pose.state, SITE_POSE_SOURCE[pose.source] || pose.source]
      .filter(Boolean).join(" · ");
    return { text: words ? `지도 위치 ${words}` : "지도 위치", cls: "", title: `Fleet map pose: ${pose.state} · ${pose.source}` };
  }
  if (loc && !loc.legacy) return localizationTag(loc);
  if (!loc && !guideRow) return null;  // offline or no evidence at all: the card says offline already
  return { text: "지도 위치 없음", cls: "",
    title: loc?.legacy ? "Fleet map pose: none · CORE localization: null" : "Fleet map pose: none" };
}
