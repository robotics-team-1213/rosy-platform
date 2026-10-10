// CAP-001 is evidence for presentation. CORE still decides every command.
import { robotMapPose } from "./localization-badge.js";

// Shared heading must agree, and a pack closer than one body is not "in front".
const AHEAD_AGREE_RAD = Math.PI / 3;
const AHEAD_TIE_M = 0.17;

export function capabilityReason(capabilities, feature) {
  if (capabilities === undefined) return ''; // Fleet versions before CAP-001 gather
  if (capabilities === null) return '주행 기능 확인 불가';
  let value = capabilities;
  for (const part of feature.split('.')) value = value?.[part];
  if (value === true) return '';
  if (capabilities.runtime?.mode === 'motor') return '수동 주행만 지원';
  if (capabilities.runtime?.mode === 'core') return '주행 런타임 대기';
  return feature === 'navigation.goal_navigation' ? '목표 주행 미지원' : '대형 주행 미지원';
}

export function formationReason(robots, leader, members) {
  const selected = [...new Set([leader, ...members])];
  if (!leader || selected.length < 2) return '리더와 팔로워를 고르세요';
  for (const id of selected) {
    const robot = robots.find(r => r.robot_id === id);
    if (!robot?.online) return `${id} · 로봇 오프라인`;
    const reason = capabilityReason(robot.capabilities, id === leader ? 'swarm.lead' : 'swarm.follow');
    if (reason) return `${id} · ${reason}`;
  }
  return '';
}

// Field check 2026-10-10: with only manual-only robots (CAP-001 runtime.maps.occupancy false) the console
// still asked /api/fleet/map every 30 s and logged a 404 each time. True only when every robot says so.
export function noRobotServesGrid(robots) {
  return robots.length > 0 && robots.every(robot => robot.capabilities?.runtime?.maps?.occupancy === false);
}

// The trailing number is the order: rosy_2 leads rosy_10. No number sorts after every number.
export function robotOrderNumber(robotId) {
  const parts = String(robotId ?? "").match(/\d+/g);
  if (!parts) return null;
  const value = Number(parts[parts.length - 1]);
  return Number.isSafeInteger(value) ? value : null;
}

function compareOrder(a, b) {
  const left = robotOrderNumber(a), right = robotOrderNumber(b);
  if (left === null && right === null) return String(a).localeCompare(String(b));
  if (left === null) return 1;
  if (right === null) return -1;
  return left - right || String(a).localeCompare(String(b));
}

function canLead(robot) {
  return Boolean(robot?.online && robot.robot_id)
    && capabilityReason(robot.capabilities, "swarm.lead") === "";
}

function travelYaw(poses) {
  let sine = 0, cosine = 0;
  for (const pose of poses) {
    sine += Math.sin(pose.yaw);
    cosine += Math.cos(pose.yaw);
  }
  if (Math.hypot(sine, cosine) / poses.length < Math.cos(AHEAD_AGREE_RAD)) return null;
  const yaw = Math.atan2(sine, cosine);
  const agrees = poses.every(pose => Math.abs(Math.atan2(
    Math.sin(pose.yaw - yaw), Math.cos(pose.yaw - yaw))) <= AHEAD_AGREE_RAD + 1e-9);
  return agrees ? yaw : null;
}

/** Leader for a formation. `by` is `ahead` (furthest LOCALIZED map pose along the shared heading),
 * `number` (smaller trailing id, also the tie-break inside 0.17 m), or empty when nobody can lead. */
export function chooseLeader(robots, poseOf = robotMapPose) {
  const candidates = (robots || []).filter(canLead);
  if (!candidates.length) return { id: "", by: "" };
  const posed = [];
  for (const robot of candidates) {
    const pose = poseOf(robot);
    if (pose && [pose.x, pose.y, pose.yaw].every(Number.isFinite)) {
      posed.push({ id: robot.robot_id, x: pose.x, y: pose.y, yaw: pose.yaw });
    }
  }
  const yaw = posed.length >= 2 ? travelYaw(posed) : null;
  if (yaw !== null) {
    const cx = posed.reduce((sum, pose) => sum + pose.x, 0) / posed.length;
    const cy = posed.reduce((sum, pose) => sum + pose.y, 0) / posed.length;
    const scored = posed.map(pose => ({
      id: pose.id,
      score: (pose.x - cx) * Math.cos(yaw) + (pose.y - cy) * Math.sin(yaw),
    }));
    const best = Math.max(...scored.map(row => row.score));
    const pack = scored.filter(row => best - row.score <= AHEAD_TIE_M).map(row => row.id).sort(compareOrder);
    return { id: pack[0], by: pack.length === 1 ? "ahead" : "number" };
  }
  return { id: candidates.map(robot => robot.robot_id).sort(compareOrder)[0], by: "number" };
}

/** How 리더에게 길 주기 moves the leader: a map point (Nav goal) or the card's lane trip. */
export function leaderPathKind(robot, { map = false, places = 0 } = {}) {
  if (!robot?.online) return { kind: "", reason: robot?.robot_id ? `${robot.robot_id} · 로봇 오프라인` : "리더를 고르세요" };
  const estop = robot.state?.safety?.estop;
  if (estop === true) return { kind: "", reason: "비상정지 중" };
  if (estop !== false) return { kind: "", reason: "안전 상태 확인 불가" };
  const mode = robot.state?.line_follow?.mode;
  const lane = mode === "CAMERA_LINE" || mode === "IR_LINE";
  if (!lane && map && capabilityReason(robot.capabilities, "navigation.goal_navigation") === "") {
    return { kind: "goal", reason: "" };
  }
  if (places > 0) return { kind: "trip", reason: "" };
  if (lane) return { kind: "", reason: "차선 추종 중 · 활성 현장 지도가 없습니다" };
  const cap = capabilityReason(robot.capabilities, "navigation.goal_navigation");
  return { kind: "", reason: cap || (map ? "길을 줄 수 없습니다" : "지도 없음") };
}
