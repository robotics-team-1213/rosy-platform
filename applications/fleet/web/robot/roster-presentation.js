// Robot list presentation and the labels shared with its selected workspace.
import { statusTag } from "/common/status-tag.js";
import { valueText } from "/common/value-text.js";
import { robotProfile } from "/common/robot-profile.js";
import { createRobotRow } from "/common/robot-row.js";
import { createRobotView } from "/common/robot-3d.js";
import { skillState } from "/common/skill-state.js";
import { mountRobotCameraTile } from "/console/assets/robot-camera-tile.js";
import { buildLocalizationView } from "/console/assets/localization-view.js";
import { NAVIGATION_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL, EVIDENCE_LABEL, enumLabel, isUnknownText } from "/common/core_ui_logic.js";
import { linkTag } from "./link-tag.js";
import { addressReason } from "/console/assets/address-drift.js";
import { robotAppLinks } from "/console/assets/device-discovery.js";
import { positionTag, sitePoseText, untrustedQueuedReason } from "./localization-badge.js";
import { staleAgeS, stateAgeS, lastSeenText } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { cardTripLine, cardTripSig, openTrip } from "./card-trip.js";
import { estopText } from "./motion-readiness.js";
import { motionSource } from "./motion-source.js";
import { planningStalled } from "./planning-stall.js";

const TAG_STATUS = { nav: "active", ok: "active", warn: "warn", crit: "crit" };

// console_view._error_of 는 닿지 못한 예외를 클래스 이름(code)으로 싣는다. 운영자 말은
// 한국어 평문이다 — 아는 코드만 옮기고 모르는 값은 받은 그대로 보인다(2026-10-02 회차).
export const REACH_LABEL = Object.freeze({
  ConnectError: "접속 실패",
  ConnectTimeout: "접속 시간 초과",
  TimeoutException: "응답 시간 초과",
  ReadTimeout: "응답 시간 초과",
});

const HOLD_WHY = Object.freeze({
  needs_new_code: "등록 자격 만료 · 로봇 화면의 새 코드로 다시 등록",
  address_changed: "주소 바뀜 · 새 주소는 로봇 화면의 코드로 확인",
  conflict: "신원 충돌 · 등록 화면 확인",
});

/** Why an offline robot is offline: Fleet's own hold (the robot was not asked), a robot refusal, or no answer. */
export function offlineWhy(robot) {
  const error = robot.error;
  if (error.held) return `Fleet이 정지 요청만 보냄 · ${HOLD_WHY[robot.held] ?? robot.held ?? "주소 미확인"}`;
  return error.reachable ? `로봇이 거절: ${error.code}` : `닿지 않음: ${REACH_LABEL[error.code] ?? error.code}`;
}

// D-596: why a camera LED check did not name the robot (Vision/Fleet reason codes).
export const IDENTIFY_REASON = {
  none: "식별 조명이 보이지 않음", multiple: "같은 식별 조명이 둘 이상", frames_missing: "카메라 프레임이 빠짐",
  stale: "카메라 영상이 오래됨", calibration_changed: "보정이 바뀜", track_lost: "트랙을 놓침",
  overlap: "다른 로봇과 겹침", not_accepted: "로봇이 거절함", lamp_refused: "로봇이 식별 조명을 거절함",
};

// D-596 rev 2026-10-10: rosy-face's reason for refusing the blink (CORE GET /host/lamp/identify/{id}).
export const LAMP_REASON = {
  CAUTION_ACTIVE: "주의 표시 중(HOLD 등)", ESTOP: "E-Stop", STATE_DISPLAY: "상태 표시 중",
  CORE_UNAVAILABLE: "CORE 인계 없음", LAMP_UNAVAILABLE: "램프 없음",
};

// v1.351 heat mode: CORE caps speed by itself; the card only says so. ok or unknown shows nothing.
const HEAT = Object.freeze({ warm: ["열: 감속", "warn"], hot: ["열: 정지", "crit"] });

/** Pure: [text, cls] of the heat chip for a CORE state, or null. */
export function heatChip(state) {
  return HEAT[state?.safety?.thermal] || null;
}

