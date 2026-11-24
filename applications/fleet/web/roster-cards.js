import { evidenceAgeText } from "/common/core_ui_logic.js";
import { createRobotVideo, bindVisibility } from "/console/assets/robot-video.js";

/** Calm whole-second / 5-second stepped offline last-seen line for in-place updates. */
export function lastSeenText(robot, nowMs = Date.now()) {
  const ts = robot?.state?.ts;
  if (typeof ts !== "number" || ts <= 0) return "응답 없음";
  const raw = Math.max(0, Math.floor((nowMs / 1000) - ts));
  if (raw >= 3600) return `마지막 응답: ${Math.floor(raw / 3600)}시간 전`;
  if (raw >= 60) return `마지막 응답: ${Math.floor(raw / 60)}분 전`;
  const calm = raw < 5 ? raw : Math.floor(raw / 5) * 5;
  return `마지막 응답: ${evidenceAgeText(calm).slice(3)}`;
}

/** Structural key for workspace cards. Live facts update in place. */
export function workspaceCardKey({
  robot, slot, displayName, view, state, power, nav, tripLine, stateStale,
  loc, sitePose, address, evidence, operator, named, goalMotion, openTripId, tripKey, moveBlocked,
}) {
  return JSON.stringify({
    id: robot.robot_id, slot, displayName, online: robot.online, link: robot.link,
    linkReason: robot.link_reason || null, ruleM: robot.rule_m || null, error: robot.error || null,
    calibration: robot.calibration || null, queued: robot.queued || null, yielding: robot.yielding || null,
    pose: Boolean(state.pose), pose_frame: state.pose_frame, map_id: state.map_id,
    sitePose: Boolean(sitePose), mode: state.mode, lineFollow: state.line_follow || null,
    powerMode: state.power?.mode, motionReady: state.power?.motion_ready,
    dock: state.docking?.state || null, diag: stateStale ? null : (state.diagnostics_summary || null),
    safety: state.safety || null, caps: robot.capabilities || null, locState: robot.localization || null,
    chargeState: robot.power_health?.battery?.charging_state || null,
    power: {
      hasBatteryProblem: Boolean(power.problem), hasNote: Boolean(power.note), safetyRelease: power.safetyRelease,
      chargingKind: power.chargingConfirmed ? "confirmed" : power.charging ? "hint" : "none",
    },
    nav, tripLine, stateStale, evidence, loc, address,
    addressStatus: view.addresses?.[robot.robot_id]?.status || null,
    selected: view.selected === robot.robot_id, pinning: view.pinning === robot.robot_id,
    stateUnavailable: Boolean(view.stateUnavailable), hasMap: Boolean(view.map), hasSiteMap: Boolean(view.siteMap),
    formation: view.formation?.active ? { leader: view.formation.leader, members: Object.keys(view.formation.assignment || {}) } : null,
    operator: Boolean(operator), named, goalMotion, openTripId, tripKey,
    peers: view.robotPeers, moveBlocked,
  });
}

/** D-651: all four safety exceptions remain visible in the compact list, ahead of nominal robots. */
export function mustExpand(robot) {
  const estop = robot.state?.safety?.estop;
  return !robot.online || !robot.state || estop !== false || Boolean(robot.calibration);
}

/** Inspection is UI-only. Switching robots withdraws every pending map interaction. */
export function selectRobot(view, robotId) {
  if (robotId && !view.robots.some(robot => robot.robot_id === robotId)) return false;
  if (view.focusRobot === robotId) return false;
  view.focusRobot = robotId || null;
  view.selected = null;
  view.pinning = null;
  view.cursor = null;
  return true;
}

