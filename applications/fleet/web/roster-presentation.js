// Robot list presentation and the labels shared with its selected workspace.
import { NAVIGATION_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { linkTag } from "./link-tag.js";
import { addressReason } from "/console/assets/address-drift.js";
import { positionTag, sitePoseText, untrustedQueuedReason } from "./localization-badge.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { cardTripLine } from "./card-trip.js";

const TAG_STATUS = { nav: "active", ok: "active", warn: "warn", crit: "crit" };

// console_view._error_of 는 닿지 못한 예외를 클래스 이름(code)으로 싣는다. 운영자 말은
// 한국어 평문이다 — 아는 코드만 옮기고 모르는 값은 받은 그대로 보인다(2026-10-02 회차).
export const REACH_LABEL = Object.freeze({
  ConnectError: "접속 실패",
  ConnectTimeout: "접속 시간 초과",
  TimeoutException: "응답 시간 초과",
  ReadTimeout: "응답 시간 초과",
});

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

export function nodeWithText(tagName, className = "", text) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function tag(text, cls) {
  const node = document.createElement("ui-tag");
  node.setAttribute("status", TAG_STATUS[cls] || "neutral");
  node.textContent = text;
  return node;
}

export function blockWith(button, reason) {
  button.disabled = Boolean(reason);
  if (reason) button.setAttribute("reason", reason);
  else button.removeAttribute("reason");
}

export function navTag(state) {
  const nav = state && state.navigation;
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
  if (queued.reason === "YIELDED") {
    return `${who} 가 지나가기를 기다리는 중 — 지나가면 제 미션으로 돌아갑니다`;
  }
  return `${who} 경로와 겹쳐 대기 중 — 앞이 비면 자동 출발합니다`;
}

export function createRosterSummary({scope, view, openCard, render, attentionItems}) {
  return function summary(robot, index) {
    const node = nodeWithText("article", `robot-summary s${index % view.colors.length}`);
    node.dataset.robotId = robot.robot_id;
    node.tabIndex = -1;
    if (view.focusRobot === robot.robot_id) node.classList.add("selected");
    const name = view.robotNames?.[robot.robot_id] || robot.robot_id;
    const line = nodeWithText("div", "robot-line");
    line.append(nodeWithText("b", "ui-disclosure-name", name));
    if (name !== robot.robot_id) line.title = `Fleet ID ${robot.robot_id}`;
    const choose = nodeWithText("ui-button", "", view.focusRobot === robot.robot_id ? "선택됨" : "선택");
    choose.type = "button";
    choose.setAttribute("kind", "toggle");
    choose.setAttribute("aria-pressed", String(view.focusRobot === robot.robot_id));
    choose.setAttribute("aria-label", `${name} 선택`);
    choose.dataset.selectRobotId = robot.robot_id;
    choose.addEventListener("click", scope.guard(() => { openCard(robot.robot_id); render(); }));
    line.append(choose);
    node.append(line);
    const state = view.stateUnavailable ? {} : robot.state || {};
    const link = linkTag(robot.link);
    const status = view.stateUnavailable ? "Fleet 상태 확인 불가" : !robot.online ? (link?.word || "오프라인")
      : !robot.state ? "상태 확인 불가" : link?.word || "연결됨";
    const estop = state.safety?.estop;
    const safety = view.stateUnavailable || !robot.online || !robot.state ? "안전 확인 불가"
      : staleAgeS(robot, view.receivedAtMs, Date.now()) !== null ? "안전 확인 불가"
        : estop === true ? "비상 정지" : estop === false ? "안전 정상" : "안전 확인 불가";
    const facts = nodeWithText("div", "robot-summary-status");
    facts.append(tag(status, view.stateUnavailable || !robot.online ? "warn" : ""),
      tag(safety, estop === true ? "crit" : safety === "안전 정상" ? "" : "warn"));
    const battery = nodeWithText("span", "robot-line-battery", `배터리 ${powerHealthView(robot, view.receivedAtMs, Date.now()).battery}`);
    battery.dataset.fact = "battery";
    facts.append(battery);
    const guideRow = (view.guide?.robots || []).find(row => row.robot_id === robot.robot_id);
    const loc = view.stateUnavailable ? null : positionTag(robot.localization, guideRow);
    const position = tag(loc?.text || "위치 미확인", loc ? loc.cls : "warn");
    position.dataset.localization = "";
    if (loc) position.title = [loc.title, sitePoseText(guideRow)].filter(Boolean).join(" · ");
    facts.append(position);
    const formation = !view.stateUnavailable && view.formation?.active ? view.formation : null;
    const role = formation?.leader === robot.robot_id ? "대형 리더"
      : formation && Object.hasOwn(formation.assignment || {}, robot.robot_id) ? "대형 팔로워" : "";
    if (role) facts.append(tag(role, "nav"));
    node.append(facts);
    const lane = state.line_follow;
    const mode = lane?.mode === "CAMERA_LINE" || lane?.mode === "IR_LINE"
      ? `${enumLabel(LINE_FOLLOW_MODE_LABEL, lane.mode)} · ${enumLabel(LINE_STATE_LABEL, lane.state)}` : navTag(state).text;
    node.append(nodeWithText("p", "trip-line", view.stateUnavailable ? "운행 확인 불가"
      : cardTripLine(view, robot.robot_id) || (robot.yielding ? "비켜서는 중" : robot.queued ? "출발 대기" : mode)));
    const evidence = [];
    if (view.stateUnavailable) evidence.push("Fleet 상태를 확인할 수 없습니다. 연결을 확인하세요.");
    else {
      if (robot.link_reason) evidence.push(`${robot.link_reason.message} ${robot.link_reason.action || ""}`.trim());
      else if (!robot.online && robot.error) evidence.push(robot.error.reachable
        ? `로봇이 거절: ${robot.error.code}` : `닿지 않음: ${REACH_LABEL[robot.error.code] ?? robot.error.code}`);
      if (robot.calibration) evidence.push(`보정 진행 중 · ${robot.calibration.label || "보정"}${robot.calibration.holder ? ` · ${robot.calibration.holder}` : ""}`);
      const address = !robot.online ? addressReason(view.addresses?.[robot.robot_id]) : null;
      if (address) {
        const why = nodeWithText("p", "robot-summary-evidence", address.text);
        why.dataset.addressReason = view.addresses[robot.robot_id].status;
        node.append(why);
      }
      evidence.push(...attentionItems(robot).map(item => item.text.replace(/^:\s*/, "")));
    }
    if (evidence.length) node.append(nodeWithText("p", "robot-summary-evidence", [...new Set(evidence)].join(" · ")));
    return node;
  };
}