export function nodeWithText(tagName, className = "", text) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Concept status table (shared statusTag owns the glyphs): disconnected, delayed, unknown, caution, danger. A neutral
// tag is quiet inline text with no glyph; only exceptions and unknown values get one.
function tagState(status, text) {
  if (isUnknownText(text)) return "unknown";
  if (status !== "warn" && status !== "crit") return null;
  if (/끊김|닿지 않|응답 없|오프라인/.test(text)) return "disconnected";
  if (/지연|멈춤|오래/.test(text)) return "delayed";
  return status === "crit" ? "danger" : "caution";
}

export function tag(text, cls) {
  const status = TAG_STATUS[cls] || "neutral";
  const blank = !(typeof text === "string" && text.trim());
  text = blank ? EVIDENCE_LABEL.unavailable : text;  // a blank tag is an unknown value (D-280)
  const state = tagState(status, text);
  let node;
  if (state) {
    node = statusTag(state, text, state === "danger" && /비상 정지/.test(text) ? {icon: "estop"} : {});
    if ((status === "crit" || status === "warn") && !blank) node.setAttribute("status", status);  // the caller's tone wins
  } else {
    node = document.createElement("ui-tag");
    node.setAttribute("status", status);
    node.textContent = text;
  }
  if (status === "neutral") node.setAttribute("variant", "inline");
  return node;
}

export function blockWith(button, reason) {
  button.disabled = Boolean(reason);
  if (reason) button.setAttribute("reason", reason);
  else button.removeAttribute("reason");
}

const planningSince = new Map();

export function navTag(state, robotId = null, nowMs = Date.now()) {
  const nav = state && state.navigation;
  if (robotId !== null && planningStalled(planningSince, robotId, nav, nowMs)) {
    return { text: "경로 계획 응답 없음 · 운행 취소 후 로봇 확인", cls: "crit" };
  }
  if (!nav) return { text: "—", cls: "" };
  if (nav === "NAVIGATING") {
    return { text: state.safety?.estop === false ? "목표 활성" : "목표 남음", cls: "nav" };
  }
  if (nav === "ARRIVED") return { text: enumLabel(NAVIGATION_LABEL, nav), cls: "ok" };
  if (nav === "FAILED") return { text: enumLabel(NAVIGATION_LABEL, nav), cls: "crit" };
  // Navigation IDLE would repeat the mode tag's "대기".
  return { text: nav === "IDLE" ? "목표 없음" : enumLabel(NAVIGATION_LABEL, nav), cls: "" };
}

// 대기에는 세 가지 이유가 있고, 운영자가 할 일이 저마다 다르다. "대기 중" 한 마디로
// 뭉뜽그리면, 손대야 풀리는 상황에서도 사람이 저절로 풀리기를 기다린다.
export function queuedReason(queued) {
  const who = queued.blocked_by;
  if (queued.reason === "NO_YIELD_SPACE") {
    return `${who} 가 길을 막았는데 비켜설 자리가 없습니다 — 맵이 좁습니다. `
      + `${who} 를 직접 다른 곳으로 보내 주세요`;
  }
  if (queued.reason === "YIELDING") {
    return `${who} 가 비켜서기를 기다리는 중 — 물러나면 자동 출발합니다`;
  }
  if (queued.reason === "LOCALIZATION_UNTRUSTED") return untrustedQueuedReason(who);
  if (queued.reason === "MAP_FRAME_MISMATCH") {
    return `${who} 가 다른 지도 프레임에 있어 경로를 함께 판단할 수 없습니다 — `
      + `${who} 의 지도를 맞춘 뒤 다시 시도하세요`;
  }
  if (queued.reason === "YIELDED") {
    return `${who} 가 지나가기를 기다리는 중 — 지나가면 제 미션으로 돌아갑니다`;
  }
  return `${who} 경로와 겹쳐 대기 중 — 앞이 비면 자동 출발합니다`;
}

