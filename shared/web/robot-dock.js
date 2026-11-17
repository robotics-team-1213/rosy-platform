/**
 * C23 robot dock: vertical strip (>=64rem) or horizontal row (<64rem) of robot quick-pick buttons.
 * Consumes robotProfile objects via dockEntries (robot-dock-model.js) and selection store (selection.js).
 * No inline styling, no animation (D-220).
 *
 *   createRobotDock({selection, profiles = [], onToggle, kinds, ids} = {})
 *     -> {root, setProfiles(list), setOpen(id | null), dispose()}
 *     root             <nav class="robot-dock" aria-label="로봇">
 *     setProfiles(list) updates buttons in place by id (preserves focus), adds/removes others
 *     setOpen(id|null) repaints aria-pressed (at most one true) and data-selected from selection.get()
 *     dispose()        unsubscribes from selection
 */
import {actionIcon} from "./ui.js";
import {dockEntries} from "./robot-dock-model.js";

const GROUPS = [
  {kind: "mobile", label: "이동로봇", shortLabel: "이동"},
  {kind: "arm", label: "로봇암", shortLabel: "팔"},
];

const MARK_ICON = Object.freeze({
  delayed: "history",
  disconnected: "wifi",
  unknown: "minus",
  caution: "warn",
  danger: "estop",
});

function iconSvg(name) {
  const holder = document.createElement("span");
  actionIcon(holder, name);
  return holder.firstElementChild;
}

function makeMark(mark) {
  const span = document.createElement("span");
  span.className = "robot-dock-mark";
  span.dataset.markKind = mark.kind;
  span.dataset.state = mark.state;
  span.setAttribute("aria-hidden", "true");
  span.append(iconSvg(MARK_ICON[mark.state] || "minus"));
  return span;
}

function syncButton(btn, entry, profile, {openId, selectedId, markSigs}) {
  btn.dataset.robotId = entry.id;
  btn.dataset.kind = entry.kind;
  btn.dataset.link = profile?.link?.state || "unavailable";
  if (profile?.alarm) btn.dataset.alarm = profile.alarm.tag || profile.alarm.level || "unknown";
  else btn.removeAttribute("data-alarm");
  btn.toggleAttribute("data-selected", selectedId === entry.id);
  btn.setAttribute("aria-pressed", String(openId === entry.id));
  btn.setAttribute("aria-label", entry.label);
  if (openId === entry.id) btn.removeAttribute("data-ui-tooltip");
  else btn.setAttribute("data-ui-tooltip", entry.label);

  const iconName = entry.kind === "arm" ? "arm" : "robot";
  let iconWrap = btn.querySelector(":scope > .robot-dock-icon");
  if (!iconWrap) {
    iconWrap = document.createElement("span");
    iconWrap.className = "robot-dock-icon";
    btn.append(iconWrap);
  }
  if (iconWrap.dataset.iconName !== iconName) {
    iconWrap.dataset.iconName = iconName;
    iconWrap.replaceChildren(iconSvg(iconName));
  }

  let idSpan = btn.querySelector(":scope > .robot-dock-id");
  if (!idSpan) {
    idSpan = document.createElement("span");
    idSpan.className = "robot-dock-id";
    btn.append(idSpan);
  }
  if (idSpan.textContent !== entry.short) idSpan.textContent = entry.short;

  const marksSig = `${entry.id}|${entry.marks.map((m) => `${m.kind}:${m.state}:${MARK_ICON[m.state] || "minus"}`).join(",")}`;
  if (!markSigs || markSigs.get(entry.id) !== marksSig) {
    markSigs?.set(entry.id, marksSig);
    for (const oldMark of btn.querySelectorAll(":scope > .robot-dock-mark")) oldMark.remove();
    for (const mark of entry.marks) btn.append(makeMark(mark));
  }
}

function syncChildrenOrder(parent, desired) {
  // Insert/move only out-of-place nodes so an already-focused button stays connected and keeps focus.
  const keep = new Set(desired);
  for (const child of [...parent.children]) {
    if (!keep.has(child)) child.remove();
  }
  desired.forEach((node, index) => {
    const at = parent.children[index];
    if (at !== node) parent.insertBefore(node, at || null);
  });
}

export function createRobotDock({selection, profiles = [], onToggle, kinds, ids} = {}) {
  const root = document.createElement("nav");
  root.className = "robot-dock";
  root.setAttribute("aria-label", "로봇");

  let openId = null;
  const buttons = new Map();
  const groupEls = new Map();
  const markSigs = new Map();

  function paintFlags() {
    const selectedId = selection?.get?.() ?? null;
    for (const [id, btn] of buttons) {
      btn.setAttribute("aria-pressed", String(openId === id));
      btn.toggleAttribute("data-selected", selectedId === id);
      if (openId === id) btn.removeAttribute("data-ui-tooltip");
      else if (btn.getAttribute("aria-label")) btn.setAttribute("data-ui-tooltip", btn.getAttribute("aria-label"));
    }
  }

  function setOpen(id) {
    openId = id ?? null;
    paintFlags();
  }

  function onButtonClick(id, btn) {
    if (openId === id) {
      setOpen(null);
      onToggle?.(null);
      return;
    }
    btn.focus();
    selection?.set?.(id, {source: "dock"});
    setOpen(id);
    onToggle?.(id);
  }

  function getGroupEl(spec) {
    let group = groupEls.get(spec.kind);
    if (!group) {
      group = document.createElement("div");
      group.className = "robot-dock-group";
      group.dataset.kind = spec.kind;
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", spec.label);
      const label = document.createElement("span");
      label.className = "robot-dock-label";
      label.setAttribute("aria-hidden", "true");
      label.textContent = spec.shortLabel;
      group.append(label);
      groupEls.set(spec.kind, group);
    }
    return group;
  }

  function setProfiles(list = []) {
    const entries = dockEntries(list, {kinds, ids});
    const byId = new Map(list.filter(Boolean).map((p) => [String(p.id ?? ""), p]));
    const selectedId = selection?.get?.() ?? null;
    const seen = new Set();

    const activeGroups = [];
    for (const spec of GROUPS) {
      const groupEntries = entries.filter((e) => e.kind === spec.kind);
      if (!groupEntries.length) continue;
      const groupEl = getGroupEl(spec);
      const labelEl = groupEl.querySelector(":scope > .robot-dock-label");
      const desired = [labelEl];
      for (const entry of groupEntries) {
        seen.add(entry.id);
        let btn = buttons.get(entry.id);
        if (!btn) {
          btn = document.createElement("button");
          btn.type = "button";
          btn.className = "robot-dock-btn";
          btn.addEventListener("click", () => onButtonClick(entry.id, btn));
          buttons.set(entry.id, btn);
        }
        syncButton(btn, entry, byId.get(entry.id), {openId, selectedId, markSigs});
        desired.push(btn);
      }
      syncChildrenOrder(groupEl, desired);
      activeGroups.push(groupEl);
    }

    for (const [id, btn] of buttons) {
      if (!seen.has(id)) {
        btn.remove();
        buttons.delete(id);
        markSigs.delete(id);
      }
    }
    syncChildrenOrder(root, activeGroups);
  }

  const offSelection = selection?.subscribe ? selection.subscribe(() => paintFlags()) : () => {};
  setProfiles(profiles);

  return {
    root,
    setProfiles,
    setOpen,
    dispose() {
      offSelection();
    },
  };
}
