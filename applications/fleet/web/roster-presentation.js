import { html, render as renderDom, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
// Robot list presentation and the labels shared with its selected workspace.
import { NAVIGATION_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { linkTag } from "./link-tag.js";
import { addressReason } from "/console/assets/address-drift.js";
import { positionTag, sitePoseText, untrustedQueuedReason } from "./localization-badge.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { cardTripLine } from "./card-trip.js";
import { estopText } from "./motion-readiness.js";
import { motionSource } from "./motion-source.js";
import { planningStalled } from "./planning-stall.js";

const TAG_STATUS = { nav: "active", ok: "active", warn: "warn", crit: "crit" };

// console_view._error_of 는 닿지 못한 예외를 클래스 이름(code)으로 싣는다. 운영자 말은
// 한국어 평문이다 — 아는 코드만 옮기고 모르는 값은 받은 그대로 보인다(2026-10-02 회차).
const REACH_LABEL = Object.freeze({
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

export function tag(text, cls) {
  const node = document.createElement("ui-tag");
  node.setAttribute("status", TAG_STATUS[cls] || "neutral");
  node.textContent = text;
  return node;
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

const ROUTINE_INLINE = new Set([
  "위치 미확인",
  "출처 확인 불가",
  "안전 확인 불가",
  "오프라인",
  "Fleet 상태 확인 불가",
  "상태 확인 불가",
]);

// keepPill wins over the routine set: the offline connection chip and an estop-unknown
// card must keep their pill even when their text is a routine phrase (requirement 33/35).
function isInlineTag(text, cls, { calmOffline = false, keepPill = false } = {}) {
  const nominal = !cls || cls === "nav" || cls === "ok" || (calmOffline && !keepPill);
  return keepPill ? nominal : nominal || ROUTINE_INLINE.has(text);
}

function MotorSummaryHost({ node }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const host = ref.current;
    if (!host) return;
    if (node) {
      if (host.firstChild !== node || host.childNodes.length !== 1) host.replaceChildren(node);
    } else if (host.childNodes.length) {
      host.replaceChildren();
    }
  }, [node]);
  return html`<span ref=${ref} />`;
}

function FactTag({ text, cls, calmOffline, keepPill = false, ...rest }) {
  const inline = isInlineTag(text, cls, { calmOffline, keepPill });
  return html`<ui-tag status=${TAG_STATUS[cls] || "neutral"} variant=${inline ? "inline" : undefined} ...${rest}>${text}</ui-tag>`;
}

function summarizeRobot(robot, view, attentionItems) {
  const name = view.robotNames?.[robot.robot_id] || robot.robot_id;
  const state = view.stateUnavailable ? {} : robot.state || {};
  const link = linkTag(robot.link);
  const status = view.stateUnavailable ? "Fleet 상태 확인 불가" : !robot.online ? (link?.word || "오프라인")
    : !robot.state ? "상태 확인 불가" : link?.word || "연결됨";
  const estop = state.safety?.estop;
  const now = Date.now();
  const stateCurrent = !view.stateUnavailable && robot.online && robot.state
    && staleAgeS(robot, view.receivedAtMs, now) === null;
  const safety = !stateCurrent ? "안전 확인 불가"
    : estop === true ? estopText(state, "비상 정지") : estop === false ? "안전 정상" : "안전 확인 불가";
  const calmOffline = !view.stateUnavailable && !robot.online;
  const power = powerHealthView(robot, view.receivedAtMs, now);
  const heat = stateCurrent ? heatChip(state) : null;
  const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id);
  const loc = view.stateUnavailable ? null : positionTag(robot.localization, guideRow);
  const locTitle = loc ? [loc.title, sitePoseText(guideRow)].filter(Boolean).join(" · ") : undefined;
  const formation = !view.stateUnavailable && view.formation?.active ? view.formation : null;
  const role = formation?.leader === robot.robot_id ? "대형 리더"
    : formation && Object.hasOwn(formation.assignment || {}, robot.robot_id) ? "대형 팔로워" : "";
  const source = motionSource(robot, view);
  const showSource = !(calmOffline && !source.attention && source.key === "unknown");

  const lane = state.line_follow;
  const mode = lane?.mode === "CAMERA_LINE" || lane?.mode === "IR_LINE"
    ? `${enumLabel(LINE_FOLLOW_MODE_LABEL, lane.mode)} · ${enumLabel(LINE_STATE_LABEL, lane.state)}` : navTag(state, robot.robot_id, now).text;
  const trip = view.stateUnavailable ? "운행 확인 불가"
    : cardTripLine(view, robot.robot_id) || (robot.yielding ? "비켜서는 중" : robot.queued ? "출발 대기" : mode);

  const address = !view.stateUnavailable && !robot.online ? addressReason(view.addresses?.[robot.robot_id]) : null;
  const evidence = [];
  if (view.stateUnavailable) evidence.push("Fleet 상태를 확인할 수 없습니다. 연결을 확인하세요.");
  else {
    const attention = attentionItems(robot);
    for (const item of attention) if (item.severity === "crit") evidence.push(item.text.replace(/^:\s*/, ""));
    if (robot.link_reason) evidence.push(`${robot.link_reason.message} ${robot.link_reason.action || ""}`.trim());
    else if (!robot.online && robot.error) evidence.push(offlineWhy(robot));
    if (robot.calibration) evidence.push(`보정 진행 중 · ${robot.calibration.label || "보정"}${robot.calibration.holder ? ` · ${robot.calibration.holder}` : ""}`);
    for (const item of attention) if (item.severity !== "crit") evidence.push(item.text.replace(/^:\s*/, ""));
  }
  const dedupedEvidence = [...new Set(evidence)];
  return {
    name,
    status,
    statusWarn: Boolean(view.stateUnavailable || !robot.online),
    battery: power.battery,
    batteryProblem: Boolean(power.problem),
    safety,
    estopTrue: estop === true,
    heat,
    loc,
    locTitle,
    role,
    source,
    showSource,
    trip,
    addressStatus: address ? view.addresses[robot.robot_id].status : null,
    addressText: address ? address.text : null,
    dedupedEvidence,
    calmOffline,
  };
}

function RosterSummaryBody({ robotId, model, motorNode }) {
  const [firstEvidence, ...otherEvidence] = model.dedupedEvidence;
  return html`
    <div class="robot-line" title=${model.name !== robotId ? `Fleet ID ${robotId}` : undefined}>
      <b class="ui-disclosure-name">${model.name}</b>
      <span class="robot-summary-head-meta">
        <${FactTag} text=${model.status} cls=${model.statusWarn ? "warn" : ""} calmOffline=${model.calmOffline} keepPill=${true} />
        <${FactTag} text=${`배터리 ${model.battery}`} cls=${model.batteryProblem ? "warn" : ""} calmOffline=${model.calmOffline} data-fact="battery" />
      </span>
    </div>
    <div class="robot-summary-status">
      <${FactTag} text=${model.safety} cls=${model.estopTrue ? "crit" : model.safety === "안전 정상" ? "" : "warn"} calmOffline=${model.calmOffline} keepPill=${model.estopTrue} />
      <${MotorSummaryHost} node=${motorNode} />
      ${model.heat ? html`<${FactTag} text=${model.heat[0]} cls=${model.heat[1]} calmOffline=${model.calmOffline} keepPill=${true} />` : null}
      <${FactTag} text=${model.loc?.text || "위치 미확인"} cls=${model.loc ? model.loc.cls : "warn"} calmOffline=${model.calmOffline} data-localization="" title=${model.locTitle} />
      ${model.role ? html`<${FactTag} text=${model.role} cls="nav" calmOffline=${model.calmOffline} />` : null}
      ${model.showSource ? html`<${FactTag} text=${model.source.text} cls=${model.source.cls} calmOffline=${model.calmOffline} keepPill=${model.source.attention} data-motion-source=${model.source.key} title=${model.source.title} />` : null}
    </div>
    ${model.trip !== "—" ? html`<p class="trip-line">${model.trip}</p>` : null}
    ${model.addressText ? html`<p class="robot-summary-evidence" data-address-reason=${model.addressStatus}>${model.addressText}</p>` : null}
    ${firstEvidence ? html`<p class="robot-summary-evidence" title=${model.dedupedEvidence.join(" · ")}><span>${firstEvidence}</span>${otherEvidence.length ? ` 외 ${otherEvidence.length}건` : ""}</p>` : null}
  `;
}

export function createRosterSummary({scope, view, openCard, render, attentionItems, motorHealth}) {
  const cards = new Map();
  return function summary(robot, index) {
    let entry = cards.get(robot.robot_id);
    if (!entry) {
      const article = document.createElement("article");
      article.dataset.robotId = robot.robot_id;
      article.tabIndex = -1;
      entry = { article, sig: "", motorNode: null };
      cards.set(robot.robot_id, entry);
    }
    const { article } = entry;
    const nextClass = `robot-summary s${index % view.colors.length}${view.focusRobot === robot.robot_id ? " selected" : ""}`;
    if (article.className !== nextClass) article.className = nextClass;
    if (article.dataset.robotId !== robot.robot_id) article.dataset.robotId = robot.robot_id;
    const model = summarizeRobot(robot, view, attentionItems);
    const motorNode = motorHealth.summary(robot);
    const sig = JSON.stringify(model);
    if (entry.sig !== sig || entry.motorNode !== motorNode) {
      entry.sig = sig;
      entry.motorNode = motorNode;
      renderDom(
        html`<${RosterSummaryBody} robotId=${robot.robot_id} model=${model} motorNode=${motorNode} />`,
        article,
      );
    }
    return article;
  };
}