// B3 (계획 6.2 R3): 로봇 상태의 arm_skill는 C20 표를 그대로 지난다. 실행 중 스킬은 행 글자(태그 없음),
// 이상일 때만 alarm 축에 태그가 붙는다. 모르는 수명주기는 글자 '정보 없음'으로만 남는다.
function robotSkill(robot) {
  return robot?.state?.arm_skill ? skillState(robot.state.arm_skill) : null;
}

export function fleetRobotProfile(robot, view, nowMs = Date.now()) {
  const state = view.stateUnavailable ? {} : robot.state || {};
  const ageS = stateAgeS(robot, view.receivedAtMs, nowMs);
  const batteryPct = robot.power_health?.battery?.percent ?? state.battery?.percent ?? null;
  const voltage = robot.power_health?.battery?.voltage ?? state.battery?.voltage ?? null;
  const charging = Boolean(robot.power_health?.battery?.charging_state === "CHARGING" || state.battery?.charging);
  const estop = state.safety?.estop;
  const skill = robotSkill(robot);
  const skillTag = skill?.tag?.state === "caution" || skill?.tag?.state === "danger" ? skill.tag.state : null;
  const alarm = estop === true
    ? { level: "crit", text: estopText(state, "비상 정지") }
    : !robot.online && robot.error
      ? { level: "warn", text: offlineWhy(robot) }
      : robot.queued
        ? { level: "warn", text: queuedReason(robot.queued) }
        : skill && skillTag
          ? { level: skillTag === "danger" ? "danger" : "caution", text: skill.text }
          : null;
  return robotProfile({
    id: robot.robot_id,
    name: view.robotNames?.[robot.robot_id] || robot.robot_id,
    kind: robot.kind === "arm" || robot.robot_id?.startsWith("arm_") ? "arm" : "mobile",
    online: !view.stateUnavailable && Boolean(robot.online),
    ageS,
    evidence: view.stateUnavailable ? "disconnected" : (robot.link === "degraded" ? "stale" : "fresh"),
    battery: { percent: Number.isFinite(batteryPct) ? batteryPct : null, voltage: Number.isFinite(voltage) ? voltage : null, charging },
    pose: state.pose ? { x: state.pose.x, y: state.pose.y } : null,
    task: skill ? skill.text : (cardTripLine(view, robot.robot_id) || undefined),
    estop: estop === true,
    alarm,
  });
}

