import { DOCK_STATE_LABEL, POWER_MODE_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL,
  enumLabel, operatorModeLabel, EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { actionIcon } from "/common/ui.js";
import { createPowerButton } from "/console/assets/power-action.js";
import { createRobotAppActions } from "/console/assets/device-discovery.js";
import { addressReason } from "/console/assets/address-drift.js";
import { linkTag, ruleMTag } from "./link-tag.js";
import { positionTag, robotPoseText, sitePoseText } from "./localization-badge.js";
import { capabilityReason, estopText, motionCommandReason } from "./motion-readiness.js";
import { staleAgeS, stateAgeS, lastSeenText } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { createQueues } from "./queues.js";
import { createFleetMotorHealth } from "./motor-health-view.js";
import { placeRosterCards as place, mustExpand, selectRobot, createRoiPoller,
  buildQuickControlPanel, appendDetailSlots, appendDetailCamera, createDetail3dController,
  leaveTwinOrCameraView, leaveCameraView } from "./roster-cards.js";
import { createStepNudge } from "/console/assets/step-nudge.js";
export {mustExpand, selectRobot} from "./roster-cards.js";
import {createRobotProfiles} from "/console/assets/robot-profile-view.js";
import {createCellFrameFeed} from "/console/assets/cell-frames.js";
import { cancelScope, cardTripLine, createCardTrip, openTrip } from "./card-trip.js";
import { stepQueuedStarts } from "./localization-view.js";
import { valueText } from "/common/value-text.js";
import { createRosterSummary, fleetRobotProfile, nodeWithText, tag, blockWith, navTag, queuedReason, offlineWhy,
  IDENTIFY_REASON, LAMP_REASON } from "./roster-presentation.js";
export function createRoster({ scope, el, view, log, call, render, streamEvidence, isOperator, namedReason = () => "",
  moveAddress = null, moveAddressBlocked = () => "", confirmedAction, onSelectionChanged = () => {} }) {
  const { attentionItems, fillQueues } = createQueues({ scope, el, view, render, streamEvidence });
  const trip = createCardTrip({ scope, el, view, call, log, render, isOperator, namedReason });
  const motorHealth = createFleetMotorHealth({view, scope});
  let profileRev = 0;
  const profiles = createRobotProfiles({call, scope, render: () => { profileRev += 1; render(); }});
  const summary = createRosterSummary({scope, view, openCard, render, attentionItems, motorHealth});
  const { roiObjectUrls, refreshRoiPreview } = createRoiPoller({ scope, view, call, render });
  // 셀 카메라 뷰도 천장 ROI와 같은 Vision 임대로 본다(D-136). Fleet은 바이트를 중계하지 않는다.
  const cellFrames = createCellFrameFeed({ call, scope });
  const detail3d = createDetail3dController(scope);
  const stepNudge = createStepNudge({ scope, call, isOperator, namedReason });
  const uiBtn = (text, kind = "quiet") => { const b = nodeWithText("ui-button", "", text); b.setAttribute("kind", kind); b.type = "button"; return b; };
  const syncMapPicking = () => {
    const stageHost = el("fleet-robot-stage");
    if (stageHost) stageHost.dataset.mapPicking = String(Boolean(view.selected || view.pinning));
  };
  function openCard(robotId) {
    if (typeof robotId === "string" && (robotId.startsWith("arm_") || robotId.startsWith("cell_"))) {
      const armId = robotId === "cell_s" ? "arm_s" : (robotId === "cell_ab" || robotId === "cell_a") ? "arm_a" : robotId === "cell_b" ? "arm_b" : robotId;
      view.focusAnchorId = armId;
      view.selected = null; view.pinning = null; view.cursor = null;
      view.robotSelection?.set(armId, { source: "selectRobot" });
      confirmedAction?.cancel(); trip.close(); onSelectionChanged(); syncMapPicking();
      void refreshRoiPreview();
      return;
    }
    if (selectRobot(view, robotId)) {
      confirmedAction?.cancel(); trip.close(); onSelectionChanged(); syncMapPicking();
      view.focusAnchorId = view.robotSelection?.get() ?? null;
      leaveCameraView(view, el);  // 선택은 카메라 보기만 닫는다 — 트윈 3D는 유지한다
      const canvas = el("map-canvas");
      canvas.classList.toggle("idle", !view.selected && !view.pinning);
      canvas.tabIndex = view.selected ? 0 : -1;
    }
  }
  function needsAttention(robot) {
    return view.stateUnavailable || mustExpand(robot) || attentionItems(robot).length > 0;
  }
  function card(robot, index, opts = null) {
    const node = document.createElement("article");
    const displayName = view.robotNames?.[robot.robot_id] || robot.robot_id;
    node.className = `robot robot-workspace-card ui-panel s${index % view.colors.length}`;
    node.dataset.surface = "raised";  // the one selected robot (concept: ui-panel raised)
    node.dataset.density = "compact";
    node.dataset.robotId = robot.robot_id;
    const lagging = !robot.online && robot.link === "degraded";
    if (!view.stateUnavailable && !robot.online && !lagging) node.classList.add("offline");
    if (view.selected === robot.robot_id) node.classList.add("selected");
    node.tabIndex = -1;
    const mainCol = nodeWithText("div", "robot-detail-main");
    const state = view.stateUnavailable ? {} : (robot.state || {});
    const pose = state.pose;
    const profile = fleetRobotProfile(robot, view);
    const nowSlot = appendDetailSlots({ mainCol, profile, robot, view, scope, openCard, render, nodeWithText, call, isOperator, log,
      onPin: (id) => { view.pinning = id; view.selected = null; view.cursor = null; syncMapPicking(); render(); },
      onStop: () => cancel.click?.(),
      split: Boolean(opts?.split) });
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    const nav = navTag(state, robot.robot_id);
    const tripLine = view.stateUnavailable ? "" : cardTripLine(view, robot.robot_id);
    const estop = state.safety?.estop;
    const stateStale = staleAgeS(robot, view.receivedAtMs, Date.now()) !== null;
    const safetyLabel = !robot.online ? "—" : view.stateUnavailable || stateStale ? EVIDENCE_LABEL.unavailable : estop === true ? estopText(state, "비상 정지")
      : estop === false ? "정상" : EVIDENCE_LABEL.unavailable;
    const goalSafetyReason = view.stateUnavailable ? "Fleet 상태를 확인할 수 없어 목표를 보낼 수 없습니다."
      : estop === true ? "비상정지가 활성화되어 목표를 보낼 수 없습니다."
      : estop !== false && robot.online ? "안전 상태를 확인할 수 없어 목표를 보낼 수 없습니다." : "";
    const head = nodeWithText("header", "robot-head");
    // One status tag in the head (the mode); neutral facts are quiet inline text on the evidence line below.
    const evidenceLine = nodeWithText("p", "robot-evidence");
    const put = (node) => { if (node.textContent === "—") return; (node.getAttribute("variant") === "inline" ? evidenceLine : head).appendChild(node); };
    const kind = document.createElement("span");
    kind.setAttribute("aria-hidden", "true");
    actionIcon(kind, "robot");
    head.append(kind);
    const robotName = document.createElement("b");
    robotName.textContent = displayName;
    const spacer = nodeWithText("span", "spacer");
    head.append(robotName);
    if (displayName !== robot.robot_id) head.append(nodeWithText("small", "hint", `Fleet ID ${robot.robot_id}`));
    head.append(spacer);
    const lane = state.line_follow || {};
    const laneOn = lane.mode === "CAMERA_LINE" || lane.mode === "IR_LINE";
    const modeTag = tag(
      view.stateUnavailable ? "상태 확인 불가" : !robot.online ? "오프라인"
        : laneOn ? `${enumLabel(LINE_FOLLOW_MODE_LABEL, lane.mode)} · ${enumLabel(LINE_STATE_LABEL, lane.state)}`
          : operatorModeLabel(state.mode),
      view.stateUnavailable || !robot.online ? "warn" : laneOn && lane.state === "LOST" ? "warn" : "");
    if (!view.stateUnavailable && robot.online && state.mode) {
      modeTag.title = laneOn ? `${state.mode} · ${lane.mode} ${lane.state || ""}`.trim() : state.mode;
    } else if (!view.stateUnavailable && !robot.online) modeTag.title = "OFFLINE";
    if (laneOn) modeTag.dataset.lineFollow = lane.mode;
    modeTag.removeAttribute("variant");
    head.appendChild(modeTag);
    if (!view.stateUnavailable && robot.online) {
      const powerMode = state.power?.mode;
      if (powerMode) {
        const waking = state.power.motion_ready === false && powerMode === "ACTIVE";
        const powerTag = tag(enumLabel(POWER_MODE_LABEL, powerMode) + (waking ? " · 준비 중" : ""), "");
        powerTag.title = String(powerMode);
        powerTag.dataset.power = String(powerMode);
        put(powerTag);
      }
      const dock = state.docking?.state;
      if (dock) {
        const dockTag = tag(enumLabel(DOCK_STATE_LABEL, dock), dock === "DOCK_FAILED" ? "crit" : "");
        dockTag.title = String(dock);
        dockTag.dataset.dock = String(dock);
        put(dockTag);
      }
      const chargeTag = tag(power.charging === EVIDENCE_LABEL.unavailable ? `충전 ${EVIDENCE_LABEL.unavailable}` : power.charging, "");
      chargeTag.dataset.charging = power.charging;
      const chargeState = robot.power_health?.battery?.charging_state;
      if (typeof chargeState === "string") chargeTag.title = chargeState;
      put(chargeTag);
    }
    const link = view.stateUnavailable ? null : linkTag(robot.link);
    const reason = view.stateUnavailable ? null : robot.link_reason;
    if (link || reason) {
      const linkNode = tag(link ? link.word : reason.message, link ? link.kind : "warn");
      if (link) linkNode.dataset.link = robot.link;
      if (reason) {
        linkNode.dataset.reason = reason.code;
        linkNode.title = `${reason.message} ${reason.action}`;
      }
      put(linkNode);
    }
    const unbounded = view.stateUnavailable ? null : ruleMTag(robot.rule_m);
    if (unbounded) {
      const boundNode = tag(unbounded.word, unbounded.kind);
      boundNode.title = unbounded.text;
      put(boundNode);
    }
    const blocked = !view.stateUnavailable && robot.queued && robot.queued.reason === "NO_YIELD_SPACE";
    put(tag(
      view.stateUnavailable ? "—" : robot.yielding ? "비켜서는 중" : robot.queued ? "출발 대기" : nav.text,
      blocked ? "crit" : robot.queued ? "warn" : nav.cls));
    const formation = view.stateUnavailable ? null : view.formation;
    const role = formation?.active ? (formation.leader === robot.robot_id ? "대형 리더"
      : Object.hasOwn(formation.assignment || {}, robot.robot_id) ? "대형 팔로워" : "") : "";
    if (role) {
      const roleTag = tag(role, "nav");
      roleTag.dataset.formationRole = role === "대형 리더" ? "leader" : "follower";
      put(roleTag);
    }
    const evidence = view.stateUnavailable ? null : streamEvidence(view.formation, robot.robot_id);
    if (evidence) {
      const relay = tag(evidence.text, evidence.cls);
      relay.dataset.evidence = evidence.evidence;
      put(relay);
    }
    const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id);
    const loc = view.stateUnavailable ? null : positionTag(robot.localization, guideRow);
    if (loc) {
      const locTag = tag(loc.text, loc.cls);
      locTag.title = loc.title;
      locTag.dataset.localization = "";
      put(locTag);
    }
    // The state age is evidence for every value below; unknown is never a number.
    const ageS = stateAgeS(robot, view.receivedAtMs, Date.now());
    const seenText = nodeWithText("span", "", view.stateUnavailable ? "" : `상태 ${valueText(ageS, {unit: "초 전"}).text}`);
    seenText.dataset.fact = "state-age";
    if (seenText.textContent) evidenceLine.append(seenText);
    mainCol.appendChild(head);
    if (evidenceLine.childElementCount) mainCol.appendChild(evidenceLine);
    if (role) mainCol.appendChild(nodeWithText('p', 'hint',
      `목적지는 리더 ${formation.leader}에게 배정합니다 · 팔로워 ${Object.keys(formation.assignment || {}).filter(id => id !== formation.leader).join(', ') || '없음'}`));
    if (tripLine) {
      const line = nodeWithText("p", "trip-line", tripLine);
      line.dataset.fact = "trip";
      mainCol.appendChild(line);
    }
    // Header numbers are a readout strip (concept: strip, not boxes). The column head carries the glyph once.
    const facts = nodeWithText("dl", "facts ui-readout");
    facts.dataset.form = "strip";
    const battery = power.battery.endsWith("%") && typeof power.voltage === "number"
      ? `${power.battery} · ${power.voltage.toFixed(2)} V`
      : power.note ? `${power.battery} · ${power.note}` : power.battery;
    const rows = [
      ["pose", "위치", robotPoseText(state, robot.localization)],
      ["yaw", "방향", pose ? `${(pose.yaw * 180 / Math.PI).toFixed(0)}°` : valueText(null).text],
      ["battery", "배터리", battery],
      ["safety", "안전", safetyLabel],
    ];
    rows.forEach(([key, label, value]) => {
      const cellEl = document.createElement("div");
      cellEl.dataset.fact = key;
      const labelEl = nodeWithText("dt", "", label);
      actionIcon(labelEl, key);
      const valueBox = document.createElement("dd");
      let valueEl;
      if (label === "안전" && value === "비상 정지") {
        // 무게로 읽히면 안 된다. 공용 어휘인 crit 태그를 재사용한다.
        valueEl = tag(value, "crit");
      } else {
        valueEl = document.createElement("strong");
        valueEl.textContent = value;
        if (key === "battery" && typeof power.observedAgeS === "number")
          valueBox.append(valueEl, nodeWithText("small", "fact-detail", `${power.observedAgeS}초 전`));
      }
      if (!valueBox.childElementCount) valueBox.append(valueEl);
      if (value === EVIDENCE_LABEL.unavailable) valueBox.toggleAttribute("data-note", true);  // unknown is a note, not a reading
      cellEl.append(labelEl, valueBox);
      const sitePose = key === "pose" && !view.stateUnavailable
        ? sitePoseText((view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id)) : null;
      if (sitePose) valueBox.append(nodeWithText("small", "fact-detail", sitePose));
      facts.appendChild(cellEl);
    });
    mainCol.appendChild(facts);

    let quickControlEl = null;
    let stepNudgeEl = null;
    if (!view.stateUnavailable) {
      quickControlEl = buildQuickControlPanel({
        robot, state, pose, power, guideRow, displayName, view, scope, el, render, isOperator,
        roiObjectUrls, refreshRoiPreview, nodeWithText, tag, cellFrames,
      });
      if (!opts?.split) mainCol.appendChild(quickControlEl);
      stepNudgeEl = stepNudge.renderPanel({ robot, onUpdate: render }).element;
      if (!opts?.split) mainCol.appendChild(stepNudgeEl);
    }

    const motorHealthEl = motorHealth.detail(robot);
    const profileDetailEl = profiles.detail("robot", robot.robot_id);
    mainCol.appendChild(profileDetailEl);
    if (!opts?.split) mainCol.appendChild(motorHealthEl);
    const context = createRobotAppActions(robot.robot_id, view.robotPeers, nodeWithText);
    const group = uiBtn('대형·대열 관리'); group.dataset.openFormation = '';
    group.addEventListener('click', scope.guard(() => view.openFormationWorkspace?.()));
    context.append(group);
    if (!opts?.split) mainCol.appendChild(context);

    if (!view.stateUnavailable) {
      if (power.safetyRelease) mainCol.appendChild(nodeWithText("p", "hint", power.safetyRelease));
      const diagnostics = Object.entries(stateStale ? {} : state.diagnostics_summary || {})
        .filter(([, status]) => status === "WARNING" || status === "ERROR" || status === "UNKNOWN")
        .map(([name, status]) => `${name}: ${status}`);
      if (diagnostics.length) mainCol.appendChild(nodeWithText("p", "hint", `진단: ${diagnostics.join(" · ")} — 로봇 진단 확인`));
    }

    if (!view.stateUnavailable && robot.yielding) {
      // 운영자가 보내지 않은 좌표로 로봇이 움직인다. 이유를 적지 않으면 오작동으로 읽힌다.
      mainCol.appendChild(nodeWithText("p", "hint",
        `${robot.yielding.for} 가 지나가도록 비켜서는 중 — (${robot.yielding.bay.x.toFixed(2)}, ${robot.yielding.bay.y.toFixed(2)}) 로 물러납니다`));
    }

    if (!view.stateUnavailable && robot.queued) {
      // 왜 안 가는지 화면이 말하지 않으면 운영자는 미션이 사라졌다고 읽는다.
      mainCol.appendChild(nodeWithText("p", "hint", queuedReason(robot.queued)));
    }

    // 한 원인은 한 번 말한다(D-359 §5.3) — 카드 상태 줄이 원인을 이미 말하면
    // 버튼 사유는 "위 사유"로 이 줄을 가리킨다.
    const offlineWhyId = !view.stateUnavailable && !robot.online && robot.error && !link ? `robot-why-${robot.robot_id}` : null;
    if (offlineWhyId) {
      const why = nodeWithText("p", "hint", offlineWhy(robot));
      why.id = offlineWhyId;
      mainCol.appendChild(why);
    }

    // 점검 2026-10-01 — 사이트 망이 바뀌면 오프라인만으로는 까닭을 모른다. 고정 주소가
    // 지금 망에 있는지는 서버가 판정하고(GET /api/fleet/discovery/addresses), 여기는 옮겨 적는다.
    const address = !view.stateUnavailable && !robot.online ? addressReason(view.addresses?.[robot.robot_id]) : null;
    if (address) {
      const why = nodeWithText("p", "hint", address.text);
      why.dataset.addressReason = view.addresses[robot.robot_id].status;
      mainCol.appendChild(why);
    }

    if (link?.text) mainCol.appendChild(nodeWithText("p", "hint", link.text));
    if (link?.next) {
      if (link.focus === "console-token") {
        const next = uiBtn(link.next); next.dataset.authFocus = "";
        next.addEventListener("click", scope.guard(() => {
          const token = document.getElementById("console-token");
          const access = document.getElementById("token-access");
          if (access) { access.hidden = false; access.open = true; }
          const more = document.getElementById("topbar-more");
          if (more?.getAttribute("aria-expanded") === "false") more.click();
          token?.focus();
        }));
        mainCol.appendChild(next);
      } else {
        mainCol.appendChild(nodeWithText("p", "hint", link.next));
      }
    }

    if (!view.stateUnavailable && !robot.online) {
      const seen = nodeWithText("p", "hint", lastSeenText(robot, Date.now()));
      seen.dataset.fact = "last-seen";
      mainCol.appendChild(seen);
    }

    const actions = nodeWithText("div", "robot-actions");
    const aim = uiBtn(view.selected === robot.robot_id ? "지도를 찍으세요" : "목표 지정", "toggle");
    aim.dataset.goalRobotId = robot.robot_id;
    aim.setAttribute("aria-pressed", view.selected === robot.robot_id ? "true" : "false");
    const currentLineFollow = state.line_follow || {};
    const lineFollowActive = currentLineFollow.mode === "CAMERA_LINE" || currentLineFollow.mode === "IR_LINE";
    blockWith(aim, namedReason() || (view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인")
        : capabilityReason(robot.capabilities, 'navigation.goal_navigation') || motionCommandReason(view, robot.robot_id, 'goal')
          || ((!view.map && !view.siteMap) ? "지도 없음" : estop === true ? "비상정지 중" : estop !== false ? "안전 상태 확인 불가" : lineFollowActive ? "차선 추종 중" : "")));
    if (offlineWhyId) aim.setAttribute("aria-describedby", offlineWhyId);
    aim.addEventListener("click", scope.guard(() => {
      view.selected = view.selected === robot.robot_id ? null : robot.robot_id;
      view.cursor = view.selected && view.map ? { col: Math.floor(view.map.width / 2), row: Math.floor(view.map.height / 2) } : null;
      const canvas = el("map-canvas");
      if (view.selected) leaveTwinOrCameraView(view, el);
      syncMapPicking();
      canvas.classList.toggle("idle", view.selected === null);
      canvas.tabIndex = view.selected ? 0 : -1;
      render();
      if (view.selected) canvas.focus({preventScroll: true});
      else [...document.querySelectorAll("#robot-panel-mount ui-button[data-goal-robot-id], #robot-workspace ui-button[data-goal-robot-id]")]
        .find(button => button.dataset.goalRobotId === robot.robot_id)?.focus({preventScroll: true});
    }));
    const pin = uiBtn(view.pinning === robot.robot_id ? "위치를 찍고 방향으로 끄세요" : "위치 찍기", "toggle");
    pin.dataset.pinRobotId = robot.robot_id;
    pin.setAttribute("aria-pressed", view.pinning === robot.robot_id ? "true" : "false");
    blockWith(pin, namedReason() || (view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인")
        : !view.map && !view.siteMap ? "지도 없음" : openTrip(view, robot.robot_id) ? "운행 중" : ""));
    pin.addEventListener("click", scope.guard(() => {
      view.pinning = view.pinning === robot.robot_id ? null : robot.robot_id;
      if (view.pinning) { view.selected = null; view.cursor = null; leaveTwinOrCameraView(view, el); }
      syncMapPicking();
      el("map-canvas").classList.toggle("idle", !view.pinning);
      render();
    }));
    // D-540 1/3: 이 로봇 정지 = 운행 취소 한 자리. 열린 trip이면 trip을, 없으면 목표(와 켜진 차선 주행)를
    // 멈춘다. 멈춤이라 quiet·확인 없음이고 이름 없는 운영자에게도 열려 있다(D-540 9). Fleet의 trip은
    // 로봇이 오프라인이어도 취소할 수 있다.
    const shown = cancelScope(openTrip(view, robot.robot_id), state.line_follow?.mode);
    const cancel = uiBtn("운행 취소");
    cancel.title = shown.text;
    cancel.dataset.cancelScope = shown.trip ? "trip" : shown.lane ? "goal-lane" : "goal";
    blockWith(cancel, view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online && !shown.trip ? (offlineWhyId ? "위 사유" : "로봇 오프라인") : "");
    if (offlineWhyId) cancel.setAttribute("aria-describedby", offlineWhyId);
    cancel.addEventListener("click", scope.guard(() => stopRobot(robot.robot_id)));
    const lineFollow = state.line_follow || {};
    const cameraFaultLatched = lineFollow.mode === "CAMERA_LINE"
      && lineFollow.state === "LOST"
      && lineFollow.reason === "camera_reselection_required";
    if (cameraFaultLatched || lineFollow.mode === "IR_LINE") {
      const fallback = uiBtn(lineFollow.mode === "IR_LINE" ? "IR 차선 추종 끄기" : "IR 차선 추종으로 전환…");
      blockWith(fallback, view.stateUnavailable ? "Fleet 상태 확인 불가"
        : !robot.online ? "로봇 오프라인"
          : !isOperator() ? "운영자 권한이 필요합니다"
            // D-540 9: IR 추적 선택은 움직임, 중지(OFF)는 멈춤이다.
            : lineFollow.mode !== "IR_LINE" ? namedReason() : "");
      fallback.addEventListener("click", scope.guard(async () => {
        const life = scope.capture();
        life.check();
        const mode = lineFollow.mode === "IR_LINE" ? "OFF" : "IR_LINE";
        const kind = `IR:${robot.robot_id}`;
        const send = async owner => {
          const result = await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/line-follow`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode }), signals: [owner.signal],
          });
          owner.check();
          const now = result.result?.state;
          log(`${robot.robot_id} ${mode === "IR_LINE" ? "IR 차선 추종 요청" : "IR 차선 추종 끔"} · ${now ? enumLabel(LINE_STATE_LABEL, now) : "CORE 응답 확인"}`, "good");
        };
        const fail = err => log(`${robot.robot_id} IR 차선 추종 거절 · ${err.message}`, "bad");
        if (mode === "OFF") {
          confirmedAction.cancel(kind);
          try { await send(life); } catch (err) { if (life.current() && err.name !== "AbortError") fail(err); }
          return;
        }
        await confirmedAction.run({kind, message: `${robot.robot_id}의 카메라 고장이 확인되었습니다. CORE 안전 조건을 다시 확인하고 IR 차선 추종을 요청할까요?`, opener: fallback,
          eligible: () => !view.stateUnavailable && isOperator() && view.robots.some(current => current.robot_id === robot.robot_id && current.online
            && current.state?.line_follow?.mode === "CAMERA_LINE" && current.state.line_follow.state === "LOST" && current.state.line_follow.reason === "camera_reselection_required"),
          request: send, onError: fail});
      }));
      actions.append(fallback);
    }
    const identify = uiBtn("LED로 찾기");
    blockWith(identify, !isOperator() ? "운영자 권한이 필요합니다"
      : namedReason() ? namedReason()
      : !robot.online || view.stateUnavailable ? "로봇 연결을 확인하세요"
        : estop !== false ? "안전 상태 확인이 필요합니다" : "");
    identify.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      try {
        // D-596: Fleet picks the colour (the robot's own, or the one still free on its camera) and asks
        // a standing robot too; the robot is never moved.
        const started = await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/identify`, { method: "POST" });
        // The robot face says CALL <id> for the same window. The map chip names who was called.
        view.call = { robot_id: robot.robot_id, until: Date.now() + 6000 };
        render();
        log(`${robot.robot_id} LED 확인 중 · ${started.color === "blue" ? "파랑" : "주황"} 식별 조명 · 얼굴에 이름 표시`, "info");
        await new Promise((done) => setTimeout(done, 8500));  // 6 s window + Vision's verdict
        if (!life.current()) return;
        const readback = await call("/api/fleet/tracking/identity", { signals: [life.signal] });
        const row = (readback.robots || []).find((item) => item.robot_id === robot.robot_id);
        if (row?.state === "CONFIRMED") log(`${robot.robot_id} LED 확인됨 · 카메라 트랙에 이름을 붙였습니다`, "good");
        else {
          const lamp = row?.last?.lamp_reason;
          const why = lamp ? ` · ${LAMP_REASON[lamp] || lamp}` : "";
          log(`${robot.robot_id} LED 확인 실패 · ${IDENTIFY_REASON[row?.reason] || row?.reason || "판정 없음"}${why}`, "bad");
        }
      } catch (error) {
        if (error.name !== "AbortError") log(`${robot.robot_id} LED 확인 거부 · ${error.message}`, "bad");
      }
    }));
    const powerButton = createPowerButton({ robot, state, view, scope, call, log, isOperator, namedReason, blockWith });
    actions.append(aim, pin, trip.toggle(robot), cancel, identify, powerButton);
    if (address?.action === "move" && moveAddress) {
      // 기존 로봇별 "새 주소로 옮기기"를 그대로 부른다 — 확인 뒤 서버가 토큰으로 신원을 다시 읽는다.
      const move = uiBtn("새 주소로 옮기기…");
      move.dataset.moveRobotId = robot.robot_id;
      blockWith(move, moveAddressBlocked());
      move.addEventListener("click", scope.guard(() => moveAddress(robot.robot_id)));
      actions.append(move);
    }
    const commandsHost = opts?.split ? nodeWithText("div", "robot-panel-commands") : mainCol;
    if (opts?.split && nowSlot) commandsHost.appendChild(nowSlot);
    commandsHost.appendChild(actions);
    const tripForm = view.stateUnavailable ? null : trip.section(robot);
    if (tripForm) commandsHost.appendChild(tripForm);
    if (goalSafetyReason) commandsHost.appendChild(nodeWithText("p", "hint", goalSafetyReason));
    if (lineFollowActive) commandsHost.appendChild(nodeWithText("p", "hint",
      "차선 추종 중에는 목표를 받지 않습니다 · 운행 취소로 차선 추종을 끈 뒤 목표를 지정하세요."));
    if (opts?.split && stepNudgeEl) commandsHost.appendChild(stepNudgeEl);
    if (opts?.split && quickControlEl) commandsHost.appendChild(quickControlEl);
    if (opts?.split) commandsHost.appendChild(context);
    if (opts?.split && opts.manualRoot) commandsHost.appendChild(opts.manualRoot);
    const cameraHost = opts?.split ? nodeWithText("div", "robot-panel-camera") : mainCol;
    appendDetailCamera({ mainCol: cameraHost, robot, call, scope, nodeWithText });
    const healthHost = opts?.split ? nodeWithText("div", "robot-panel-health") : null;
    if (healthHost) healthHost.appendChild(motorHealthEl);
    const settingsHost = opts?.split ? nodeWithText("div", "robot-panel-settings") : node;
    const settingsCol = opts?.split ? nodeWithText("div", "robot-panel-settings-body") : mainCol;
    if (opts?.split) {
      const settingsFacts = nodeWithText("dl", "facts");
      const addrRow = view.addresses?.[robot.robot_id];
      const factRows = [["식별자", robot.robot_id]];
      if (addrRow?.address) factRows.push(["연결 주소", addrRow.address]);
      for (const [label, value] of factRows) {
        const box = document.createElement("div");
        box.append(nodeWithText("dt", "", label), nodeWithText("dd", "", value));
        settingsFacts.append(box);
      }
      const settingsLinks = nodeWithText("div", "robot-panel-settings-links");
      const rid = encodeURIComponent(robot.robot_id);
      for (const [href, label] of [
        [`/console/install?robot=${rid}#install-heading`, "주소·페어링·네트워크 설정"],
        [`/console/site-map?robot=${rid}`, "지도·원점·캘리브레이션 설정"],
        [`/console/install?profile=${rid}#device-profiles`, "장치 정보 · 주의사항"],
      ]) {
        const link = nodeWithText("a", "ui-action-link", label);
        link.dataset.kind = "quiet";
        link.href = href;
        settingsLinks.append(link);
      }
      settingsCol.append(settingsFacts, settingsLinks);
    }
    detail3d.mount({ node: settingsHost, mainCol: settingsCol, robot, profile, state, pose, view, nodeWithText });
    if (opts?.split) { node.appendChild(mainCol); return {
      status: node, camera: cameraHost, health: healthHost, commands: commandsHost, settings: settingsHost,
      stop: { label: "주행 취소 · 이 로봇", disabled: cancel.disabled, onStop: () => cancel.click?.() },
    }; }
    return node;
  }

  async function stopRobot(robotId) {
    if (!robotId) return;
    const life = scope.capture();
    life.check();
    view.locStopped ??= {}; view.locStopped[robotId] = true;
    stepQueuedStarts({ view, stoppedRobotId: robotId, render });
    // Decide at click time: a card kept across polls (roster.place) may predate the trip.
    const now = view.robots.find((row) => row.robot_id === robotId) || { robot_id: robotId };
    const stop = cancelScope(openTrip(view, robotId), now.state?.line_follow?.mode);
    try {
      if (stop.trip) {
        try {
          await call(`/api/fleet/trips/${encodeURIComponent(stop.trip)}/cancel`, { method: "POST" });
          life.check();
          view.trafficTrips = (view.trafficTrips || []).filter((row) => row.trip_id !== stop.trip);
          render();
          log(`${robotId} 운행 취소`, "good");
          return;
        } catch (err) {  // the trip may have just ended: the goal cancel below still stops the robot
          if (err.name === "AbortError") return;
          log(`${robotId} 운행 취소 실패 — ${err.message} · 목표 취소를 보냅니다`, "bad");
        }
      }
      const pending = view.pendingTasks[robotId];
      if (pending) {
        const readback = await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}`);
        life.check();
        if (readback.task?.status === "QUEUED") {
          await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}/cancel`, { method: "POST" });
          life.check();
          delete view.pendingTasks[robotId];
          render();
          log(`${robotId} task ${pending.task_id} QUEUED 취소`, "good");
          return;
        }
        delete view.pendingTasks[robotId];
      }
      await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/cancel`, { method: "POST" });
      life.check();
      if (stop.lane) {
        await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-follow`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "OFF" }) });
        life.check();
      }
      log(`${robotId} ${stop.lane ? "목표·차선 추종 취소" : "항법 취소"}`, "good");
    } catch (err) {
      if (err.name === "AbortError") return;
      log(`${robotId} 취소 실패 — ${err.message}`, "bad");
    }
  }

  function openTripForm(robotId) {
    openCard(robotId);
    trip.focus(robotId);
  }

  function paintTrip(box, robotId) {
    const focused = document.activeElement;
    if (focused?.tagName === "SELECT" && box.contains(focused)) return;
    const robot = view.stateUnavailable ? null : view.robots.find(row => row.robot_id === robotId);
    const controls = () => [...box.querySelectorAll("ui-button, select")], at = controls().indexOf(focused);
    let section = robot ? trip.section(robot) : null;
    if (robot && !section) {
      trip.focus(robotId);
      section = trip.section(robot);
    }
    box.replaceChildren(...(section ? [section] : []));
    controls()[at]?.focus({preventScroll: true});
  }

  return { card, summary, clear3d: () => detail3d.clear(), place, fillQueues, queuedReason, needsAttention, attentionItems, openCard, stopRobot,
    profileVersion: () => profileRev, syncProfile: (robotId) => profiles.detail("robot", robotId),
    syncConvoy: trip.syncConvoy, closeTrip: trip.close, openTrip: openTripForm, paintTrip };
}
