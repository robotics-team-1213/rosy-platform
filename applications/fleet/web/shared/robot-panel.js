/**
 * C24 robot panel: non-modal left push column (>=64rem) or below-header sheet (<64rem) for one robot.
 * Shell only: head (name, abnormal link statusTag, close), ordered sections (status, camera, commands,
 * collapsible manual controls & settings), and fixed stop footer (live stop button or note). No inline styling, no animation (D-220).
 *
 *   createRobotPanel({selection, onClose, onManualCollapse, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {})
 *     -> {root, setRobot(profile | null, detail?, opts?), focus(), dispose()}
 *     sections        {status, camera, commands, manual, health, settings}, each (profile, detail) => Node | null
 *     onManualCollapse called when the manual <details> section collapses
 *     stop            {label, onStop} | {note} | null, or (profile) => obj | null
 *     stopButton      static HTML emergency-stop <ui-button> passed from the page (D-371)
 *     links           {taskRow(taskId) -> url}: link builders each screen supplies (deep link to its work-screen task row); sections get them as the 3rd argument. A link is navigation, never a call; approve/resume happen on the work screen.
 *     resolve(id)     optional (id) => {profile, detail} | null; follows selection while open
 *     setRobot(...)   non-null opens/updates and focuses title on first open, robot switch, or {force: true};
 *                     same-id updates patch head, freshness, changed sections, and footer in place; null hides
 *     focus()         moves focus to .robot-panel-title (tabindex=-1)
 *     dispose()       unsubscribes from selection
 */
import {actionIcon} from "/common/ui.js";
import {EVIDENCE_LABEL} from "/common/core_ui_logic.js";

const STATUS_TAGS = Object.freeze({
  fresh: {status: "neutral", icon: null, text: EVIDENCE_LABEL.fresh},
  progress: {status: "active", icon: null, text: "진행 중"},
  delayed: {status: "warn", icon: "history", text: EVIDENCE_LABEL.delayed},
  disconnected: {status: "warn", icon: "wifi", text: EVIDENCE_LABEL.disconnected},
  unknown: {status: "neutral", icon: "minus", text: EVIDENCE_LABEL.unavailable},
  caution: {status: "warn", icon: "warn", text: "주의"},
  danger: {status: "crit", icon: "safety", text: "위험"},
  locked: {status: "neutral", icon: "lock", text: "잠김"},
});

function statusTag(state, text, {icon, danger = false} = {}) {
  const row = STATUS_TAGS[state];
  if (!row) throw new RangeError(`Unknown status tag state: ${state}`);
  const tag = document.createElement("ui-tag");
  tag.setAttribute("status", state === "disconnected" && danger ? "crit" : row.status);
  tag.dataset.state = state;
  tag.textContent = text ?? row.text;
  const name = icon ?? row.icon;
  if (name) actionIcon(tag, name);
  return tag;
}

let panelSerial = 0;

const SECTION_SPECS = [
  ["status", "상태"],
  ["camera", "카메라"],
  ["commands", "명령"],
  ["manual", "수동 조종"],
  ["health", "모터 · 진단"],
  ["settings", "설정 · 장치"],
];

const JUMP_SPECS = [
  ["status", "상태"],
  ["camera", "카메라"],
  ["commands", "명령"],
  ["manual", "수동"],
  ["settings", "설정"],
];

