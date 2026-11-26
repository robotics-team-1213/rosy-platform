/**
 * C24 robot panel: non-modal left push column (>=64rem) or below-header sheet (<64rem) for one robot.
 * Shell only: head (name, abnormal link statusTag, close), fixed jumps slot (section shortcuts, never scrolls),
 * scrolling body of ordered sections (status, camera, commands, collapsible manual controls & settings),
 * and fixed stop footer (live stop button or note). No inline styling, no animation (D-220).
 *
 *   createRobotPanel({selection, onClose, onManualCollapse, onCameraCollapse, locate = null, sectionHeadings = null, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {})
 *     -> {root, setRobot(profile | null, detail?, opts?), focus(), dispose()}
 *     sections        {status, camera, commands, manual, health, settings}, each (profile, detail) => Node | null
 *     onManualCollapse called when the manual <details> section collapses
 *     onCameraCollapse called when the camera <details> section collapses
 *     locate          (profile, detail) => fn | {label?, onLocate} | null, or static object/fn; drives the persistent place strip button
 *     sectionHeadings {key: heading} or (profile, detail) => {key: heading}; overrides default section headings
 *     stop            {label, onStop} | {note} | null, or (profile) => obj | null
 *     stopButton      static HTML emergency-stop <ui-button> passed from the page (D-371)
 *     links           {taskRow(taskId) -> url}: link builders each screen supplies (deep link to its work-screen task row); sections get them as the 3rd argument. A link is navigation, never a call; approve/resume happen on the work screen.
 *     resolve(id)     optional (id) => {profile, detail} | null; follows selection while open
 *     setRobot(...)   non-null opens/updates and focuses title on first open, robot switch, or {force: true};
 *                     same-id updates patch head, freshness, changed sections, and footer in place; null hides
 *     focus()         moves focus to .robot-panel-title (tabindex=-1)
 *     dispose()       unsubscribes from selection
 */
import {actionIcon, iconSvg} from "/common/ui.js";
import {patchAttr, patchData, patchHidden, patchText} from "/common/control-dom.js";
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
  ["status", "상태", "robot"],
  ["camera", "카메라", "image"],
  ["commands", "명령", "next"],
  ["manual", "수동 조종", "hand"],
  ["health", "모터 · 진단", "tools"],
  ["settings", "설정 · 장치", "settings"],
];

const JUMP_SPECS = [
  ["status", "상태"],
  ["camera", "카메라"],
  ["commands", "명령"],
  ["health", "모터"],
  ["manual", "수동"],
  ["settings", "설정"],
];