export function createRosterSummary({scope, view, openCard, render, attentionItems, motorHealth}) {
  return function summary(robot, index) {
    const profile = fleetRobotProfile(robot, view);
    const activeId = view.robotSelection?.get() ?? null;
    const node = createRobotRow(profile, {
      selected: activeId === robot.robot_id,
      onSelect: scope.guard(() => {
        const next = activeId === robot.robot_id ? null : robot.robot_id;
        if (view.robotSelection) view.robotSelection.set(next, { source: "roster" });
        else { openCard(next); render(); }
      }),
    });
    node.classList.add("robot-summary", `s${index % view.colors.length}`);
    node.tabIndex = -1;
    if (activeId === robot.robot_id) node.classList.add("selected");
    const extra = nodeWithText("div", "robot-row-extra");
    const state = view.stateUnavailable ? {} : robot.state || {};
    const link = linkTag(robot.link);
    const status = view.stateUnavailable ? "Fleet 상태 확인 불가" : !robot.online ? (link?.word || "오프라인")
      : !robot.state ? "상태 확인 불가" : link?.word || "연결됨";
    const estop = state.safety?.estop;
    const stateCurrent = !view.stateUnavailable && robot.online && robot.state
      && staleAgeS(robot, view.receivedAtMs, Date.now()) === null;
    const safety = !stateCurrent ? "안전 확인 불가"
      : estop === true ? estopText(state, "비상 정지") : estop === false ? "안전 정상" : "안전 확인 불가";
    const facts = nodeWithText("div", "robot-summary-status");
    // Normal is quiet: connection and safety show a tag only when one is abnormal.
    if (status !== "연결됨") facts.append(tag(status, view.stateUnavailable || !robot.online ? "warn" : ""));
    if (safety !== "안전 정상") facts.append(tag(safety, estop === true ? "crit" : "warn"));
    // D-926: every fact on the card is the one chip shape; an unread battery is not an attention item.
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    const battery = tag(`배터리 ${power.battery}`, power.problem ? "warn" : "");
    battery.dataset.fact = "battery";
    facts.append(battery, motorHealth.summary(robot));
    const heat = stateCurrent ? heatChip(state) : null;
    if (heat) facts.append(tag(...heat));
    const guideRow = (view.guide?.robots || []).find(row => row.robot_id === robot.robot_id);
    const locView = view.stateUnavailable ? null : buildLocalizationView(robot, view, () => Boolean(view.isOperator?.()));
    const position = document.createElement("span");
    position.className = "robot-row-localization";
    position.dataset.localization = "";
    if (!locView) {
      position.append(statusTag("unknown", "위치 미확인"));
    } else if (locView.state === "localized" && locView.freshness === "fresh") {
      position.textContent = locView.text;
    } else {
      position.append(statusTag(locView.tag, locView.tag_text), ` ${locView.text}`);
    }
    if (guideRow) position.title = sitePoseText(guideRow) || "";
    facts.append(position);
    const formation = !view.stateUnavailable && view.formation?.active ? view.formation : null;
    const role = formation?.leader === robot.robot_id ? "대형 리더"
      : formation && Object.hasOwn(formation.assignment || {}, robot.robot_id) ? "대형 팔로워" : "";
    if (role) facts.append(tag(role, "nav"));
    const source = motionSource(robot, view);
    const sourceTag = tag(source.text, source.cls);
    sourceTag.dataset.motionSource = source.key;
    sourceTag.title = source.title;
    facts.append(sourceTag);
    extra.append(facts);
    const evidence = [];
    if (view.stateUnavailable) evidence.push("Fleet 상태를 확인할 수 없습니다. 연결을 확인하세요.");
    else {
      if (robot.link_reason) evidence.push(`${robot.link_reason.message} ${robot.link_reason.action || ""}`.trim());
      else if (!robot.online && robot.error) evidence.push(offlineWhy(robot));
      if (robot.calibration) evidence.push(`보정 진행 중 · ${robot.calibration.label || "보정"}${robot.calibration.holder ? ` · ${robot.calibration.holder}` : ""}`);
      const address = !robot.online ? addressReason(view.addresses?.[robot.robot_id]) : null;
      if (address) {
        const why = nodeWithText("p", "robot-summary-evidence", address.text);
        why.dataset.addressReason = view.addresses[robot.robot_id].status;
        extra.append(why);
      }
      evidence.push(...attentionItems(robot).map(item => item.text.replace(/^:\s*/, "")));
    }
    if (evidence.length) extra.append(nodeWithText("p", "robot-summary-evidence", [...new Set(evidence)].join(" · ")));
    const appLinks = robotAppLinks(robot.robot_id, view.robotPeers);
    const relocAct = locView?.actions?.find(a => a.id === "relocalize" && !a.disabled);
    const actionsCell = (appLinks.length || relocAct)
      ? (node.querySelector?.('[data-col="actions"]') ?? node.children?.find?.(child => child?.dataset?.col === "actions"))
      : null;
    if (actionsCell) {
      if (relocAct) {
        const relocBtn = nodeWithText("ui-button", "", relocAct.label);
        relocBtn.setAttribute("kind", "quiet");
        relocBtn.type = "button";
        relocBtn.dataset.locAction = "relocalize";
        relocBtn.dataset.robotId = robot.robot_id;
        relocBtn.addEventListener("click", scope.guard(() => {
          if (view.robotSelection) view.robotSelection.set(robot.robot_id, { source: "roster" });
          else openCard(robot.robot_id);
          render();
        }));
        actionsCell.append(relocBtn);
      }
      for (const app of appLinks) {
        const link = nodeWithText("a", "ui-action-link", app.app === "robot" ? "Robot" : "Pilot");
        link.href = app.href;
        link.dataset.kind = "quiet";
        link.dataset.robotApp = app.app;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        actionsCell.append(link);
      }
    }
    node.append(extra);
    return node;
  };
}

