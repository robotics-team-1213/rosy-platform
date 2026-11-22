/**
 * Fleet cockpit C23 right robot dock + C24 left push/sheet robot panel adapter.
 * Connects the shared selection store (C18) with mobile robots and observed OMX arms.
 */
import { createRobotDock } from "/common/robot-dock.js";
import { createRobotPanel } from "/common/robot-panel.js";
import { createRobotView } from "/common/robot-3d.js";
import { createMotorHealthState, renderMotorHealth } from "/common/motor-health.js";
import { robotProfile } from "/common/robot-profile.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { setOff } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";
import { cardTripLine } from "./card-trip.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import { createTelemetryTrace } from "/console/assets/cockpit-telemetry.js";
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
  const armFeed = createCellFrameFeed({ call, scope, intervalMs: 2000 });
  armFeed.setRunning(false);
  const armHealthState = createMotorHealthState();
  const statusWrap = document.createElement("div");
  statusWrap.className = "robot-panel-status-wrap";
  const twinHost = document.createElement("div");
  twinHost.className = "robot-panel-twin";
  const telemetryTrace = createTelemetryTrace();
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
  const armCamBox = document.createElement("div");
  armCamBox.className = "robot-panel-camera-box";
  const armCamToggle = document.createElement("ui-button");
  armCamToggle.setAttribute("kind", "toggle");
  armCamToggle.setAttribute("data-work-read", "");
  armCamToggle.type = "button";
  armCamToggle.textContent = "팔 카메라 보기";
  const armCamFrame = document.createElement("div");
  armCamFrame.className = "omx-inspector-cam-frame";
  const armCamImg = document.createElement("img");
  armCamImg.className = "omx-inspector-main-cam omx-inspector-cam";
  armCamImg.alt = "선택한 팔 카메라 실시간 영상";
  armCamImg.loading = "lazy";
  const armCamBadge = node("small", "영상 대기 · 클릭하여 연결", "omx-inspector-cam-badge");
  armCamFrame.append(armCamImg);
  armCamBox.append(armCamToggle, armCamFrame, armCamBadge);
  const armStatusBox = document.createElement("dl");
  armStatusBox.className = "robot-panel-kv";
  const armHealthBox = document.createElement("section");
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
  let activeTwinKey = null;
  let activeTwinView = null;
  let armCamActive = false;
  let armCamSource = "";

  function resetArmCam() {
    armCamActive = false;
    armCamSource = "";
    armFeed.setRunning(false);
    armCamImg.removeAttribute("src");
  }

  function disposeTwin() {
    activeTwinView?.dispose?.();
    activeTwinView = null;
    activeTwinKey = null;
    twinHost.replaceChildren();
  }

  function syncTwin(profile, detail) {
    const nextKey = `${profile.kind}:${profile.id}`;
    const pose = detail?.robot?.state?.pose;
    const joints = profile.kind === "arm" ? (detail?.obsArm?.positions || detail?.anc?.joints || undefined) : undefined;
    if (activeTwinKey !== nextKey) {
      disposeTwin();
      activeTwinKey = nextKey;
      activeTwinView = createRobotView(twinHost, {
        kind: profile.kind,
        profile,
        name: profile.name,
        selected: true,
        selection,
        robotId: profile.id,
        pose,
        joints,
      });
    } else {
      activeTwinView?.setState({ profile, name: profile.name, selected: true, pose, joints });
    }
    if (profile.kind === "arm") {
      const ma = typeof detail?.currentMa === "number" ? detail.currentMa : null;
      const pwmPct = typeof detail?.pwmPct === "number" ? detail.pwmPct : null;
      const temp = typeof detail?.tempC === "number" ? detail.tempC : null;
      const tone = detail?.obsArm?.held || detail?.anc?.held ? "warn" : detail?.obsArm?.hwFaultMotors ? "crit" : "primary";
      if (ma !== null) {
        telemetryTrace.update({ id: `arm:${profile.id}:ma`, title: "SERVO · LOAD", readout: `${ma} mA${temp !== null ? ` · ${temp} °C` : ""}`, value: ma, unit: "mA", tone });
      } else if (pwmPct !== null) {
        telemetryTrace.update({ id: `arm:${profile.id}:pwm`, title: "SERVO · PWM", readout: `${pwmPct}%${temp !== null ? ` · ${temp} °C` : ""}`, value: pwmPct, unit: "%", minBound: 0, maxBound: 100, tone });
      } else if (temp !== null) {
        telemetryTrace.update({ id: `arm:${profile.id}:temp`, title: "SERVO · TEMP", readout: `${temp} °C`, value: temp, unit: "°C", minBound: 0, maxBound: 85, tone });
      } else {
        telemetryTrace.update({ id: `arm:${profile.id}`, title: "SERVO · LOAD", readout: "—", value: null, unit: "mA", tone });
      }
    } else {
      const robot = detail?.robot || {};
      const state = view.stateUnavailable ? {} : (robot.state || {});
      const pct = robot.online && !view.stateUnavailable ? readBatteryPercent(robot, state) : null;
      const power = powerHealthView(robot, view.receivedAtMs, Date.now());
      const readout = pct !== null
        ? `${Math.round(pct)}%${typeof power.voltage === "number" ? ` · ${power.voltage.toFixed(1)}V` : ""}`
        : robot.online ? "—" : "오프라인";
      telemetryTrace.update({
        id: `batt:${profile.id}`,
        title: "POWER · BATT",
        readout,
        value: pct,
        unit: "%",
        minBound: 0,
        maxBound: 100,
        tone: pct === null ? "neutral" : pct <= 15 ? "crit" : pct <= 25 ? "warn" : "primary",
      });
    }
  }

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
    const obsArms = view.workcellObs?.arms || [];
    const defsById = new Map(OMX_CELL_DEFS.map((def) => [def.target_id, def]));
    const armOrder = [];
    const seenArms = new Set();
    for (const def of OMX_CELL_DEFS.filter((d) =>
      (view.anchors || []).some((a) => a.target_id === d.target_id)
      || obsArms.some((o) => o.id === d.target_id)
    )) {
      seenArms.add(def.target_id);
      armOrder.push(def.target_id);
    }
    for (const obsArm of obsArms) {
      if (!seenArms.has(obsArm.id)) {
        seenArms.add(obsArm.id);
        armOrder.push(obsArm.id);
      }
    }
    const arms = armOrder.map((armId) => {
      const def = defsById.get(armId) || { target_id: armId, shortLabel: armId.toUpperCase(), stationId: "CELL", stationName: "작업 셀" };
      const anc = (view.anchors || []).find((a) => a.target_id === armId) || {};
      const obsArm = obsArms.find((o) => o.id === armId) || null;
      const hold = obsArm?.held === true || anc.held === true || anc.cell_status === "HOLD" || anc.cell_status === "PAUSED_HUMAN";
      const hwFault = (obsArm?.hwFaultMotors || 0) > 0 || obsArm?.motorHealth?.status === "fault";
      const cellId = armId === "arm_s" ? "cell_s" : "cell_ab";
      const currentMa = typeof anc.current_ma === "number" ? anc.current_ma : (obsArm?.maxCurrentMa ?? null);
      const tempC = typeof anc.temp_c === "number" ? anc.temp_c : (obsArm?.maxTempC ?? null);
      const pwmPct = obsArm?.maxPwmPct ?? null;
      const evidence = view.stateUnavailable ? "unavailable"
        : obsArm ? (obsArm.fresh ? "fresh" : obsArm.ageS !== null ? "delayed" : "unavailable")
        : anc.online === false ? "disconnected"
        : anc.cell_status ? "fresh" : "unavailable";
      const profile = robotProfile({
        id: armId,
        name: def.shortLabel,
        kind: "arm",
        online: obsArm ? true : anc.online !== false,
        ageS: obsArm?.ageS ?? (typeof anc.age_s === "number" ? anc.age_s : undefined),
        evidence,
        torque: typeof anc.torque === "boolean" ? anc.torque : (obsArm?.motorHealth?.status === "active" ? true : undefined),
        servo: { currentMa: currentMa ?? undefined, temperatureC: tempC ?? undefined },
        place: `${def.stationId} · ${cellId}`,
        task: anc.cell_status || (obsArm?.fresh ? "실시간 관측" : obsArm ? "대기" : undefined),
        alarm: hold ? { level: "caution", text: obsArm?.heldIncidents?.length ? `보류 ${obsArm.heldIncidents.length}건` : "홀드 중" }
          : hwFault ? { level: "danger", text: "모터 고장" }
          : obsArm?.openIncidents?.length ? { level: "caution", text: `사건 ${obsArm.openIncidents.length}건` }
          : undefined,
      });
      return { profile, detail: { def, anc, obsArm, cellId, currentMa, tempC, pwmPct } };
    });
    return [...mobile, ...arms];
  }

  const resolve = (id) => latestRecords.find((r) => r.profile.id === id) ?? null;

  armCamToggle.addEventListener("click", scope.guard(() => {
    if (!openId) return;
    armCamActive = !armCamActive;
    if (!armCamActive) armFeed.setRunning(false);
    render();
  }));

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
      resetArmCam();
      disposeTwin();
      telemetryTrace.clear();
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
        syncTwin(profile, detail);
        if (profile.kind === "arm") {
          const { def, anc, obsArm, cellId } = detail || {};
          const obsStatus = obsArm?.held ? `보류 ${obsArm.heldIncidents.length}건`
            : obsArm?.fresh ? "실시간 관측" : obsArm ? "대기 · 엔코더 만료" : null;
          const motorTxt = obsArm?.motorHealth
            ? `${obsArm.maxTempC ?? "—"} °C · PWM ${obsArm.maxPwmPct ?? "—"}%`
            : anc?.motor_summary;
          appendKv(armStatusBox, [
            ["셀", cellId || EVIDENCE_LABEL.unavailable],
            ["연계 정류장", def?.stationName || profile.place.text],
            ["상태", anc?.cell_status || obsStatus || EVIDENCE_LABEL.unavailable],
            ["관절", obsArm?.jointsText || anc?.joints_summary || EVIDENCE_LABEL.unavailable],
            ["서보", motorTxt || EVIDENCE_LABEL.unavailable],
          ]);
          const desired = [twinHost, telemetryTrace.root, armStatusBox];
          if (statusWrap.childElementCount !== desired.length || desired.some((n, i) => statusWrap.children[i] !== n)) {
            statusWrap.replaceChildren(...desired);
          }
          return statusWrap;
        }
        const index = view.robots.findIndex((r) => r.robot_id === profile.id);
        roster.place(workspaceBox, index >= 0 ? [roster.card(view.robots[index], index)] : []);
        const desired = [twinHost, telemetryTrace.root, workspaceBox];
        if (statusWrap.childElementCount !== desired.length || desired.some((n, i) => statusWrap.children[i] !== n)) {
          statusWrap.replaceChildren(...desired);
        }
        return statusWrap;
      },
      camera(profile, detail) {
        if (profile.kind === "arm") {
          const cams = view.workcellObs?.cameras || [];
          const cam = cams.find((c) => c.arm_id === profile.id)
            || cams.find((c) => profile.id === "arm_s" ? c.source_id === "omx_arm_s_top" : c.source_id === "omx_overhead");
          if (!cam) {
            resetArmCam();
            return armCameraHint;
          }
          armCamToggle.setAttribute("aria-pressed", armCamActive ? "true" : "false");
          armCamToggle.textContent = armCamActive ? `${cam.label} 끄기` : `${cam.label} 보기`;
          armCamFrame.hidden = !armCamActive;
          if (armCamActive) {
            armFeed.setRunning(!auth.locked && !document.hidden);
            if (armCamSource !== cam.source_id) {
              armCamSource = cam.source_id;
              armFeed.bind(armCamImg, { source: cam.source_id }, armCamBadge, cam.label);
            }
          } else {
            armFeed.setRunning(false);
            armCamBadge.textContent = `${cam.label} · 클릭하면 실시간 영상을 연결합니다`;
          }
          return armCamBox;
        }
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
      health(profile, detail) {
        if (profile.kind !== "arm" || !detail?.obsArm?.motorHealth) return null;
        armHealthState.accept(detail.obsArm.motorHealth, { receivedAtMs: view.workcellObs?.receivedAtMs });
        renderMotorHealth(armHealthBox, armHealthState.read(Date.now()));
        return armHealthBox;
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
      resetArmCam();
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
    resetArmCam();
    disposeTwin();
    telemetryTrace.clear();
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
        disposeTwin();
        telemetryTrace.clear();
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
    disposeTwin();
    telemetryTrace.clear();
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
    disposeTwin();
    telemetryTrace.dispose();
    dock.dispose();
    panel.dispose();
  });

  return { sync, open, close, yieldSheetForGoal, restoreAfterGoal };
}
