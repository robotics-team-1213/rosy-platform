// Console stage binding for C23 robot dock + C24 robot panel (Pinky and OMX arms).
import { createRobotDock } from "/common/robot-dock.js";
import { createRobotPanel } from "/common/robot-panel.js";
import { createRobotRoster } from "/common/robot-row.js";
import { statusTag } from "/common/status-tag.js";
import {
  ARM_STOP_NOTE,
  buildArmSections,
  buildDockEntries,
  summarizeFleetProfiles,
} from "./robot-panel-adapters.js";
import {
  armSignatures,
  captureFocusIn,
  pinkyCommandsSig,
  pinkyStatusSig,
  refreshPinkyAges,
  restoreFocus,
} from "./roster-presentation.js";
import { sortProblemsFirst } from "./overview-order.js";
import { quietRowTexts } from "/common/core_ui_logic.js";

const OVERVIEW_GROUPS = [
  ["mobile", "이동로봇"],
  ["arm", "로봇암"],
];

function node(tag, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  return element;
}

function replaceSectionContent(host, nextNode) {
  if (!host) return;
  if (!nextNode) { host.replaceChildren(); return; }
  host.replaceChildren(nextNode);
}

export function createRobotDockBinding({
  scope, el, view, call, roster, manualControl, assistant, onOpen = null, isOperator, namedReason, refresh, render,
}) {
  const dockMount = el("robot-dock-mount");
  const panelMount = el("robot-panel-mount");
  const stopButton = el("robot-panel-stop");
  if (!dockMount || !panelMount) {
    return { sync() {}, close() {}, dock: null, panel: null };
  }

  const armSections = buildArmSections({ call, view, isOperator, namedReason, refresh, scope });
  let entries = [];
  let renderedId = null;
  let activeCameraDispose = null;
  let pinkyStopFn = null;
  let pinkyStopDisabled = true;
  let lastPinkyStatusSig = null;
  let lastPinkyCommandsSig = null;
  let lastArmStatusSig = null;
  let lastArmSettingsSig = null;
  let lastOverviewSig = null;
  let lastOverviewSelected = undefined;
  let lastGridSig = null;
  let activeOverviewRoster = null;

  // Persistent per-section wrappers keep the live camera stream, .motor-health table,
  // and open disclosures untouched across 1s Fleet telemetry refreshes for the same robot.
  const wraps = {
    status: node("div", "robot-panel-wrap"),
    statusBody: node("div", "robot-panel-wrap"),
    manual: node("details", "robot-panel-manual"),
    camera: node("div", "robot-panel-wrap"),
    health: node("div", "robot-panel-wrap"),
    commands: node("div", "robot-panel-wrap"),
    settings: node("div", "robot-panel-wrap"),
  };
  // 수동 조종: 닫힌 채 시작하는 접힘 구획(화면 명세 3절). 요약 줄이 잠금 사유를 한 줄로 말한다.
  const manualSummary = node("summary", "ui-disclosure-row");
  const manualLock = node("small", "robot-panel-manual-lock");
  manualSummary.append("수동 조종", manualLock);
  wraps.manual.hidden = true;
  wraps.manual.append(manualSummary);
  wraps.status.append(wraps.statusBody, wraps.manual);

  function setManualMounted(on) {
    wraps.manual.hidden = !on;
    const root = manualControl?.root;
    if (!on || !root) { root?.remove(); return; }
    if (root.parentNode !== wraps.manual) wraps.manual.append(root);
  }
  function paintManualLock(entry) {
    const robot = entry?.robot;
    const why = robot && robot.capabilities?.teleop !== true ? "이 로봇은 수동 조종을 지원하지 않습니다." : "";
    if (manualLock.textContent !== why) manualLock.textContent = why;
  }

  function disposeCamera() {
    if (activeCameraDispose) {
      try { activeCameraDispose(); } catch (_err) { /* ignore cleanup race */ }
      activeCameraDispose = null;
    }
    wraps.camera.replaceChildren();
    roster.clear3d?.();
    lastPinkyStatusSig = null;
    lastPinkyCommandsSig = null;
    lastArmStatusSig = null;
    lastArmSettingsSig = null;
  }

  function buildPinkyParts(robotId, { withManual = false } = {}) {
    const idx = Math.max(0, (view.robots || []).findIndex((r) => r.robot_id === robotId));
    const robot = (view.robots || [])[idx];
    if (!robot) return null;
    return roster.card(robot, idx, { split: true, manualRoot: withManual ? (manualControl?.root || null) : null });
  }

  function updatePanelHeadAndStop(profile, stopSpec) {
    const linkSlot = panel.root.querySelector(".robot-panel-link");
    const link = profile?.link;
    if (linkSlot) {
      if (link && link.state !== "fresh" && link.text) {
        const tagState = link.state === "delayed" ? "delayed" : link.state === "disconnected" ? "disconnected" : "unknown";
        const linkSig = `${tagState}:${link.text}`;
        if (linkSlot.dataset.linkSig !== linkSig) {
          linkSlot.dataset.linkSig = linkSig;
          linkSlot.replaceChildren(statusTag(tagState, link.text, tagState === "disconnected" ? { danger: true } : undefined));
        }
        linkSlot.hidden = false;
      } else {
        if (linkSlot.dataset.linkSig) {
          delete linkSlot.dataset.linkSig;
          linkSlot.replaceChildren();
        }
        linkSlot.hidden = true;
      }
    }
    if (stopButton && stopSpec && "disabled" in stopSpec) {
      stopButton.disabled = Boolean(stopSpec.disabled);
      if (stopButton.disabled) stopButton.setAttribute("reason", stopSpec.reason || "정지 명령을 보낼 수 없습니다");
      else stopButton.removeAttribute("reason");
    }
  }

  function paintSections(entry, { fresh }) {
    const id = entry.profile.id;
    const isArm = Boolean(entry.detail?.def) && !entry.robot;
    if (isArm) {
      pinkyStopFn = null;
      lastPinkyStatusSig = null;
      lastPinkyCommandsSig = null;
      const savedCmdFocus = fresh ? null : captureFocusIn(wraps.commands);
      const { statusSig, settingsSig } = armSignatures(id, entry.detail, { isOperator, namedReason });
      if (fresh) {
        setManualMounted(false);
        wraps.health.replaceChildren();
      }
      if (fresh || lastArmStatusSig !== statusSig || !wraps.statusBody.firstElementChild) {
        lastArmStatusSig = statusSig;
        replaceSectionContent(wraps.statusBody, armSections.status(entry.profile, entry.detail));
      }
      const curCmd = wraps.commands.firstElementChild;
      const nextCmdSig = armSections.commandsSig(entry.profile, entry.detail);
      const keepCmd = !fresh && curCmd && (curCmd.dataset.armCmdBusy === "1" || curCmd.dataset.armCmdSig === nextCmdSig);
      if (!keepCmd) replaceSectionContent(wraps.commands, armSections.commands(entry.profile, entry.detail, links));
      if (fresh || lastArmSettingsSig !== settingsSig || !wraps.settings.firstElementChild) {
        lastArmSettingsSig = settingsSig;
        replaceSectionContent(wraps.settings, armSections.settings(entry.profile, entry.detail));
      }
      restoreFocus(wraps.commands, savedCmdFocus);
      if (fresh) {
        const camNode = armSections.camera(entry.profile, entry.detail);
        replaceSectionContent(wraps.camera, camNode);
        activeCameraDispose = camNode?._disposeCamera || null;
      }
      return { wraps };
    }

    lastArmStatusSig = null;
    lastArmSettingsSig = null;
    const nowMs = Date.now();
    const index = Math.max(0, (view.robots || []).findIndex((r) => r.robot_id === id));
    const profileVer = roster.profileVersion?.() || 0;
    const statusSig = pinkyStatusSig(entry, view, { isOperator, namedReason, profileVer, index }, nowMs);
    const commandsSig = pinkyCommandsSig(entry, view, { isOperator, namedReason });
    const activeEl = typeof document !== "undefined" ? document.activeElement : null;
    const cmdFocused = fresh ? null : captureFocusIn(wraps.commands);
    const inCommands = Boolean(activeEl && wraps.commands.contains(activeEl));
    const inManual = Boolean(activeEl && wraps.manual.contains(activeEl));
    const focusedTrip = inCommands && activeEl?.tagName === "SELECT" ? activeEl.closest(".card-trip") : null;
    const holdingControl = Boolean(
      wraps.manual.querySelector('[data-manual-direction][aria-pressed="true"]')
      || (inManual && activeEl?.matches?.("[data-manual-direction], [data-manual-mode], [data-manual-speed]"))
      || (cmdFocused && inCommands && (activeEl?.tagName === "SELECT" || activeEl?.matches?.("[data-step-direction]"))),
    );
    const statusChanged = fresh || statusSig !== lastPinkyStatusSig || !wraps.statusBody.firstElementChild;
    const commandsChanged = fresh || ((!holdingControl || focusedTrip) && commandsSig !== lastPinkyCommandsSig) || !wraps.commands.firstElementChild;
    if (!fresh && !statusChanged) roster.syncProfile?.(id);
    if (!statusChanged && !commandsChanged) {
      refreshPinkyAges(wraps.statusBody.firstElementChild, entry.robot, view, nowMs);
      return { stopSpec: { disabled: pinkyStopDisabled } };
    }

    const parts = buildPinkyParts(id, { withManual: false });
    if (!parts) return null;
    pinkyStopFn = parts.stop?.onStop || null;
    pinkyStopDisabled = Boolean(parts.stop?.disabled);
    function mountManual() {
      // Mount manual-control pad directly after status/profile so 2x2 teleop fits above the 768px fold while camera precedes .robot-actions.
      setManualMounted(Boolean(manualControl?.root));
    }
    if (fresh) {
      lastPinkyStatusSig = statusSig;
      lastPinkyCommandsSig = commandsSig;
      replaceSectionContent(wraps.statusBody, parts.status);
      mountManual();
      replaceSectionContent(wraps.camera, parts.camera);
      activeCameraDispose = parts.camera?._disposeCamera || null;
      replaceSectionContent(wraps.health, parts.health);
      replaceSectionContent(wraps.commands, parts.commands);
      replaceSectionContent(wraps.settings, parts.settings);
    } else {
      if (statusChanged) {
        lastPinkyStatusSig = statusSig;
        roster.place(wraps.statusBody, parts.status ? [parts.status] : []);
      } else {
        refreshPinkyAges(wraps.statusBody.firstElementChild, entry.robot, view, nowMs);
      }
      if (focusedTrip) {
        const nextTrip = parts.commands?.querySelector?.(".card-trip");
        if (nextTrip && commandsSig !== lastPinkyCommandsSig) {
          const oldNote = focusedTrip.querySelector(".stuck-result");
          const nextNote = nextTrip.querySelector(".stuck-result");
          if (oldNote && nextNote) {
            oldNote.textContent = nextNote.textContent;
            oldNote.hidden = nextNote.hidden;
          } else if (!oldNote && nextNote) {
            focusedTrip.append(nextNote);
          } else if (oldNote && !nextNote) {
            oldNote.remove();
          }
          lastPinkyCommandsSig = commandsSig;
        }
      } else if (commandsChanged) {
        lastPinkyCommandsSig = commandsSig;
        replaceSectionContent(wraps.commands, parts.commands);
        restoreFocus(wraps.commands, cmdFocused);
      }
    }
    return { stopSpec: parts.stop };
  }

  const links = {
    taskRow: (taskId) => (taskId ? `/console?view=work&task=${encodeURIComponent(taskId)}` : "/console?view=work#work-overview"),
  };

  let dock = null;
  const panel = createRobotPanel({
    selection: view.robotSelection,
    stopButton,
    links,
    onClose: () => {
      dock?.setOpen(null);
      disposeCamera();
      armSections.reset?.();
      renderedId = null;
      if (view.robotSelection?.get()) view.robotSelection.set(null, { source: "panel-close" });
    },
    sections: {
      status: () => wraps.status,
      camera: () => wraps.camera,
      health: () => (wraps.health.childElementCount ? wraps.health : null),
      commands: () => wraps.commands,
      settings: () => wraps.settings,
    },
    stop: (profile) => {
      const entry = profile?.id ? entries.find((e) => e.profile.id === profile.id) : null;
      return entry?.detail?.def && !entry?.robot
        ? { note: ARM_STOP_NOTE }
        : { label: "주행 취소 · 이 로봇", button: stopButton, onStop: () => pinkyStopFn?.() };
    },
  });

  dock = createRobotDock({
    selection: view.robotSelection,
    onToggle: (id) => {
      if (!id) {
        disposeCamera();
        armSections.reset?.();
        renderedId = null;
        panel.setRobot(null);
        if (view.robotSelection?.get()) view.robotSelection.set(null, { source: "dock" });
        return;
      }
      onOpen?.();
      assistant?.close?.({ restoreFocus: false });
      const found = entries.find((e) => e.profile.id === id) || null;
      if (!found) { panel.setRobot(null); renderedId = null; return; }
      openEntry(found);
    },
  });

  panel.root.id = "robot-panel-mount";
  dock.root.id = "robot-dock-mount";
  dock.root.setAttribute("aria-label", "로봇 선택 도크");
  panelMount.replaceWith(panel.root);
  dockMount.replaceWith(dock.root);

  function openEntry(entry) {
    const id = entry.profile.id;
    const isFresh = renderedId !== id;
    if (isFresh) disposeCamera();
    const res = paintSections(entry, { fresh: isFresh });
    if (isFresh) wraps.manual.open = false;
    paintManualLock(entry);
    if (isFresh) {
      renderedId = id;
      panel.setRobot(entry.profile, entry.detail);
    }
    updatePanelHeadAndStop(entry.profile, res?.stopSpec || (entry.profile.kind === "mobile" ? { disabled: pinkyStopDisabled } : null));
  }

  function close() {
    disposeCamera();
    armSections.reset?.();
    renderedId = null;
    dock.setOpen(null);
    panel.setRobot(null);
    if (view.robotSelection?.get()) view.robotSelection.set(null, { source: "dock-close" });
  }

  function paintOverviewPressed(host, selectedId) {
    if (!host) return;
    lastOverviewSelected = selectedId;
    for (const item of host.querySelectorAll(".robot-overview-item")) {
      item.setAttribute("aria-pressed", String(item.dataset.robotId === selectedId));
    }
  }

  function renderOverviewList(unsortedEntries, selectedId) {
    const currentEntries = sortProblemsFirst(unsortedEntries, (r) => roster.needsAttention(r) || view.stateUnavailable);
    const host = el("robot-overview-list");
    if (!host) return;
    const sig = JSON.stringify([
      Boolean(view.stateUnavailable),
      currentEntries.map(({ profile }) => [
        profile.id, profile.kind, profile.name,
        profile.link.state, profile.link.text,
        profile.power.text, profile.place.text, profile.task.text,
        profile.alarm?.tag || null, profile.alarm?.text || null, profile.alarm?.icon || null,
      ]),
    ]);
    if (sig === lastOverviewSig && host.childElementCount > 0) {
      if (lastOverviewSelected !== selectedId) paintOverviewPressed(host, selectedId);
      return;
    }
    const active = typeof document !== "undefined" ? document.activeElement : null;
    const focusedRobotId = active && host.contains(active)
      ? active.closest?.(".robot-overview-item")?.dataset?.robotId || null
      : null;
    const children = [];
    if (!currentEntries.length) {
      const empty = node("p", "hint");
      empty.textContent = view.stateUnavailable ? "Fleet 상태 확인 불가" : "등록된 로봇 없음";
      children.push(empty);
    } else {
      for (const [kind, label] of OVERVIEW_GROUPS) {
        const groupEntries = currentEntries.filter((e) => e.profile.kind === kind);
        if (!groupEntries.length) continue;
        const section = node("section", "robot-overview-group");
        section.dataset.kind = kind;
        const title = node("h3", "robot-overview-group-title");
        title.textContent = `${label} (${groupEntries.length})`;
        const list = node("div", "robot-overview-items");
        for (const { profile } of groupEntries) {
          const btn = node("button", "robot-overview-item");
          btn.type = "button";
          btn.dataset.robotId = profile.id;
          btn.dataset.kind = profile.kind;
          btn.setAttribute("aria-pressed", String(selectedId === profile.id));
          btn.addEventListener("click", () => {
            const current = view.robotSelection?.get?.() ?? null;
            view.robotSelection?.set?.(profile.id === current ? null : profile.id, { source: "overview" });
          });

          const head = node("span", "robot-overview-head");
          const nameWrap = node("span", "robot-overview-name");
          const nameText = node("strong", "");
          nameText.textContent = profile.name;
          nameWrap.append(nameText);
          if (!profile.name.includes(profile.id)) {
            const idText = node("small", "robot-overview-id");
            idText.textContent = profile.id;
            nameWrap.append(idText);
          }
          const tags = node("span", "robot-overview-tags");
          if (profile.link.state === "fresh" && !profile.alarm) {
            // 정상 수신(최신)은 가시 칩 없이 낱독어만 남긴다. 지연·끊김·미수신은 아래 가시 칩 그대로다.
            const fresh = node("span", "sr-only");
            fresh.textContent = profile.link.text;
            tags.append(fresh);
          } else {
            if (profile.link.state !== "fresh") {
              const linkState = profile.link.state === "unavailable" ? "unknown" : profile.link.state;
              tags.append(statusTag(linkState, profile.link.text, linkState === "disconnected" ? { danger: true } : undefined));
            }
            if (profile.alarm) {
              tags.append(statusTag(profile.alarm.tag, profile.alarm.text, profile.alarm.icon ? { icon: profile.alarm.icon } : undefined));
            }
          }
          head.append(nameWrap, tags);

          const meta = node("span", "robot-overview-meta");
          const task = node("span", "robot-overview-task");
          // 조용한 행(robot-row.js와 같은 규칙): 알 수 없음은 행에 한 번만(D-280), 지연 나이는 연결 태그와
          // 같은 나이일 때만 뺀다. 칸 나이가 다르면 그 칸의 사실이므로 남는다.
          const [powerText, placeText, taskText] = quietRowTexts(profile.link, [
            profile.power.text,
            profile.place.text,
            profile.task.text,
          ]);
          meta.textContent = [powerText, placeText].filter(Boolean).join(" · ");
          task.textContent = taskText;
          btn.append(head, meta, task);
          list.append(btn);
        }
        section.append(title, list);
        children.push(section);
      }
    }
    host.replaceChildren(...children);
    lastOverviewSig = sig;
    lastOverviewSelected = selectedId;
    if (focusedRobotId) {
      const target = [...host.querySelectorAll(".robot-overview-item")].find((b) => b.dataset.robotId === focusedRobotId);
      target?.focus?.({ preventScroll: true });
    }
  }

  function syncOverviewGrid(currentEntries) {
    const screen = el("robots-overview");
    const grid = el("robots-overview-grid");
    if (!screen || screen.hidden || !grid) {
      if (activeOverviewRoster) {
        activeOverviewRoster.dispose?.();
        activeOverviewRoster = null;
        lastGridSig = null;
      }
      return;
    }
    const profiles = currentEntries.map((e) => (
      typeof e.profile.detail === "string" || e.profile.detail == null
        ? e.profile
        : { ...e.profile, detail: null }
    ));
    const sig = JSON.stringify(profiles.map((p) => [
      p.id, p.name, p.kind, p.link, p.power, p.task, p.place, p.alarm,
      typeof p.detail === "string" ? p.detail : "",
    ]));
    if (sig === lastGridSig && grid.firstElementChild) return;
    const active = typeof document !== "undefined" ? document.activeElement : null;
    const focusedSelectId = active && grid.contains(active) ? active.dataset?.selectRobotId || null : null;
    activeOverviewRoster?.dispose?.();
    activeOverviewRoster = createRobotRoster(profiles, { selection: view.robotSelection });
    grid.replaceChildren(activeOverviewRoster);
    lastGridSig = sig;
    if (focusedSelectId) {
      const target = [...grid.querySelectorAll("[data-select-robot-id]")].find((b) => b.dataset.selectRobotId === focusedSelectId);
      target?.focus?.({ preventScroll: true });
    }
  }

  function sync() {
    entries = buildDockEntries(view, view.chargeBaysPlan);
    dock.setProfiles(entries.map((e) => e.profile));
    const summaryEl = el("roster-summary");
    if (summaryEl) {
      const nextSummary = entries.length
        ? summarizeFleetProfiles(entries)
        : (view.stateUnavailable ? "Fleet 상태 확인 불가" : "등록된 로봇 없음");
      if (summaryEl.textContent !== nextSummary) summaryEl.textContent = nextSummary;
    }
    const targetId = view.robotSelection?.get() ?? null;
    renderOverviewList(entries, targetId);
    syncOverviewGrid(entries);
    if (!targetId) {
      if (renderedId || !panel.root.hidden) close();
      return;
    }
    const found = entries.find((e) => e.profile.id === targetId) || null;
    if (!found) {
      if (renderedId) close();
      return;
    }
    if (renderedId !== targetId || !panel.root.hidden) {
      dock.setOpen(targetId);
      openEntry(found);
    }
  }

  scope?.onDispose?.(view.robotSelection.subscribe((id, meta) => {
    paintOverviewPressed(el("robot-overview-list"), id ?? null);
    if (!id) {
      close();
      return;
    }
    if (meta?.source === "dock") return;
    onOpen?.();
    assistant?.close?.({ restoreFocus: false });
    dock.setOpen(id);
    const found = entries.find((e) => e.profile.id === id) || null;
    if (found) openEntry(found);
  }));

  // Pin mode gets first crack at Escape so disarming a pin never accidentally dismisses the open panel.
  const onKeyDownCapture = (event) => {
    if (event.key !== "Escape" || !view.pinning) return;
    const robotId = view.pinning;
    event.preventDefault();
    event.stopPropagation();
    view.pinning = null;
    render?.();
    const mount = el("robot-panel-mount");
    if (mount && !mount.hidden) {
      const target = mount.querySelector(`[data-pin-robot-id="${CSS.escape(robotId)}"]`)
        || mount.querySelector(".robot-panel-close, button, ui-button")
        || mount;
      target?.focus?.({ preventScroll: true });
    }
  };
  if (typeof window !== "undefined") {
    window.addEventListener("keydown", onKeyDownCapture, true);
    scope?.onDispose?.(() => window.removeEventListener("keydown", onKeyDownCapture, true));
  }
  scope?.onDispose?.(() => {
    disposeCamera();
    activeOverviewRoster?.dispose?.();
    activeOverviewRoster = null;
  });

  return { sync, close, dock, panel };
}