export function captureFocusIn(container) {
  const active = typeof document !== "undefined" ? document.activeElement : null;
  if (!active || !container?.contains(active)) return null;
  const tag = active.tagName;
  const selector = active.dataset?.goalRobotId ? `[data-goal-robot-id="${active.dataset.goalRobotId}"]`
    : active.dataset?.pinRobotId ? `[data-pin-robot-id="${active.dataset.pinRobotId}"]`
    : active.dataset?.armTransferPropose ? `[data-arm-transfer-propose="${active.dataset.armTransferPropose}"]`
    : active.dataset?.armJobCancel ? `[data-arm-job-cancel="${active.dataset.armJobCancel}"]`
    : active.dataset?.stepDirection ? `[data-step-direction="${active.dataset.stepDirection}"]`
    : active.dataset?.stepNudge ? `[data-step-nudge="${active.dataset.stepNudge}"]`
    : null;
  return { element: active, selector, tag };
}

export function restoreFocus(container, saved) {
  if (!saved) return;
  if (saved.element?.isConnected) {
    if (document.activeElement !== saved.element) saved.element.focus({ preventScroll: true });
    return;
  }
  if (saved.selector) {
    const candidate = container.querySelector(saved.selector);
    if (candidate && typeof candidate.focus === "function") candidate.focus({ preventScroll: true });
  }
}

export function pinkyStatusSig(entry, view, { isOperator, namedReason, profileVer = 0, index = 0 }, nowMs) {
  const r = entry.robot || {}, id = entry.profile.id, s = r.state || {};
  const power = powerHealthView(r, view.receivedAtMs, nowMs);
  const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === id) || null;
  const open = openTrip(view, id);
  return JSON.stringify([
    id, index, view.colors?.length || 0, view.robotNames?.[id] || "", Boolean(r.online),
    r.link || "", r.link_reason || null, r.rule_m || null, r.error || null, Boolean(r.held),
    r.calibration || null, r.queued || null, r.yielding || null,
    staleAgeS(r, view.receivedAtMs, nowMs) !== null,
    s.mode || "", s.navigation || "", s.safety || null, s.pose || null, s.line_follow || null,
    s.power || null, s.docking || null, s.localization || null, s.evidence || null,
    s.arm_skill || null, s.joints || s.arm?.joints || null, s.diagnostics_summary || null,
    Boolean(!r.online && typeof s.ts === "number" && s.ts > 0),
    power.battery, power.voltage, power.charging, power.note, power.safetyRelease,
    typeof power.observedAgeS === "number", view.selected === id, Boolean(view.stateUnavailable),
    view.formation || null, guideRow, view.addresses?.[id] || null, cardTripLine(view, id),
    open?.trip_id || open?.id || null, Boolean(isOperator?.()), namedReason?.() || "",
    Boolean(view.locStopped?.[id]), view.locByRobot?.[id] || null, view.autoLocateByRobot?.[id] || null,
    view.queuedStarts?.[id] || null, Boolean(view.locDisabled?.[id]), view.locRefused?.[id] || null,
    Boolean(view.locConfirming?.[id]), view.lastRequesterByRobot?.[id] || null, profileVer,
  ]);
}

