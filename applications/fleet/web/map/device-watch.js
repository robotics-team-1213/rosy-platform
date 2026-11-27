// 지도 위 보기. 작동하는 것은 천장 영상과, 막힘 큐가 받아 둔 전방 사진뿐이다.
// 로봇 API 를 부르지 않고, 천장 원본은 camera-backdrop 이 둔 #map-birdseye 한 장이다.
import { setOffBy } from "/common/cause-line.js";
import { patchAttr, patchHidden } from "/common/control-dom.js";

/** The robot the map is already about: the open card, else the armed goal, else the only robot. */
export function shownRobot(view) {
  const robots = Array.isArray(view?.robots) ? view.robots.filter((robot) => robot && robot.robot_id) : [];
  const wanted = view?.focusRobot || view?.selected || "";
  const named = wanted ? robots.find((robot) => robot.robot_id === wanted) : null;
  if (named) return named;
  return robots.length === 1 ? robots[0] : null;
}

export function createDeviceWatch({ scope, el, view }) {
  const ceiling = el("watch-ceiling");
  const stage = el("map-stage");

  function syncCeiling() {
    const frame = el("map-birdseye");
    const live = Boolean(frame && !frame.hidden);
    patchAttr(ceiling, "aria-pressed", String(stage.dataset.watch !== "off"));
    setOffBy(ceiling, live ? "" : "영상 대기");
  }

  function paintFront(robot) {
    const figure = el("watch-front");
    const image = el("watch-front-image");
    const id = robot?.robot_id || "";
    const source = id
      ? document.querySelector(`.stuck-item[data-robot-id="${CSS.escape(id)}"] .stuck-evidence img`)
      : null;
    if (!source?.getAttribute("src")) {
      patchAttr(image, "src", null);
      if (image.alt !== "") image.alt = "";
      patchHidden(figure, true);
      return;
    }
    if (image.getAttribute("src") !== source.getAttribute("src")) image.src = source.src;
    const alt = source.alt || `${id} 전방`;
    if (image.alt !== alt) image.alt = alt;
    patchHidden(figure, false);
  }

  function render() {
    paintFront(view.stateUnavailable ? null : shownRobot(view));
    syncCeiling();
  }

  scope.listen(ceiling, "click", () => {
    stage.dataset.watch = stage.dataset.watch === "off" ? "pip" : "off";
    syncCeiling();
  });
  return { render };
}
