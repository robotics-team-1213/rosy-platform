import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from "/common/motor-health.js";

export function createFleetMotorHealth({view, scope}) {
  const states = new Map(), nodes = new Map();
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
    const paint = () => {
      const read = health(robot);
      // A robot that never reported motors shows no motor row, so the local roster stays compact.
      root.hidden = !read.motors.length && read.status === 'unavailable' && !read.lastFault;
      (detail ? renderMotorHealth : renderMotorHealthSummary)(root, read);
    };
    nodes.set(root, paint); paint();
    return root;
  }
  function tick() {
    for (const [root, paint] of nodes) {
      if (root.isConnected) paint();
      else nodes.delete(root);
    }
    for (const id of states.keys()) if (!view.robots.some(robot => robot.robot_id === id)) states.delete(id);
  }
  // Registered once with the page, not on the first card, so the page owns a fixed set of polls.
  scope?.interval(tick, 1000);
  return {summary: robot => make(robot, false), detail: robot => make(robot, true)};
}
