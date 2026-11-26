import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from "/common/motor-health.js";
import {patchHidden} from "/common/control-dom.js";

export function createFleetMotorHealth({view, scope}) {
  const states = new Map(), summaryNodes = new Map(), detailNodes = new Map();
  function health(robotId) {
    const robot = view.robots.find(row => row.robot_id === robotId) || {robot_id: robotId};
    if (!states.has(robotId)) states.set(robotId, createMotorHealthState());
    const state = states.get(robotId);
    state.accept(robot.motor_health, {receivedAtMs: robot.motorHealthReceivedAtMs ?? view.receivedAtMs,
      requestedAtMs: robot.motorHealthRequestedAtMs, cacheAgeS: robot.motor_health_age_s,
      disconnected: view.stateUnavailable || robot.online === false});
    return state.read();
  }
  function obtain(robot, detail) {
    const map = detail ? detailNodes : summaryNodes;
    let entry = map.get(robot.robot_id);
    if (!entry) {
      const root = document.createElement(detail ? "section" : "span");
      root.dataset.motorRobot = robot.robot_id;
      const paint = () => {
        const read = health(robot.robot_id);
        // A robot that never reported motors shows no motor row, so the local roster stays compact.
        patchHidden(root, !read.motors.length && read.status === 'unavailable' && !read.lastFault);
        (detail ? renderMotorHealth : renderMotorHealthSummary)(root, read);
      };
      entry = {root, paint};
      map.set(robot.robot_id, entry);
    }
    entry.paint();
    return entry.root;
  }
  function tick() {
    for (const [id, entry] of summaryNodes) {
      if (entry.root.isConnected) entry.paint();
      else if (!view.robots.some(robot => robot.robot_id === id)) summaryNodes.delete(id);
    }
    for (const [id, entry] of detailNodes) {
      if (entry.root.isConnected) entry.paint();
      else if (!view.robots.some(robot => robot.robot_id === id)) detailNodes.delete(id);
    }
    for (const id of states.keys()) if (!view.robots.some(robot => robot.robot_id === id)) states.delete(id);
  }
  // Registered once with the page, not on the first card, so the page owns a fixed set of polls.
  scope?.interval(tick, 1000);
  return {summary: robot => obtain(robot, false), detail: robot => obtain(robot, true)};
}
