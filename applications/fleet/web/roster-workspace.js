/**
 * Fleet cockpit C23 right robot dock + C24 left push/sheet robot panel adapter.
 * Connects the shared selection store (C18) with mobile robots and observed OMX arms.
 */
import { html, render as renderDom } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { createRobotDock } from "/console/assets/robot-dock.js";
import { createRobotPanel } from "/console/assets/robot-panel.js";
import { Robot3dHost, TelemetryChartHost, PanelKvList } from "/console/assets/cockpit-hosts.js";
import { createMotorHealthState, renderMotorHealth } from "/common/motor-health.js";
import { robotProfile, armEffectivePose, armPositionLine, armCameraChannels, mobileCameraChannels } from "/console/assets/robot-profile.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { node } from "/common/control-dom.js";
import { cardTripLine } from "./card-trip.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import { robotMapPose, robotPoseText, sitePoseText } from "./localization-badge.js";
import { createLocalizationPanel } from "./localization-panel.js";
import { OMX_CELL_DEFS, createFrontCamera } from "./roster-cards.js";
import { rosterPower } from "./roster-presentation.js";
import { staleAgeS } from "./state-age.js";

export function createRosterWorkspace({ scope, el, view, auth, selection, call, render, roster, manualControl, log, confirmedAction, isOperator = () => false, namedReason = () => "" }) {
  const locPanel = createLocalizationPanel({ scope, view, auth, call, log, render, confirmedAction, isOperator, namedReason });
  const stage = el("robot-stage");
  const frontCamera = createFrontCamera({ call, scope });
  const camFeed = createCellFrameFeed({ call, scope, intervalMs: 2000 });
  camFeed.setRunning(false);
  const armHealthState = createMotorHealthState();
  const statusWrap = document.createElement("div");
  statusWrap.className = "robot-panel-status-wrap";
  const twinSlot = document.createElement("div");
  const telemetrySlot = document.createElement("div");
  const workspaceBox = document.createElement("div");
  workspaceBox.id = "robot-workspace";
  workspaceBox.setAttribute("aria-label", "선택한 로봇의 작업");

  const cameraBox = document.createElement("div");
  cameraBox.className = "robot-panel-camera-box";
  const cameraToggleSlot = document.createElement("div");
  const camFrame = document.createElement("div");
  camFrame.className = "omx-inspector-cam-frame";
  const camImg = document.createElement("img");
  camImg.className = "omx-inspector-main-cam omx-inspector-cam";
  camImg.alt = "선택한 로봇 카메라 실시간 영상";
  const camStandby = node("span", "영상 대기", "omx-inspector-cam-standby");
  camStandby.setAttribute("role", "status");
  const camBadge = node("small", "영상 대기 · 클릭하여 연결", "omx-inspector-cam-badge");
  camFrame.append(camImg, camStandby);
  const armStatusBox = document.createElement("div");
  const armHealthBox = document.createElement("section");
  const armCommandsBox = document.createElement("div");
  armCommandsBox.className = "ui-control-stack";
  armCommandsBox.append(node("p", "로봇팔 작업 준비와 승인은 작업 화면(셀)에서 진행합니다.", "hint"));
  const armObsLink = node("a", "팔 관측·사건 보기", "ui-action-link");
  armObsLink.dataset.kind = "quiet";
  armObsLink.href = "/console/cell#observation-heading";
  const armWorkLink = node("a", "팔레트 적재 화면 열기", "ui-action-link");
  armWorkLink.dataset.kind = "quiet";
  armWorkLink.href = "/console/cell";
  armCommandsBox.append(armObsLink, armWorkLink);
  const settingsBox = document.createElement("div");

  let latestRecords = [];
  let openId = null;
  let yieldedForGoal = false;
  let sampleSeq = 0;
  let lastSampleStamp = "";
  let lastArmStatusSig = "";
  let lastSettingsSig = "";
  let lastCamToggleSig = "";
  let mobileCamChannel = "off";
  let armCamChannelId = null;
  let boundCamKey = "";

  function stopAllCameras() {
    frontCamera.stop();
    mobileCamChannel = "off";
    armCamChannelId = null;
    boundCamKey = "";
    camFeed.setRunning(false);
    camImg.removeAttribute("src");
  }

  function clearInspectorHosts() {
    locPanel.clear();
    lastSampleStamp = "";
    lastArmStatusSig = "";
    lastSettingsSig = "";
    lastCamToggleSig = "";
    renderDom(null, twinSlot);
    renderDom(html`<${TelemetryChartHost} active=${false} />`, telemetrySlot);
  }

  function buildTelemetryProps(profile, detail) {
    if (profile.kind === "arm") {
      const ma = typeof detail?.currentMa === "number" ? detail.currentMa : null;
      const pwmPct = typeof detail?.pwmPct === "number" ? detail.pwmPct : null;
      const temp = typeof detail?.tempC === "number" ? detail.tempC : null;
      const tone = detail?.obsArm?.held || detail?.anc?.held ? "warn" : detail?.obsArm?.hwFaultMotors ? "crit" : "primary";
      if (ma !== null) {
        return { id: `arm:${profile.id}:ma`, title: "SERVO · LOAD", readout: `${ma} mA${temp !== null ? ` · ${temp} °C` : ""}`, value: ma, unit: "mA", minBound: null, maxBound: null, tone };
      }
      if (pwmPct !== null) {
        return { id: `arm:${profile.id}:pwm`, title: "SERVO · PWM", readout: `${pwmPct}%${temp !== null ? ` · ${temp} °C` : ""}`, value: pwmPct, unit: "%", minBound: 0, maxBound: 100, tone };
      }
      if (temp !== null) {
        return { id: `arm:${profile.id}:temp`, title: "SERVO · TEMP", readout: `${temp} °C`, value: temp, unit: "°C", minBound: 0, maxBound: 85, tone };
      }
      return { id: `arm:${profile.id}`, title: "SERVO · LOAD", readout: "—", value: null, unit: "mA", minBound: null, maxBound: null, tone };
    }
    const robot = detail?.robot || {};
    const power = rosterPower(view, robot, Date.now());
    const pct = robot.online && !view.stateUnavailable ? power.percent : null;
    const readout = pct !== null
      ? `${pct}%${typeof power.voltage === "number" ? ` · ${power.voltage.toFixed(1)}V` : ""}`
      : !robot.online ? "오프라인"
      : power.note ? `확인 불가 · ${power.note}` : "확인 불가";
    return {
      id: `batt:${profile.id}`,
      title: "POWER · BATT",
      readout,
      value: pct,
      battery: { percent: pct, charging: power.chargingConfirmed, online: robot.online && !view.stateUnavailable },
      unit: "%",
      minBound: 0,
      maxBound: 100,
      tone: pct === null ? (robot.online && !view.stateUnavailable ? "warn" : "neutral") : pct <= 15 ? "crit" : pct <= 25 ? "warn" : "primary",
    };
  }

  function syncTwin(profile, detail) {
    const pose = detail?.effectivePose ?? detail?.robot?.state?.pose;
    const joints = profile.kind === "arm" ? (detail?.obsArm?.positions || detail?.anc?.joints || undefined) : undefined;
    const stamp = `${profile.id}:${profile.kind === "arm" ? (view.workcellObs?.receivedAtMs ?? "") : (view.receivedAtMs ?? "")}`;
    if (stamp !== lastSampleStamp) {
      lastSampleStamp = stamp;
      sampleSeq += 1;
    }
    renderDom(
      html`<${Robot3dHost}
        kind=${profile.kind}
        robotId=${profile.id}
        selection=${selection}
        profile=${profile}
        name=${profile.name}
        selected=${true}
        pose=${pose}
        joints=${joints}
      />`,
      twinSlot,
    );
    const trace = buildTelemetryProps(profile, detail);
    renderDom(html`<${TelemetryChartHost} active=${true} ...${trace} sampleSeq=${sampleSeq} />`, telemetrySlot);
  }

  const isWide = () => typeof matchMedia !== "function" || matchMedia("(min-width: 64rem)").matches;

  function buildRecords() {
    if (auth.locked) return [];
    const now = Date.now();
    const mobile = view.robots.map((robot) => {
      const state = view.stateUnavailable ? {} : (robot.state || {});
      const power = rosterPower(view, robot, now);
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
      const guideRow = !view.stateUnavailable
        ? (view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id) || null
        : null;
      const guidePose = guideRow?.pose && Number.isFinite(guideRow.pose.x) && Number.isFinite(guideRow.pose.y) ? guideRow.pose : null;
      const effectivePose = view.stateUnavailable ? undefined : (robotMapPose(robot) || guidePose || state.pose);
      const placeText = view.stateUnavailable
        ? undefined
        : (guidePose ? sitePoseText(guideRow) : null) || (state.pose ? robotPoseText(state, robot.localization) : undefined);
      const profile = robotProfile({
        id: robot.robot_id,
        name: view.robotNames?.[robot.robot_id] || robot.robot_id,
        kind: "mobile",
        online: robot.online,
        ageS,
        evidence,
        battery: {
          percent: view.stateUnavailable ? null : power.percent,
          voltage: power.voltage,
          charging: power.chargingConfirmed,
        },
        pose: effectivePose,
        place: placeText,
        estop: view.stateUnavailable ? undefined : state.safety?.estop,
        task: view.stateUnavailable ? undefined : (cardTripLine(view, robot.robot_id) || undefined),
        alarm,
      });
      return { profile, detail: { robot, effectivePose } };
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
      const pose = armEffectivePose(def, anc);
      const profile = robotProfile({
        id: armId,
        name: def.shortLabel,
        kind: "arm",
        online: obsArm ? true : anc.online !== false,
        ageS: obsArm?.ageS ?? (typeof anc.age_s === "number" ? anc.age_s : undefined),
        evidence,
        torque: typeof anc.torque === "boolean" ? anc.torque : (obsArm?.motorHealth?.status === "active" ? true : undefined),
        servo: { currentMa: currentMa ?? undefined, temperatureC: tempC ?? undefined },
        place: armPositionLine(def, anc, cellId),
        task: anc.cell_status || (obsArm?.fresh ? "실시간 관측" : obsArm ? "대기" : undefined),
        alarm: hold && obsArm?.heldIncidents?.length ? { level: "caution", text: `보류 ${obsArm.heldIncidents.length}건` }
          : hwFault ? { level: "danger", text: "모터 고장" }
          : obsArm?.homeRecoveries?.length ? { level: "caution", text: "홈 복구 대기" }
          : hold ? { level: "caution", text: "홀드 중" }
          : obsArm?.openIncidents?.length ? { level: "caution", text: `사건 ${obsArm.openIncidents.length}건` }
          : undefined,
      });
      return { profile, detail: { def, anc, obsArm, cellId, effectivePose: pose, currentMa, tempC, pwmPct } };
    });
    return [...mobile, ...arms];
  }

  const resolve = (id) => latestRecords.find((r) => r.profile.id === id) ?? null;

  const selectCamChannel = scope.guard((kind, chId) => {
    if (!openId || (kind === "mobile" && resolve(openId)?.profile.kind !== "mobile")) return;
    const cur = kind === "arm" ? armCamChannelId : mobileCamChannel;
    const next = cur === chId ? (kind === "arm" ? null : "off") : chId;
    stopAllCameras();
    if (kind === "arm") armCamChannelId = next;
    else { mobileCamChannel = next; if (next === "front") frontCamera.toggle(openId); }
    render();
  });

  function renderCamTabs(label, channels, activeId, kind, optsFor) {
    renderDom(html`<div class="omx-inspector-tabs" role="group" aria-label=${label}>
      ${channels.map((ch) => {
        const extra = optsFor ? optsFor(ch) : {};
        return html`<${UiButton} key=${ch.id} kind="segment" data-work-read="" aria-pressed=${activeId === ch.id ? "true" : "false"} disabled=${Boolean(extra.disabled)} reason=${extra.reason || ""} onClick=${() => selectCamChannel(kind, ch.id)}>${ch.label}</${UiButton}>`;
      })}
    </div>`, cameraToggleSlot);
  }

  function syncCameraBox(children, visionSpec) {
    if (visionSpec) children.push(camFrame, camBadge);
    const same = cameraBox.childElementCount === children.length
      && children.every((child, idx) => cameraBox.children[idx] === child);
    if (!same) cameraBox.replaceChildren(...children);
    if (!visionSpec) {
      camFeed.setRunning(false);
      return cameraBox;
    }
    camFeed.setRunning(!auth.locked && !document.hidden);
    if (boundCamKey !== visionSpec.key) {
      boundCamKey = visionSpec.key;
      camFeed.bind(camImg, visionSpec.view, camBadge, visionSpec.label);
    }
    return cameraBox;
  }

  const panel = createRobotPanel({
    selection,
    resolve,
    onManualCollapse: () => manualControl.stop(),
    onCameraCollapse: () => { stopAllCameras(); render(); },
    locate: (profile, detail) => (detail?.effectivePose ? () => roster.openCard(profile.id) : null),
    sectionHeadings: (p) => ({ commands: p.kind === "arm" ? "셀 작업 · 관측" : "위치 · 목표" }),
    onClose: () => {
      manualControl.stop();
      stopAllCameras();
      clearInspectorHosts();
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
          const { def, anc, obsArm, cellId, effectivePose } = detail || {};
          const obsStatus = obsArm?.heldIncidents?.length ? `보류 ${obsArm.heldIncidents.length}건`
            : obsArm?.homeRecoveries?.length ? "홈 복구 대기"
            : obsArm?.fresh ? "실시간 관측" : obsArm ? "대기 · 엔코더 만료" : null;
          const motorTxt = obsArm?.motorHealth
            ? `${obsArm.maxTempC ?? "—"} °C · PWM ${obsArm.maxPwmPct ?? "—"}%`
            : anc?.motor_summary;
          const posReach = effectivePose
            ? `(${effectivePose.x.toFixed(2)}, ${effectivePose.y.toFixed(2)} m)${typeof def?.reach_m === "number" ? ` · 도달 ${def.reach_m.toFixed(2)} m` : ""}`
            : null;
          const rows = [
            ["셀", cellId],
            ["연계 정류장", def?.stationName || profile.place.text],
            ["위치 · 반경", posReach],
            ["상태", anc?.cell_status || obsStatus],
            ["관절", obsArm?.jointsText || anc?.joints_summary],
            ["서보", motorTxt],
          ];
          const armSig = `${profile.id}:${JSON.stringify(rows)}`;
          if (armSig !== lastArmStatusSig) {
            lastArmStatusSig = armSig;
            renderDom(html`<${PanelKvList} rows=${rows} />`, armStatusBox);
          }
          const desired = [twinSlot, telemetrySlot, armStatusBox];
          if (statusWrap.childElementCount !== desired.length || desired.some((n, i) => statusWrap.children[i] !== n)) {
            statusWrap.replaceChildren(...desired);
          }
          return statusWrap;
        }
        const index = view.robots.findIndex((r) => r.robot_id === profile.id);
        roster.place(workspaceBox, index >= 0 ? [roster.card(view.robots[index], index)] : []);
        const desired = [twinSlot, telemetrySlot, workspaceBox];
        if (statusWrap.childElementCount !== desired.length || desired.some((n, i) => statusWrap.children[i] !== n)) {
          statusWrap.replaceChildren(...desired);
        }
        return statusWrap;
      },
      camera(profile, detail) {
        if (profile.kind === "arm") {
          const channels = armCameraChannels(profile.id, view.workcellObs?.cameras);
          const activeCh = armCamChannelId ? channels.find((c) => c.id === armCamChannelId) || null : null;
          if (armCamChannelId && !activeCh) { armCamChannelId = null; boundCamKey = ""; camImg.removeAttribute("src"); }
          const toggleSig = `arm:${profile.id}:${activeCh?.id || "off"}:${channels.map((c) => c.id).join(",")}`;
          if (toggleSig !== lastCamToggleSig) {
            lastCamToggleSig = toggleSig;
            renderCamTabs("팔 카메라 선택", channels, activeCh?.id || null, "arm");
          }
          return syncCameraBox([cameraToggleSlot], activeCh && {
            key: `${profile.id}:${activeCh.id}:${activeCh.roiTarget || activeCh.source}`,
            view: activeCh.roiTarget ? { roiTarget: activeCh.roiTarget } : { source: activeCh.source },
            label: activeCh.label,
          });
        }
        const channels = mobileCameraChannels(profile.id);
        const frontActive = mobileCamChannel === "front" && frontCamera.robotId() === profile.id;
        const activeId = frontActive ? "front" : mobileCamChannel === "roi" ? "roi" : "off";
        const frontOff = !detail?.robot?.online && !frontActive;
        const frontReason = frontOff ? "오프라인 로봇은 전면 카메라를 열 수 없습니다." : "";
        const toggleSig = `mob:${profile.id}:${activeId}:${frontOff}:${frontReason}`;
        if (toggleSig !== lastCamToggleSig) {
          lastCamToggleSig = toggleSig;
          renderCamTabs("이동로봇 카메라 선택", channels, activeId, "mobile", (ch) => (ch.id === "front" ? { disabled: frontOff, reason: frontReason } : {}));
        }
        const children = [cameraToggleSlot];
        if (frontActive && frontCamera.stage()) children.push(frontCamera.stage());
        return syncCameraBox(children, activeId === "roi" && { key: `${profile.id}:roi:${profile.id}`, view: { roiTarget: profile.id }, label: "천장 확대 (ROI)" });
      },
      health(profile, detail) {
        if (profile.kind !== "arm" || !detail?.obsArm?.motorHealth) return null;
        armHealthState.accept(detail.obsArm.motorHealth, { receivedAtMs: view.workcellObs?.receivedAtMs });
        renderMotorHealth(armHealthBox, armHealthState.read(Date.now()));
        return armHealthBox;
      },
      commands(profile, detail) {
        if (profile.kind !== "arm") {
          locPanel.sync(detail?.robot);
          return locPanel.element();
        }
        armObsLink.href = detail?.obsArm?.sourceId
          ? `/console/cell?focus=arm:${encodeURIComponent(detail.obsArm.sourceId)}#observation-heading`
          : "/console/cell#observation-heading";
        return armCommandsBox;
      },
      manual(profile) {
        if (profile.kind !== "mobile") return null;
        manualControl.root.hidden = false;
        return manualControl.root;
      },
      settings(profile, detail) {
        const rows = profile.kind === "arm" ? [
          ["ID", profile.id],
          ["종류", profile.kindLabel],
          ["연결", profile.link.text],
          ["정류장", detail?.def?.stationName || profile.place.text],
        ] : [
          ["ID", profile.id],
          ["이름", profile.name],
          ["연결", profile.link.text],
          ["위치", profile.place.text],
        ];
        const sig = `${profile.id}:${JSON.stringify(rows)}`;
        if (sig !== lastSettingsSig) {
          lastSettingsSig = sig;
          renderDom(html`<${PanelKvList} rows=${rows} />`, settingsBox);
        }
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
      stopAllCameras();
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
      stopAllCameras();
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
    stopAllCameras();
    clearInspectorHosts();
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
        stopAllCameras();
        clearInspectorHosts();
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
    stopAllCameras();
    clearInspectorHosts();
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
    renderDom(null, twinSlot);
    renderDom(null, telemetrySlot);
    renderDom(null, armStatusBox);
    renderDom(null, settingsBox);
    renderDom(null, cameraToggleSlot);
    dock.dispose();
    panel.dispose();
  });

  return { sync, open, close, yieldSheetForGoal, restoreAfterGoal };
}
