import { createRobotVideo, bindVisibility } from "/console/assets/robot-video.js";

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

// A focused picker or motor table keeps its card across polling updates.
export function placeRosterCards(box, cards) {
  const focus = document.activeElement;
  const focused = focus?.matches("select, .motor-health-scroll") ? focus.closest("#robot-workspace article") : null;
  const keep = focused?.parentElement === box ? focused : null;
  if (keep) {
    const current = cards.find(node => node.dataset.robotId === keep.dataset.robotId);
    const profile = current?.querySelector("[data-robot-profile]");
    if (profile) keep.querySelector("[data-robot-profile]")?.replaceWith(profile);
    const form = keep.querySelector(".card-trip"), previous = form?.querySelector(".stuck-result");
    const note = current?.querySelector(".card-trip .stuck-result");
    if (previous?.textContent !== note?.textContent) {
      previous?.remove();
      if (form && note) form.append(note);
    }
  }
  const nodes = cards.map((node) => (keep && node.dataset.robotId === keep.dataset.robotId ? keep : node));
  if (!nodes.includes(keep)) { box.replaceChildren(...nodes); return; }
  for (const node of [...box.children]) if (node !== keep) node.remove();
  nodes.forEach((node, i) => { if (box.children[i] !== node) box.insertBefore(node, box.children[i] || null); });
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