export function pinkyCommandsSig(entry, view, { isOperator, namedReason }) {
  const r = entry.robot || {}, id = entry.profile.id, s = r.state || {};
  const open = openTrip(view, id);
  const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === id) || null;
  const focusAnchorId = view.focusAnchorId || id;
  return JSON.stringify([
    id, Boolean(r.online), r.error || null, r.link_reason || null, Boolean(r.held),
    r.calibration || null, r.queued || null, r.goal || null, r.capabilities || null, r.localization || null,
    s.mode || "", s.safety || null, s.line_follow || null, s.power || null, s.arm_skill || null, s.trip_lease || null,
    Boolean(view.stateUnavailable), Boolean(view.map), Boolean(view.siteMap), Boolean(view.guideUnavailable),
    view.activeSiteMap?.version ?? null, view.activeSiteMap?.map?.places?.length || 0,
    view.formation || null, guideRow, view.anchors || null, focusAnchorId,
    view.selectedGoal?.robotId === id ? view.selectedGoal : null,
    view.trackerCamByTarget?.[focusAnchorId] || null, view.selected === id, view.pinning === id,
    view.pendingTasks?.[id] || null, open?.trip_id || open?.id || null, open?.state || open?.status || null,
    cardTripSig(view.cardTripForm), view.traffic?.loop_capacity || null, view.trafficTrips || null,
    view.robotPeers || null, view.addresses?.[id] || null, Boolean(isOperator?.()), namedReason?.() || "",
    Boolean(view.locStopped?.[id]), view.locByRobot?.[id] || null, view.autoLocateByRobot?.[id] || null,
    view.queuedStarts?.[id] || null, Boolean(view.locDisabled?.[id]), view.locRefused?.[id] || null,
    Boolean(view.locConfirming?.[id]), view.lastRequesterByRobot?.[id] || null,
  ]);
}

export function refreshPinkyAges(statusEl, robot, view, nowMs) {
  if (!statusEl || !robot) return;
  const ageEl = statusEl.querySelector('[data-fact="state-age"]');
  if (ageEl) {
    const ageS = stateAgeS(robot, view.receivedAtMs, nowMs);
    const nextText = view.stateUnavailable ? "" : `상태 ${valueText(ageS, { unit: "초 전" }).text}`;
    if (ageEl.textContent !== nextText) ageEl.textContent = nextText;
  }
  const batAgeEl = statusEl.querySelector('[data-fact="battery"] .fact-detail');
  if (batAgeEl) {
    const power = powerHealthView(robot, view.receivedAtMs, nowMs);
    if (typeof power.observedAgeS === "number") {
      const nextText = `${power.observedAgeS}초 전`;
      if (batAgeEl.textContent !== nextText) batAgeEl.textContent = nextText;
    }
  }
  const lastSeenEl = statusEl.querySelector('[data-fact="last-seen"]');
  if (lastSeenEl && !view.stateUnavailable && !robot.online) {
    const nextText = lastSeenText(robot, nowMs);
    if (lastSeenEl.textContent !== nextText) lastSeenEl.textContent = nextText;
  }
}

export function armSignatures(id, detail, { isOperator, namedReason }) {
  const d = detail || {};
  const joints = Array.isArray(d.live?.joints_deg) ? d.live.joints_deg.slice(0, 6).map((v) => Number(v).toFixed(1)) : null;
  const liveOffline = !d.live || d.live.available === false || d.live.online === false;
  const liveStale = Boolean(d.live?.stale === true || (Number.isFinite(d.live?.age_s) && d.live.age_s > 5));
  return {
    statusSig: JSON.stringify([
      id, Boolean(isOperator?.()), Boolean(namedReason?.()), liveOffline, liveStale,
      (liveOffline || liveStale) && Number.isFinite(d.live?.age_s) ? Math.round(d.live.age_s) : null,
      Boolean(d.hold?.held), d.hold?.reason || "", Boolean(d.humanSafety),
      d.gate?.phase || "", Boolean(d.gate?.amr_motion_inhibited),
      d.ownerConnected !== false, d.def?.cellId || "", joints,
    ]),
    settingsSig: JSON.stringify([id, d.def?.cellId || "", d.gate?.phase || "", d.gate?.allowed_owners || null]),
  };
}

function skillSentence(armSkill) {
  if (!armSkill) return undefined;
  const skill = skillState(armSkill);
  const byLabel = Object.fromEntries(skill.readout.map(row => [row.label, row.value]));
  return [byLabel["실행기"], byLabel["단계"]].filter(Boolean).join(" · ") || skill.text;
}

