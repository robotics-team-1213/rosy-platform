/**
 * C24 robot panel: non-modal left push column (>=64rem) or below-header sheet (<64rem) for one robot.
 * Shell only: head (name, abnormal link statusTag, close), ordered sections (status, camera, commands,
 * collapsible settings), and fixed stop footer (live stop button or note). No inline styling, no animation (D-220).
 *
 *   createRobotPanel({selection, onClose, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {})
 *     -> {root, setRobot(profile | null, detail?), focus(), dispose()}
 *     sections        {status, camera, commands, settings}, each (profile, detail) => Node | null
 *     stop            {label, onStop} | {note} | null, or (profile) => obj | null
 *     stopButton      static HTML emergency-stop <ui-button> passed from the page (D-371)
 *     links           {taskRow(taskId) -> url}: link builders each screen supplies (deep link to its work-screen task row); sections get them as the 3rd argument. A link is navigation, never a call; approve/resume happen on the work screen.
 *     resolve(id)     optional (id) => {profile, detail} | null; follows selection while open
 *     setRobot(...)   non-null opens/updates and focuses title on first open or robot switch; null hides
 *     focus()         moves focus to .robot-panel-title (tabindex=-1)
 *     dispose()       unsubscribes from selection
 */
import {statusTag} from "./status-tag.js";

let panelSerial = 0;

const SECTION_SPECS = [
  ["status", "상태"],
  ["camera", "카메라"],
  ["commands", "명령"],
  ["health", "모터 · 진단"],
  ["settings", "설정 · 장치"],
];

const JUMP_SPECS = [
  ["status", "상태"],
  ["camera", "카메라"],
  ["commands", "명령"],
  ["settings", "설정"],
];

export function createRobotPanel({selection, onClose, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {}) {
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

  const foot = document.createElement("footer");
  foot.className = "robot-panel-foot";
  foot.hidden = true;

  root.append(head, body, foot);

  let opener = null;
  let currentId = null;
  let activeStop = null;
  const fallbackStopBtn = document.createElement("ui-button");
  fallbackStopBtn.className = "robot-panel-stop";
  fallbackStopBtn.setAttribute("kind", "primary");
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

  function setRobot(profile, detail) {
    if (!profile) {
      root.hidden = true;
      root.removeAttribute("data-kind");
      root.removeAttribute("data-robot-id");
      title.textContent = "";
      linkSlot.replaceChildren();
      linkSlot.hidden = true;
      body.replaceChildren();
      foot.replaceChildren();
      foot.hidden = true;
      activeStop = null;
      if (stopButton) stopButton.hidden = true;
      currentId = null;
      opener = null;
      return;
    }

    const wasHidden = root.hidden;
    const prevId = currentId;
    const nextId = String(profile.id ?? "");
    if (wasHidden) opener = document.activeElement;
    currentId = nextId;

    root.dataset.kind = profile.kind || "";
    root.dataset.robotId = nextId;

    const displayName = profile.name || nextId;
    title.textContent = displayName;
    closeBtn.setAttribute("aria-label", `${displayName} 패널 닫기`);

    const linkState = profile.link?.state;
    if (linkState && linkState !== "fresh") {
      const tagState = linkState === "unavailable" ? "unknown" : linkState;
      linkSlot.replaceChildren(statusTag(tagState, profile.link.text));
      linkSlot.hidden = false;
    } else {
      linkSlot.replaceChildren();
      linkSlot.hidden = true;
    }

    body.replaceChildren();
    if (wasHidden || prevId !== nextId) body.scrollTop = 0;
    const presentSections = new Set();
    for (const [key, heading] of SECTION_SPECS) {
      const render = sections?.[key];
      const content = typeof render === "function" ? render(profile, detail, links) : null;
      if (content == null) continue;
      presentSections.add(key);
      if (key === "settings") {
        const details = document.createElement("details");
        details.className = "robot-panel-section";
        details.dataset.section = key;
        const summary = document.createElement("summary");
        summary.textContent = heading;
        details.append(summary, content);
        body.append(details);
      } else {
        const section = document.createElement("section");
        section.className = "robot-panel-section";
        section.dataset.section = key;
        const h3 = document.createElement("h3");
        h3.id = `robot-panel-sec-${panelId}-${key}`;
        h3.textContent = heading;
        section.setAttribute("aria-labelledby", h3.id);
        section.append(h3, content);
        body.append(section);
      }
    }
    const jumpTargets = JUMP_SPECS.filter(([key]) => presentSections.has(key));
    if (jumpTargets.length) {
      const jumpsNav = document.createElement("nav");
      jumpsNav.className = "robot-panel-jumps";
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
          if (key === "settings" && target.tagName === "DETAILS") target.open = true;
          target.scrollIntoView?.({block: "nearest"});
        });
        jumpsNav.append(btn);
      }
      body.prepend(jumpsNav);
    }

    foot.replaceChildren();
    activeStop = null;
    if (stopButton) stopButton.hidden = true;
    const stopSpec = typeof stop === "function" ? stop(profile) : stop;
    if (stopSpec?.label) {
      const stopBtn = ensureStopButton(stopSpec.button);
      stopBtn.hidden = false;
      stopBtn.textContent = stopSpec.label;
      activeStop = typeof stopSpec.onStop === "function" ? () => stopSpec.onStop(profile, detail) : null;
      foot.append(stopBtn);
      foot.hidden = false;
    } else if (stopSpec?.note) {
      const note = document.createElement("p");
      note.className = "robot-panel-stop-note";
      note.textContent = stopSpec.note;
      foot.append(note);
      foot.hidden = false;
    } else {
      foot.hidden = true;
    }

    root.hidden = false;
    if (wasHidden || prevId !== nextId) title.focus();
  }

  function close() {
    if (root.hidden) return;
    const back = opener;
    setRobot(null);
    if (back?.isConnected && typeof back.focus === "function") back.focus();
    onClose?.();
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
