/**
 * C14 robot row: one row form for robot arms and mobile robots (concept 2026-11-14: a repeated target is a row, not a
 * card). The model is robotProfile (robot-profile.js); this module only draws it. No inline styling, no animation (D-220).
 *
 *   createRobotRow(profile, {selected = false, onSelect}) -> <li class="robot-row">
 *     columns (data-col): name (icon, name, kind and id) | link | power | task | place | alarm | actions
 *     link   a ui-tag only when the report is delayed, lost or unknown; a fresh link draws nothing (calm normal)
 *     quieting  unknown is said once per row and the delay age once, on the link tag (quietRowTexts, D-280)
 *     alarm  one statusTag (caution / danger / unknown) or nothing; freshness and severity are separate columns
 *     onSelect(id)  adds the 선택 toggle (data-select-robot-id); profile.detail adds an info toggletip
 *   createRobotRoster(profiles, {selectedId, onSelect, emptyText}) -> <div class="robot-roster">
 *     groups "로봇암 (N)" and "이동로봇 (N)", each a list of rows under one column-label line; an empty group says
 *     so instead of vanishing.
 *   selection (optional, selection.js createSelection): the roster reads the selected id from the store, a 선택 press sets
 *     it (source "roster", onSelect still runs), and a change from any other view repaints the rows in place. The
 *     returned div gets dispose() to unsubscribe. Without it nothing changes (selectedId/onSelect as before).
 *   Rows stay in a list (ul), never boxes. Wide: one grid line per robot. Narrow: label above value, two per line.
 */
import {actionIcon, toggletip} from "./ui.js";
import {statusTag} from "./status-tag.js";
import {groupRobots} from "./robot-profile.js";
import {quietRowTexts} from "./core_ui_logic.js";

const COLUMNS = [["link", "연결"], ["power", "전원"], ["task", "작업"], ["place", "위치"], ["alarm", "경보"]];
const text = (tagName, className, content) => {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
};

function cell(name, label) {
  const node = text("div", "robot-cell");
  node.dataset.col = name;
  // the visible label shows only when the row is narrow (the column head line carries it when wide); screen readers always get it
  const visible = text("span", "robot-cell-label", label);
  visible.setAttribute("aria-hidden", "true");
  node.append(text("span", "sr-only", label), visible);
  return node;
}

function iconNode(name) {
  const holder = document.createElement("span");
  actionIcon(holder, name);
  return holder.firstElementChild;
}

export function createRobotRow(profile, {selected = false, onSelect} = {}) {
  const row = text("li", "robot-row");
  Object.assign(row.dataset, {robotId: profile.id, kind: profile.kind, link: profile.link.state});
  if (selected) row.dataset.selected = "";

  const name = text("div", "robot-cell");
  name.dataset.col = "name";
  const title = text("span", "robot-name");
  title.append(iconNode(profile.kind === "arm" ? "arm" : "robot"), text("b", "", profile.name));
  const sub = text("small", "robot-sub", profile.name === profile.id ? profile.kindLabel : `${profile.kindLabel} · ${profile.id}`);
  name.append(title, sub);

  const link = cell("link", "연결");
  // normal is quiet: only a report that is late, lost or unknown gets a tag; a fresh one is the screen-reader word only
  if (profile.link.state === "fresh") { link.append(text("span", "sr-only", profile.link.text)); link.dataset.empty = ""; }
  else link.append(statusTag(profile.link.state === "unavailable" ? "unknown" : profile.link.state, profile.link.text));

  const power = cell("power", "전원");
  const task = cell("task", "작업");
  const place = cell("place", "위치");
  // quiet row: the unknown marker is said once for the whole row and the delay age stays on the link tag only
  // (quietRowTexts, D-280); a cell whose age differs keeps its own age, and no value is invented.
  const quiet = quietRowTexts(profile.link, [profile.power.text, profile.task.text, profile.place.text]);
  for (const [node, part, shown] of [[power, profile.power, quiet[0]], [task, profile.task, quiet[1]], [place, profile.place, quiet[2]]]) {
    const value = text("span", "robot-value", shown);
    value.dataset.state = part.state;
    if (!shown) node.dataset.empty = ""; // a merged-away unknown leaves a calm blank cell, like a fresh link
    node.append(value);
  }
  if (profile.power.charging) power.querySelector(".robot-value").prepend(iconNode("charging"));

  const alarm = cell("alarm", "경보");
  if (profile.alarm) alarm.append(statusTag(profile.alarm.tag, profile.alarm.text, {icon: profile.alarm.icon}));
  else alarm.dataset.empty = ""; // narrow rows hide an empty cell, so a calm row shows no bare label

  const actions = text("div", "robot-cell");
  actions.dataset.col = "actions";
  if (typeof onSelect === "function") {
    const choose = text("ui-button", "", selected ? "선택됨" : "선택");
    choose.setAttribute("kind", "toggle");
    choose.setAttribute("type", "button");
    choose.setAttribute("aria-pressed", String(selected));
    choose.setAttribute("aria-label", `${profile.name} 선택`);
    choose.dataset.selectRobotId = profile.id;
    choose.addEventListener("click", () => onSelect(profile.id));
    actions.append(choose);
  }
  if (profile.detail) {
    const more = text("ui-button", "", "자세히"); // visible word: an icon-only button is for wide mouse surfaces only (concept rule 10)
    more.setAttribute("kind", "quiet");
    more.setAttribute("type", "button");
    more.setAttribute("aria-label", `${profile.name} 자세히`);
    actionIcon(more, "info");
    actions.append(more);
    toggletip(more, profile.detail);
  }

  row.append(name, link, power, task, place, alarm, actions);
  return row;
}

function paintSelected(root, id) {
  for (const row of root.querySelectorAll(".robot-row")) {
    const on = row.dataset.robotId === id;
    row.toggleAttribute("data-selected", on);
    const button = row.querySelector("[data-select-robot-id]");
    if (button) { button.setAttribute("aria-pressed", String(on)); button.firstChild.textContent = on ? "선택됨" : "선택"; }
  }
}

export function createRobotRoster(profiles, {selectedId, onSelect, selection, emptyText = {arm: "관측된 로봇암이 없습니다", mobile: "등록된 이동로봇이 없습니다"}} = {}) {
  const root = text("div", "robot-roster");
  if (selection) {
    const own = onSelect;
    selectedId = selection.get();
    onSelect = id => { selection.set(id, {source: "roster"}); own?.(id); };
    root.dispose = selection.subscribe(id => paintSelected(root, id));
  }
  for (const group of groupRobots(profiles)) {
    const section = text("section", "robot-group");
    section.dataset.kind = group.kind;
    section.append(text("h3", "robot-group-title", `${group.label} (${group.rows.length})`));
    if (!group.rows.length) {
      section.append(text("ui-empty", "", emptyText[group.kind]));
    } else {
      const head = text("div", "robot-row-head");
      head.setAttribute("aria-hidden", "true");
      head.append(text("span", "", "이름"), ...COLUMNS.map(([, label]) => text("span", "", label)), text("span", ""));
      const list = text("ul", "robot-rows");
      list.setAttribute("aria-label", group.label);
      list.append(...group.rows.map(profile => createRobotRow(profile, {selected: profile.id === selectedId, onSelect})));
      section.append(head, list);
    }
    root.append(section);
  }
  return root;
}
