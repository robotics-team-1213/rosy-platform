/**
 * Fleet cockpit C23 right robot dock + C24 left push/sheet robot panel adapter.
 * Connects the shared selection store (C18) with mobile robots and observed OMX arms.
 */
import { createRobotDock } from "/common/robot-dock.js";
import { createRobotPanel } from "/common/robot-panel.js";
import { robotProfile } from "/common/robot-profile.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { setOff } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";
import { cardTripLine } from "./card-trip.js";
import { OMX_CELL_DEFS, createFrontCamera } from "./roster-cards.js";
import { powerHealthView } from "./power-health-view.js";
import { staleAgeS } from "./state-age.js";

function readBatteryPercent(robot, state) {
  const pct = state.battery?.percent;
  if (typeof pct === "number" && Number.isFinite(pct)) return pct;
  const frac = state.battery?.percentage;
  if (typeof frac === "number" && Number.isFinite(frac)) return frac <= 1 ? frac * 100 : frac;
  const shown = state.battery_status?.shown_percent ?? robot.power_health?.battery?.percent;
  return typeof shown === "number" && Number.isFinite(shown) ? shown : null;
}

function appendKv(dl, rows) {
  const nodes = [];
  for (const [label, value] of rows) {
    nodes.push(node("dt", label), node("dd", value || EVIDENCE_LABEL.unavailable));
  }
  dl.replaceChildren(...nodes);
}