export function placeRosterCards(box, cards) {
  const focus = document.activeElement;
  const focused = focus?.matches("select, .motor-health-scroll, summary, details[data-more], [data-more-toggle]")
    ? focus.closest("article") : null;
  const keep = focused?.parentElement === box && focus.matches("select, .motor-health-scroll") ? focused : null;
  const disclosure = focused?.parentElement === box && !keep ? focus : null;
  if (keep) {
    const current = cards.find(node => node.dataset.robotId === keep.dataset.robotId);
    const motor = current && current !== keep ? current.querySelector("[data-motor-robot]") : null;
    const oldMotor = keep.querySelector("[data-motor-robot]");
    if (motor && oldMotor !== motor) {
      if (oldMotor) oldMotor.replaceWith(motor);
      else keep.querySelector(".facts")?.after(motor);
    }
    const profile = current && current !== keep ? current.querySelector("[data-robot-profile]") : null;
    const oldProfile = keep.querySelector("[data-robot-profile]");
    if (profile && oldProfile !== profile) {
      if (oldProfile) oldProfile.replaceWith(profile);
      else (keep.querySelector("[data-motor-robot]") || keep.querySelector(".facts"))?.after(profile);
    }
    const form = keep.querySelector(".card-trip"), previous = form?.querySelector(".stuck-result");
    const note = current?.querySelector(".card-trip .stuck-result");
    if (previous?.textContent !== note?.textContent) {
      previous?.remove();
      if (form && note) form.append(note.cloneNode(true));
    }
  }
  const nodes = cards.map((node) => (keep && node.dataset.robotId === keep.dataset.robotId ? keep : node));
  if (nodes.length === box.children.length && nodes.every((node, i) => box.children[i] === node)) return;
  const wanted = new Set(nodes);
  for (const node of [...box.children]) if (!wanted.has(node)) node.remove();
  nodes.forEach((node, i) => { if (box.children[i] !== node) box.insertBefore(node, box.children[i] || null); });
  if (disclosure && document.activeElement !== disclosure) {
    const card = nodes.find(node => node.dataset.robotId === focused.dataset.robotId);
    (card?.querySelector(disclosure.matches("[data-more-toggle]") ? "[data-more-toggle]" : disclosure.localName) || card)?.focus({preventScroll: true});
  }
}

export const OMX_CELL_DEFS = [
  { target_id: "arm_a", kind: "omx_ai", label: "OMX-AI #1 · arm_a (cell_ab · S5 1·3층 적재)", shortLabel: "Arm A · S5", stationId: "S5", stationName: "S5 팔레트 적재 (1·3층)", stationX: 0.9212, stationY: -0.4776, base_x: 0.551, base_y: 0.365, head_x: 0.550, head_y: 0.109, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_b", kind: "omx_ai", label: "OMX-AI #2 · arm_b (cell_ab · S5 2층 적재)", shortLabel: "Arm B · S5", stationId: "S5", stationName: "S5 팔레트 적재 (2층)", stationX: 0.9212, stationY: -0.4776, base_x: 0.956, base_y: 0.370, head_x: 0.956, head_y: 0.113, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_s", kind: "omx_ai", label: "OMX-AI #3 · arm_s (cell_s · S3 하역 셔틀)", shortLabel: "Arm S · S3", stationId: "S3", stationName: "S3 하역 셔틀", stationX: 0.6987, stationY: -0.2512, base_x: 0.960, base_y: -0.035, head_x: 0.703, head_y: -0.035, head_yaw: 3.14, reach_m: 0.28, zoom: 4 },
];

/** D-801: one robot's front camera in its card's ROI spot. Started by the person, closed on reselect or hide. */
// Nothing is created until the person asks: no DOM, no grant, no WHEP session.
export function createFrontCamera({ call, scope }) {
  let stage = null, video = null, robotId = null, unbind = null;
  const stop = () => { robotId = null; unbind?.(); unbind = null; video?.stop(); };
  scope.onDispose(stop);
  return {
    stop,
    stage: () => stage,
    robotId: () => robotId,
    toggle(id) {
      if (robotId === id) { stop(); return; }
      stop();
      stage ??= Object.assign(document.createElement("div"), { className: "robot-video-stage" });
      video ??= createRobotVideo({ call });
      robotId = id;
      unbind = bindVisibility({ target: stage, video });
      void video.start(stage, [id]);
    },
  };
}