export function createRobotPanel({selection, onClose, onManualCollapse, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {}) {
  const panelId = ++panelSerial;
  const root = document.createElement("aside");
  root.className = "robot-panel";
  root.hidden = true;

  const head = document.createElement("header");
  head.className = "robot-panel-head";

  const title = document.createElement("h2");
  title.className = "robot-panel-title";
  title.id = `robot-panel-title-${panelId}`;
  title.tabIndex = -1;
  root.setAttribute("aria-labelledby", title.id);

  const linkSlot = document.createElement("span");
  linkSlot.className = "robot-panel-link";
  linkSlot.hidden = true;

  const closeBtn = document.createElement("ui-button");
  closeBtn.className = "robot-panel-close";
  closeBtn.setAttribute("kind", "quiet");
  closeBtn.setAttribute("type", "button");
  closeBtn.textContent = "닫기";

  head.append(title, linkSlot, closeBtn);

  const body = document.createElement("div");
  body.className = "robot-panel-body";

  const foot = document.createElement("div");
  foot.className = "robot-panel-foot";
  foot.hidden = true;

  root.append(head, body, foot);

  let opener = null;
  let currentId = null;
  let activeStop = null;
  let closing = false;
  const sectionMap = new Map();
  let jumpsNav = null;
  let footerMode = null;
  let footerNoteEl = null;
  const fallbackStopBtn = document.createElement("ui-button");
  fallbackStopBtn.className = "robot-panel-stop";
  fallbackStopBtn.setAttribute("kind", "quiet");
  fallbackStopBtn.setAttribute("type", "button");
  fallbackStopBtn.setAttribute("data-always-live", "");
  const boundButtons = new WeakSet();
  const ensureStopButton = (btn) => {
    const target = btn || stopButton || fallbackStopBtn;
    target.classList.add("robot-panel-stop");
    target.setAttribute("type", "button");
    target.setAttribute("data-always-live", "");
    if (!boundButtons.has(target)) {
      boundButtons.add(target);
      target.addEventListener("click", () => activeStop?.());
    }
    return target;
  };

  function makeSectionWrapper(key, heading, content) {
    if (key === "settings" || key === "manual") {
      const details = document.createElement("details");
      details.className = "robot-panel-section";
      details.dataset.section = key;
      const summary = document.createElement("summary");
      summary.textContent = heading;
      details.append(summary, content);
      if (key === "manual") {
        details.addEventListener("toggle", () => {
          if (details.open) details.scrollIntoView?.({block: "end"});
          else onManualCollapse?.();
        });
      }
      return details;
    }
    const section = document.createElement("section");
    section.className = "robot-panel-section";
    section.dataset.section = key;
    const h3 = document.createElement("h3");
    h3.id = `robot-panel-sec-${panelId}-${key}`;
    h3.textContent = heading;
    section.setAttribute("aria-labelledby", h3.id);
    section.append(h3, content);
    return section;
  }

  function syncJumps(presentSections) {
    const jumpTargets = JUMP_SPECS.filter(([key]) => presentSections.has(key));
    const sig = jumpTargets.map(([key]) => key).join(",");
    if (jumpsNav && jumpsNav.dataset.jumpSig === sig) return;
    jumpsNav?.remove();
    jumpsNav = null;
    if (!jumpTargets.length) return;
    jumpsNav = document.createElement("nav");
    jumpsNav.className = "robot-panel-jumps";
    jumpsNav.dataset.jumpSig = sig;
    jumpsNav.setAttribute("aria-label", "패널 섹션 바로가기");
    for (const [key, label] of jumpTargets) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "robot-panel-jump";
      btn.dataset.jumpSection = key;
      btn.textContent = label;
      btn.addEventListener("click", () => {
        const target = body.querySelector(`[data-section="${key}"]`);
        if (!target) return;
        if (target.tagName === "DETAILS") target.open = true;
        target.scrollIntoView?.({block: "nearest"});
      });
      jumpsNav.append(btn);
    }
    body.prepend(jumpsNav);
  }

  function setRobot(profile, detail, {force = false} = {}) {
    if (!profile) {
      root.hidden = true;
      root.removeAttribute("data-kind");
      root.removeAttribute("data-robot-id");
      title.textContent = "";
      linkSlot.replaceChildren();
      linkSlot.hidden = true;
      body.replaceChildren();
      sectionMap.clear();
      jumpsNav = null;
      foot.replaceChildren();
      foot.hidden = true;
      footerMode = null;
      footerNoteEl = null;
      activeStop = null;
      if (stopButton) stopButton.hidden = true;
      currentId = null;
      opener = null;
      return;
    }

    const wasHidden = root.hidden;
    const prevId = currentId;
    const nextId = String(profile.id ?? "");
    const sameId = !wasHidden && !force && prevId === nextId;
    if (wasHidden) opener = document.activeElement;
    currentId = nextId;

    root.dataset.kind = profile.kind || "";
    root.dataset.robotId = nextId;

    const displayName = profile.name || nextId;
    if (title.textContent !== displayName) title.textContent = displayName;
    closeBtn.setAttribute("aria-label", `${displayName} 패널 닫기`);

    const linkState = profile.link?.state;
    if (linkState && linkState !== "fresh") {
      const tagState = linkState === "unavailable" ? "unknown" : linkState;
      const linkText = profile.link.text || "";
      if (linkSlot.dataset.tagState !== tagState || linkSlot.dataset.tagText !== linkText || linkSlot.hidden) {
        linkSlot.dataset.tagState = tagState;
        linkSlot.dataset.tagText = linkText;
        linkSlot.replaceChildren(statusTag(tagState, profile.link.text));
        linkSlot.hidden = false;
      }
    } else if (!linkSlot.hidden || linkSlot.childElementCount) {
      delete linkSlot.dataset.tagState;
      delete linkSlot.dataset.tagText;
      linkSlot.replaceChildren();
      linkSlot.hidden = true;
    }

    if (!sameId) {
      body.replaceChildren();
      sectionMap.clear();
      jumpsNav = null;
      body.scrollTop = 0;
    }

    const presentSections = new Set();
    const desiredNodes = [];
    for (const [key, heading] of SECTION_SPECS) {
      const render = sections?.[key];
      const content = typeof render === "function" ? render(profile, detail, links) : null;
      const existing = sameId ? sectionMap.get(key) : null;
      if (content == null) {
        if (existing) {
          existing.wrapper.remove();
          sectionMap.delete(key);
        }
        continue;
      }
      presentSections.add(key);
      if (existing) {
        if (content !== existing.content) {
          existing.content.replaceWith(content);
          existing.content = content;
        }
        desiredNodes.push(existing.wrapper);
      } else {
        const wrapper = makeSectionWrapper(key, heading, content);
        sectionMap.set(key, {wrapper, content});
        desiredNodes.push(wrapper);
      }
    }

    syncJumps(presentSections);
    const startOffset = jumpsNav ? 1 : 0;
    desiredNodes.forEach((node, index) => {
      const at = body.children[index + startOffset];
      if (at !== node) body.insertBefore(node, at || null);
    });

    activeStop = null;
    if (stopButton && footerMode !== "btn") stopButton.hidden = true;
    const stopSpec = typeof stop === "function" ? stop(profile) : stop;
    if (stopSpec?.label) {
      const stopBtn = ensureStopButton(stopSpec.button);
      activeStop = typeof stopSpec.onStop === "function" ? () => stopSpec.onStop(profile, detail) : null;
      if (footerMode !== "btn" || stopBtn.parentElement !== foot) {
        foot.replaceChildren(stopBtn);
        footerMode = "btn";
        footerNoteEl = null;
      }
      stopBtn.hidden = false;
      if (stopBtn.textContent !== stopSpec.label) stopBtn.textContent = stopSpec.label;
      foot.hidden = false;
    } else if (stopSpec?.note) {
      if (stopButton) stopButton.hidden = true;
      if (footerMode !== "note" || !footerNoteEl) {
        footerNoteEl = document.createElement("p");
        footerNoteEl.className = "robot-panel-stop-note";
        foot.replaceChildren(footerNoteEl);
        footerMode = "note";
      }
      if (footerNoteEl.textContent !== stopSpec.note) footerNoteEl.textContent = stopSpec.note;
      foot.hidden = false;
    } else {
      if (stopButton) stopButton.hidden = true;
      if (foot.childElementCount || !foot.hidden) {
        foot.replaceChildren();
        foot.hidden = true;
      }
      footerMode = null;
      footerNoteEl = null;
    }

    root.hidden = false;
    if (!sameId) title.focus();
  }

  function close() {
    if (root.hidden || closing) return;
    closing = true;
    const back = opener;
    try {
      onClose?.();
      setRobot(null);
      if (back?.isConnected && typeof back.focus === "function") back.focus();
    } finally {
      closing = false;
    }
  }

  closeBtn.addEventListener("click", close);
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    close();
  });

  const offSelection = selection?.subscribe && typeof resolve === "function"
    ? selection.subscribe((id) => {
        if (root.hidden || id == null) return;
        const resolved = resolve(id);
        if (resolved?.profile) setRobot(resolved.profile, resolved.detail);
      })
    : () => {};

  return {
    root,
    setRobot,
    focus() {
      title.focus();
    },
    dispose() {
      offSelection();
    },
  };
}
