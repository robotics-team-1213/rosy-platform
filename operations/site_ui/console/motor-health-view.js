import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from "/common/motor-health.js";

export function createFleetMotorHealth({view, scope}) {
  const states = new Map(), nodes = new Map();
  let ticking = false;
  function health(previous) {
    const robot = view.robots.find(row => row.robot_id === previous.robot_id) || previous;
    if (!states.has(robot.robot_id)) states.set(robot.robot_id, createMotorHealthState());
    const state = states.get(robot.robot_id);
    state.accept(robot.motor_health, {receivedAtMs: robot.motorHealthReceivedAtMs ?? view.receivedAtMs,
      requestedAtMs: robot.motorHealthRequestedAtMs, cacheAgeS: robot.motor_health_age_s,
      disconnected: view.stateUnavailable || robot.online === false});
    return state.read();
  }
  function make(robot, detail) {
    const root = document.createElement(detail ? "section" : "span");
    root.dataset.motorRobot = robot.robot_id;
    const paint = () => (detail ? renderMotorHealth : renderMotorHealthSummary)(root, health(robot));
    nodes.set(root, paint); paint();
    if (!ticking) { scope.interval(tick, 1000); ticking = true; }
    return root;
  }
  function tick() {
    for (const [root, paint] of nodes) {
      if (root.isConnected) paint();
      else nodes.delete(root);
    }
    for (const id of states.keys()) if (!view.robots.some(robot => robot.robot_id === id)) states.delete(id);
  }
  return {summary: robot => make(robot, false), detail: robot => make(robot, true)};
}
