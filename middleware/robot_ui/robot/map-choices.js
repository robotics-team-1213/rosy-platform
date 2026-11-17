// The two map pickers, one definition for the compat console and the console panel (S2):
//   layers  K5 toggle group, independent show/hide flags with immediate effect (occupancy, costmap, path)
//   clicks  K1 single group, what a click on the map does (set the start pose, or set the goal)
// createFieldMap (map.js) binds handlers and drives the click items; callers only place the two elements.
import {createChoiceGroup} from "/common/choice-group.js";

export const LAYER_IDS = ["occupancy", "costmap", "path"];
export const CLICK_IDS = ["pose", "goal"];

/** labels: {layers: [3 strings], clicks: [2 strings]}; id: unique prefix for the two groups. */
export function createMapChoices({id, labels}) {
  const handlers = {layers: () => {}, click: () => {}};
  const layers = createChoiceGroup({id: `${id}-layers`, label: "지도 레이어", mode: "toggle", value: LAYER_IDS,
    items: LAYER_IDS.map((value, at) => ({value, label: labels.layers[at]})), onChange: (values) => handlers.layers(values)});
  const clicks = createChoiceGroup({id: `${id}-click`, label: "지도 클릭 동작", mode: "single", value: "pose",
    items: CLICK_IDS.map((value, at) => ({value, label: labels.clicks[at]})), onChange: (mode) => handlers.click(mode)});
  const tag = () => {
    for (const button of layers.element.querySelectorAll("[data-value]")) button.dataset.mapLayer = button.dataset.value;
    for (const input of clicks.element.querySelectorAll("input")) input.dataset.mapClick = input.value;
  };
  tag();
  return {layers, clicks, handlers, tag, labels};
}