export function createDetail3dController(scope) {
  let detail3d = null;
  function clear() {
    if (!detail3d) return;
    detail3d.media?.removeEventListener?.("change", detail3d.onMedia);
    detail3d.fold?.removeEventListener?.("toggle", detail3d.onToggle);
    detail3d.view?.dispose?.();
    detail3d = null;
  }
  scope.onDispose(clear);
  function ensureView() {
    if (!detail3d || detail3d.view) return;
    detail3d.view = createRobotView(detail3d.host, detail3d.viewOpts);
  }
  function mount({ node, mainCol, robot, profile, state, pose, view, nodeWithText }) {
    const joints = state.joints || state.arm?.joints || null;
    const skill = skillSentence(state.arm_skill);
    const selected = view.robotSelection ? view.robotSelection.get() === robot.robot_id : true;
    const stateKey = JSON.stringify([profile?.name, profile?.link?.state, pose?.yaw, joints, skill, selected]);
    const viewOpts = {
      kind: profile.kind, profile, name: profile.name, selected,
      selection: view.robotSelection, robotId: robot.robot_id,
      joints, pose: pose || null, preset: "iso", skill,
    };
    const panelMount = typeof document !== "undefined" ? document.getElementById("robot-panel-mount") : null;
    const liveNode = detail3d?.host?.isConnected ? detail3d.host : detail3d?.fold;
    const sameLivePanel = Boolean(
      detail3d && detail3d.robotId === robot.robot_id && node.classList.contains("robot-panel-settings")
      && liveNode?.isConnected && panelMount?.contains(liveNode),
    );
    if (!detail3d || detail3d.robotId !== robot.robot_id) {
      clear();
      const host = nodeWithText("div", "robot-detail-3d");
      const media = typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(min-width: 1100px)") : { matches: true, addEventListener() {}, removeEventListener() {} };
      detail3d = { robotId: robot.robot_id, host, view: null, media, onMedia: null, fold: null, onToggle: null, stateKey, viewOpts };
    } else {
      detail3d.viewOpts = viewOpts;
      if (detail3d.stateKey !== stateKey) {
        detail3d.stateKey = stateKey;
        detail3d.view?.setState({ profile, name: profile.name, joints, pose: pose || null, skill, selected });
      }
      if (sameLivePanel) return;
      detail3d.media?.removeEventListener?.("change", detail3d.onMedia);
      detail3d.fold?.removeEventListener?.("toggle", detail3d.onToggle);
    }
    const fold3d = document.createElement("details");
    fold3d.className = "robot-detail-3d-fold";
    fold3d.appendChild(nodeWithText("summary", "ui-disclosure-row", "3D 보기"));
    mainCol.appendChild(fold3d);
    const place3d = () => {
      if (!detail3d) return;
      if (detail3d.media.matches) {
        fold3d.hidden = true; ensureView(); node.appendChild(detail3d.host);
      } else {
        fold3d.hidden = false; if (fold3d.open) ensureView(); fold3d.appendChild(detail3d.host);
      }
    };
    const onToggle = () => { if (fold3d.open) ensureView(); };
    detail3d.fold = fold3d; detail3d.onToggle = onToggle; detail3d.onMedia = place3d;
    fold3d.addEventListener("toggle", onToggle);
    detail3d.media?.addEventListener?.("change", place3d);
    node.appendChild(mainCol);
    place3d();
  }
  return { clear, mount };
}

export function appendDetailCamera({ mainCol, robot, call, scope, nodeWithText }) {
  if (!call || robot.kind === "arm" || !robot.robot_id) return;
  if (mainCol.classList.contains("robot-panel-camera") && typeof document !== "undefined") {
    const existing = [...document.querySelectorAll("#robot-panel-mount [data-robot-camera-tile]")]
      .find((el) => el.dataset.robotCameraTile === robot.robot_id);
    if (existing?.isConnected) return;
  }
  const host = nodeWithText("section", "robot-detail-camera");
  host.setAttribute("aria-label", "앞 카메라");
  const tile = mountRobotCameraTile({ host, robotId: robot.robot_id, call, scope });
  mainCol._disposeCamera = tile.stop;
  mainCol.appendChild(host);
}