export function createRobotPanel({selection, onClose, onManualCollapse, onCameraCollapse, locate = null, sectionHeadings = null, sections = {}, stop = null, stopButton = null, resolve, links = {}} = {}) {
  const panelId = ++panelSerial;
  const root = document.createElement("aside");
  root.className = "robot-panel";
  root.hidden = true;

  const head = document.createElement("header");
  head.className = "robot-panel-head";

  const kindTag = document.createElement("ui-tag");
  kindTag.className = "robot-panel-kind";
  kindTag.setAttribute("status", "neutral");
  kindTag.setAttribute("variant", "inline");
  kindTag.hidden = true;

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
  closeBtn.setAttribute("kind", "segment");
  closeBtn.setAttribute("type", "button");
  closeBtn.textContent = "닫기";

  head.append(kindTag, title, linkSlot, closeBtn);

  const placeBar = document.createElement("div");
  placeBar.className = "robot-panel-place";
  placeBar.hidden = true;

  const placeLabel = document.createElement("span");
  placeLabel.className = "robot-panel-place-label";
  placeLabel.textContent = "위치";

  const placeText = document.createElement("span");
  placeText.className = "robot-panel-place-text";

  const locateBtn = document.createElement("ui-button");
  locateBtn.setAttribute("kind", "quiet");
  locateBtn.setAttribute("type", "button");
  locateBtn.className = "robot-panel-locate";
  locateBtn.textContent = "지도 보기";
  locateBtn.hidden = true;

  placeBar.append(placeLabel, placeText, locateBtn);

  const body = document.createElement("div");
  body.className = "robot-panel-body";

  const foot = document.createElement("div");
  foot.className = "robot-panel-foot";
  foot.hidden = true;

  root.append(head, placeBar, body, foot);

  let opener = null;
  let currentId = null;
  let activeLocate = null;
  let activeStop = null;
  let closing = false;
  const sectionMap = new Map();
  let jumpsNav = null;
  let footerMode = null;
  let footerNoteEl = null;
  locateBtn.addEventListener("click", () => activeLocate?.());
  const fallbackStopBtn = document.createElement("ui-button");
  fallbackStopBtn.className = "robot-panel-stop";
  fallbackStopBtn.setAttribute("kind", "quiet");
  fallbackStopBtn.setAttribute("type", "button");
  fallbackStopBtn.setAttribute("data-always-live", "");
  const boundButtons = new WeakSet();
  const ensureStopButton = (btn) => {
    const target = btn || stopButton || fallbackStopBtn;
    if (!target.classList.contains("robot-panel-stop")) target.classList.add("robot-panel-stop");
    patchAttr(target, "type", "button");
    patchAttr(target, "data-always-live", "");
    if (!boundButtons.has(target)) {
      boundButtons.add(target);
      target.addEventListener("click", () => activeStop?.());
    }
    return target;
  };

  function setHeading(host, text, icon) {
    const wrap = document.createElement("span"), label = document.createElement("span"), svg = icon ? iconSvg(icon) : null;
    wrap.className = "robot-panel-sec-title"; label.textContent = text;
    wrap.append(...(svg ? [svg] : []), label); host.append(wrap); return label;
  }
  function makeSectionWrapper(key, heading, content, icon) {
    if (key === "settings" || key === "manual" || key === "camera") {
      const details = document.createElement("details");
      details.className = "robot-panel-section";
      details.dataset.section = key;
      if (key === "camera") {
        details.open = typeof window !== "undefined" && window.innerHeight > 800;
        details.addEventListener("toggle", () => {
          if (!details.open) onCameraCollapse?.();
        });
      }
      const summary = document.createElement("summary");
      const headingEl = setHeading(summary, heading, icon);
      details.append(summary, content);
      if (key === "manual") {
        details.addEventListener("toggle", () => {
          if (details.open) details.scrollIntoView?.({block: "end"});
          else onManualCollapse?.();
        });
      }
      return {wrapper: details, headingEl};
    }
    const section = document.createElement("section");
    section.className = "robot-panel-section";
    section.dataset.section = key;
    const h3 = document.createElement("h3");
    h3.id = `robot-panel-sec-${panelId}-${key}`;
    const headingEl = setHeading(h3, heading, icon);
    section.setAttribute("aria-labelledby", h3.id);
    section.append(h3, content);
    return {wrapper: section, headingEl};
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
    root.insertBefore(jumpsNav, body);  // fixed slot between head and body: the body scrolls under it, not behind it
  }

  function setRobot(profile, detail, {force = false} = {}) {
    if (!profile) {
      root.hidden = true;
      root.removeAttribute("data-kind");
      root.removeAttribute("data-robot-id");
      patchText(kindTag, "");
      patchHidden(kindTag, true);
      title.textContent = "";
      linkSlot.replaceChildren();
      linkSlot.hidden = true;
      patchText(placeText, "");
      patchHidden(placeBar, true);
      activeLocate = null;
      patchHidden(locateBtn, true);
      body.replaceChildren();
      sectionMap.clear();
      jumpsNav?.remove();
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

    patchData(root, "kind", profile.kind || "");
    patchData(root, "robotId", nextId);

    patchText(kindTag, profile.kindLabel || "");
    patchHidden(kindTag, !profile.kindLabel);

    const displayName = profile.name || nextId;
    patchText(title, displayName);
    patchAttr(closeBtn, "aria-label", `${displayName} 패널 닫기`);

    const linkState = profile.link?.state;
    if (linkState && linkState !== "fresh") {
      const tagState = linkState === "unavailable" ? "unknown" : linkState;
      const linkText = profile.link.text || "";
      if (linkSlot.dataset.tagState !== tagState || linkSlot.dataset.tagText !== linkText || linkSlot.hidden) {
        linkSlot.dataset.tagState = tagState;
        linkSlot.dataset.tagText = linkText;
        linkSlot.replaceChildren(statusTag(tagState, profile.link.text));
        patchHidden(linkSlot, false);
      }
    } else if (!linkSlot.hidden || linkSlot.childElementCount) {
      patchData(linkSlot, "tagState", null);
      patchData(linkSlot, "tagText", null);
      if (linkSlot.childElementCount) linkSlot.replaceChildren();
      patchHidden(linkSlot, true);
    }

    patchText(placeText, profile.place?.text || EVIDENCE_LABEL.unavailable);
    patchHidden(placeBar, false);
    const locateSpec = typeof locate === "function" ? locate(profile, detail) : locate;
    if (typeof locateSpec === "function") {
      activeLocate = () => locateSpec(profile, detail);
      patchText(locateBtn, "지도 보기");
      patchAttr(locateBtn, "aria-label", `${displayName} 지도에서 보기`);
      patchHidden(locateBtn, false);
    } else if (locateSpec && typeof locateSpec.onLocate === "function") {
      activeLocate = () => locateSpec.onLocate(profile, detail);
      patchText(locateBtn, locateSpec.label || "지도 보기");
      patchAttr(locateBtn, "aria-label", `${displayName} 지도에서 보기`);
      patchHidden(locateBtn, false);
    } else {
      activeLocate = null;
      patchHidden(locateBtn, true);
    }

    if (!sameId) {
      body.replaceChildren();
      sectionMap.clear();
      jumpsNav?.remove();
      jumpsNav = null;
      body.scrollTop = 0;
    }

    const headingsSpec = typeof sectionHeadings === "function" ? sectionHeadings(profile, detail) : sectionHeadings;
    const presentSections = new Set();
    const desiredNodes = [];
    for (const [key, defaultHeading, icon] of SECTION_SPECS) {
      const heading = headingsSpec?.[key] || defaultHeading;
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
        patchText(existing.headingEl, heading);
        if (content !== existing.content) {
          existing.content.replaceWith(content);
          existing.content = content;
        }
        desiredNodes.push(existing.wrapper);
      } else {
        const {wrapper, headingEl} = makeSectionWrapper(key, heading, content, icon);
        sectionMap.set(key, {wrapper, content, headingEl});
        desiredNodes.push(wrapper);
      }
    }

    syncJumps(presentSections);
    desiredNodes.forEach((node, index) => {
      const at = body.children[index];
      if (at !== node) body.insertBefore(node, at || null);
    });

    activeStop = null;
    if (stopButton && footerMode !== "btn") patchHidden(stopButton, true);
    const stopSpec = typeof stop === "function" ? stop(profile) : stop;
    if (stopSpec?.label) {
      const stopBtn = ensureStopButton(stopSpec.button);
      activeStop = typeof stopSpec.onStop === "function" ? () => stopSpec.onStop(profile, detail) : null;
      if (footerMode !== "btn" || stopBtn.parentElement !== foot) {
        foot.replaceChildren(stopBtn);
        footerMode = "btn";
        footerNoteEl = null;
      }
      patchHidden(stopBtn, false);
      patchText(stopBtn, stopSpec.label);
      patchHidden(foot, false);
    } else if (stopSpec?.note) {
      if (stopButton) patchHidden(stopButton, true);
      if (footerMode !== "note" || !footerNoteEl) {
        footerNoteEl = document.createElement("p");
        footerNoteEl.className = "robot-panel-stop-note";
        foot.replaceChildren(footerNoteEl);
        footerMode = "note";
      }
      patchText(footerNoteEl, stopSpec.note);
      patchHidden(foot, false);
    } else {
      if (stopButton) patchHidden(stopButton, true);
      if (foot.childElementCount || !foot.hidden) {
        if (foot.childElementCount) foot.replaceChildren();
        patchHidden(foot, true);
      }
      footerMode = null;
      footerNoteEl = null;
    }

    patchHidden(root, false);
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
