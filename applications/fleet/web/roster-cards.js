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