export function createRosterWorkspace({ scope, el, view, auth, selection, call, render, roster, manualControl }) {
  const stage = el("robot-stage");
  const frontCamera = createFrontCamera({ call, scope });
  const workspaceBox = document.createElement("div");
  workspaceBox.id = "robot-workspace";
  workspaceBox.setAttribute("aria-label", "선택한 로봇의 작업");

  const cameraBox = document.createElement("div");
  cameraBox.className = "robot-panel-camera-box";
  const cameraToggle = document.createElement("ui-button");
  cameraToggle.setAttribute("kind", "toggle");
  cameraToggle.setAttribute("data-work-read", "");
  cameraToggle.type = "button";
  cameraToggle.textContent = "전면 카메라";
  const armCameraHint = node("p", "팔 카메라는 작업 화면(셀)에서 확인합니다.", "hint");
  const armStatusBox = document.createElement("dl");
  armStatusBox.className = "robot-panel-kv";
  const armCommandsBox = document.createElement("div");
  armCommandsBox.className = "ui-control-stack";
  armCommandsBox.append(node("p", "로봇팔 작업 준비와 승인은 작업 화면(셀)에서 진행합니다.", "hint"));
  const armWorkLink = node("a", "팔레트 적재 화면 열기", "ui-action-link");
  armWorkLink.dataset.kind = "quiet";
  armWorkLink.href = "/console/cell";
  armCommandsBox.append(armWorkLink);
  const settingsBox = document.createElement("dl");
  settingsBox.className = "robot-panel-kv";

  let latestRecords = [];
  let openId = null;
  let yieldedForGoal = false;

  const isWide = () => typeof matchMedia !== "function" || matchMedia("(min-width: 64rem)").matches;

  function buildRecords() {
    if (auth.locked) return [];
    const now = Date.now();
    const mobile = view.robots.map((robot) => {
      const state = view.stateUnavailable ? {} : (robot.state || {});
      const power = powerHealthView(robot, view.receivedAtMs, now);
      const staleS = staleAgeS(robot, view.receivedAtMs, now);
      const ageS = typeof robot.state_age_s === "number" && Number.isFinite(robot.state_age_s)
        ? robot.state_age_s + Math.max(0, (now - (view.receivedAtMs ?? now)) / 1000)
        : undefined;
      const evidence = view.stateUnavailable ? "unavailable"
        : !robot.online ? "disconnected"
        : staleS !== null ? "delayed" : "fresh";
      const alarm = !view.stateUnavailable && robot.calibration
        ? { level: "caution", text: "보정 중" }
        : !view.stateUnavailable && robot.online && robot.error
          ? { level: "caution", text: robot.error.code || "오류" }
          : undefined;
      const chargingState = robot.power_health?.battery?.charging_state;
      const profile = robotProfile({
        id: robot.robot_id,
        name: view.robotNames?.[robot.robot_id] || robot.robot_id,
        kind: "mobile",
        online: robot.online,
        ageS,
        evidence,
        battery: {
          percent: readBatteryPercent(robot, state),
          voltage: power.voltage,
          charging: chargingState === "CHARGING" || state.power?.charging === true,
        },
        pose: state.pose,
        estop: view.stateUnavailable ? undefined : state.safety?.estop,
        task: view.stateUnavailable ? undefined : (cardTripLine(view, robot.robot_id) || undefined),
        alarm,
      });
      return { profile, detail: { robot } };
    });
    const arms = OMX_CELL_DEFS.filter((def) => (view.anchors || []).some((a) => a.target_id === def.target_id))
      .map((def) => {
        const anc = view.anchors.find((a) => a.target_id === def.target_id) || {};
        const hold = anc.held === true || anc.cell_status === "HOLD" || anc.cell_status === "PAUSED_HUMAN";
        const cellId = def.target_id === "arm_s" ? "cell_s" : "cell_ab";
        const profile = robotProfile({
          id: def.target_id,
          name: def.shortLabel,
          kind: "arm",
          online: anc.online !== false,
          ageS: typeof anc.age_s === "number" ? anc.age_s : undefined,
          evidence: view.stateUnavailable ? "unavailable"
            : anc.online === false ? "disconnected"
            : anc.cell_status ? "fresh" : "unavailable",
          torque: typeof anc.torque === "boolean" ? anc.torque : undefined,
          servo: { currentMa: anc.current_ma, temperatureC: anc.temp_c },
          place: `${def.stationId} · ${cellId}`,
          task: anc.cell_status || undefined,
          alarm: hold ? { level: "caution", text: "홀드 중" } : undefined,
        });
        return { profile, detail: { def, anc, cellId } };
      });
    return [...mobile, ...arms];
  }

  const resolve = (id) => latestRecords.find((r) => r.profile.id === id) ?? null;

  cameraToggle.addEventListener("click", scope.guard(() => {
    if (!openId) return;
    const entry = resolve(openId);
    if (!entry || entry.profile.kind !== "mobile") return;
    frontCamera.toggle(openId);
    render();
  }));

  const panel = createRobotPanel({
    selection,
    resolve,
    onManualCollapse: () => manualControl.stop(),
    onClose: () => {
      manualControl.stop();
      frontCamera.stop();
      openId = null;
      dock.setOpen(null);
      if (yieldedForGoal) return;
      view.selected = null;
      view.cursor = null;
      roster.openCard(null, { fromSelection: true });
      selection?.set?.(null, { source: "panel" });
      render();
    },
    sections: {
      status(profile, detail) {
        if (profile.kind === "arm") {
          const { def, anc, cellId } = detail || {};
          appendKv(armStatusBox, [
            ["셀", cellId || EVIDENCE_LABEL.unavailable],
            ["연계 정류장", def?.stationName || profile.place.text],
            ["상태", anc?.cell_status || EVIDENCE_LABEL.unavailable],
            ["관절", anc?.joints_summary || EVIDENCE_LABEL.unavailable],
            ["서보", anc?.motor_summary || EVIDENCE_LABEL.unavailable],
          ]);
          return armStatusBox;
        }
        const index = view.robots.findIndex((r) => r.robot_id === profile.id);
        roster.place(workspaceBox, index >= 0 ? [roster.card(view.robots[index], index)] : []);
        return workspaceBox;
      },
      camera(profile, detail) {
        if (profile.kind === "arm") return armCameraHint;
        const active = frontCamera.robotId() === profile.id;
        cameraToggle.setAttribute("aria-pressed", active ? "true" : "false");
        const camOff = !detail?.robot?.online && !active;
        setOff(cameraToggle, camOff, camOff ? "오프라인 로봇은 전면 카메라를 열 수 없습니다." : "");
        const children = [cameraToggle];
        if (active && frontCamera.stage()) children.push(frontCamera.stage());
        const same = cameraBox.childElementCount === children.length
          && children.every((child, idx) => cameraBox.children[idx] === child);
        if (!same) cameraBox.replaceChildren(...children);
        return cameraBox;
      },
      commands(profile) {
        return profile.kind === "arm" ? armCommandsBox : null;
      },
      manual(profile) {
        if (profile.kind !== "mobile") return null;
        manualControl.root.hidden = false;
        return manualControl.root;
      },
      settings(profile, detail) {
        if (profile.kind === "arm") {
          appendKv(settingsBox, [
            ["ID", profile.id],
            ["종류", profile.kindLabel],
            ["연결", profile.link.text],
            ["정류장", detail?.def?.stationName || profile.place.text],
          ]);
          return settingsBox;
        }
        appendKv(settingsBox, [
          ["ID", profile.id],
          ["이름", profile.name],
          ["연결", profile.link.text],
          ["위치", profile.place.text],
        ]);
        return settingsBox;
      },
    },
    stop: (profile) => (profile.kind === "arm"
      ? { note: "팔 단독 정지 없음 · 위 머리의 전체 비상 정지를 쓴다" }
      : {
          label: "주행 취소 · 이 로봇",
          onStop: (p) => roster.cancelRobot?.(p.id),
        }),
  });
  panel.root.id = "robot-panel";

  const dock = createRobotDock({
    selection,
    onToggle: (id) => {
      yieldedForGoal = false;
      manualControl.stop();
      frontCamera.stop();
      if (!id) {
        openId = null;
        dock.setOpen(null);
        panel.setRobot(null);
        roster.openCard(null, { fromSelection: true });
        selection?.set?.(null, { source: "dock" });
        render();
        return;
      }
      open(id);
    },
  });
  dock.root.id = "robot-dock";

  if (stage) {
    stage.prepend(panel.root);
    stage.append(dock.root);
  }

  function open(id, { fromSelection = false } = {}) {
    if (!id) return;
    yieldedForGoal = false;
    latestRecords = buildRecords();
    const found = resolve(id);
    if (!found) return;
    if (openId && openId !== id) {
      manualControl.stop();
      frontCamera.stop();
    }
    openId = id;
    roster.openCard(id, { fromSelection: true });
    if (!fromSelection) selection?.set?.(id, { source: "dock" });
    dock.setOpen(id);
    panel.setRobot(found.profile, found.detail);
    render();
  }

  function close() {
    yieldedForGoal = false;
    manualControl.stop();
    frontCamera.stop();
    openId = null;
    dock.setOpen(null);
    panel.setRobot(null);
    roster.openCard(null, { fromSelection: true });
    selection?.set?.(null, { source: "lock" });
  }

  function sync() {
    latestRecords = buildRecords();
    dock.setProfiles(latestRecords.map((r) => r.profile));
    if (!panel.root.hidden) {
      const targetId = openId || view.focusAnchorId || view.focusRobot;
      const found = targetId ? resolve(targetId) : null;
      if (found) {
        openId = found.profile.id;
        dock.setOpen(openId);
        panel.setRobot(found.profile, found.detail);
      } else {
        manualControl.stop();
        frontCamera.stop();
        openId = null;
        dock.setOpen(null);
        panel.setRobot(null);
      }
    }
  }

  function yieldSheetForGoal() {
    if (isWide() || panel.root.hidden) return;
    yieldedForGoal = true;
    manualControl.stop();
    panel.setRobot(null);
    dock.setOpen(null);
  }

  function restoreAfterGoal(robotId) {
    if (!yieldedForGoal) return;
    yieldedForGoal = false;
    const id = robotId || selection?.get?.() || view.focusRobot;
    if (!id) return;
    open(id);
    workspaceBox.querySelector(`ui-button[data-goal-robot-id="${id}"]`)?.focus({ preventScroll: true });
  }

  const offSelection = selection?.subscribe?.((id, meta) => {
    if (meta?.source === "dock" || meta?.source === "panel" || meta?.source === "lock") return;
    if (id && (meta?.source === "roster" || meta?.source === "map" || !panel.root.hidden)) {
      open(id, { fromSelection: true });
      return;
    }
    roster.openCard(id || null, { fromSelection: true });
    render();
  });
  scope.onDispose?.(() => {
    offSelection?.();
    dock.dispose();
    panel.dispose();
  });

  return { sync, open, close, yieldSheetForGoal, restoreAfterGoal };
}
