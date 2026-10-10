// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createConnectionView } from "./connection-view.js";
import { createFormation } from "./formation.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { CAUSE_LABEL, createLineStuckPanel } from "./line-stuck.js";
import { createTripReplan } from "./trip-replan.js";
import { createSignals } from "./signals.js";
import { createTrackingView } from "./tracking-view.js";
import { pinPrefill } from "./localization-badge.js";
import { createVisionView } from "/console/assets/vision-view.js";
import { applyRoleToControls, namedOperatorReason } from "/console/assets/authorization.js";
// D-410 — 기기 등록·카메라 연결 승인·경기장/맵 보정은 설치 화면(install.js)이 가진다.
import { addressMap, movableRobots, renumberBanner } from "/console/assets/address-drift.js";
import { fleetRow, proxyRow, visionRow, sitePathSummary } from "./site-path.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { createFleetClient } from "/common/fleet-client.js";
import { issueDevelopmentSession } from "/console/assets/development-auth.js";
import { createPasswordLogin } from "./password-login.js";
import { confirmIrreversible } from "/common/ui.js";
import { createConfirmedAction } from "./confirmed-action.js";
import { createPageScope } from "/common/scope.js";
import { bindEstop, showFleet, showSession, showSignedOut, stopNotice, tickClock } from "/console/assets/fleet-header.js";
const pageScope = createPageScope();
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.


const el = (id) => document.getElementById(id);
const layoutMedia = matchMedia("(min-width: 64rem)");
// D-493 — 넓은 단: 왼쪽 열은 지도 하나, 오른쪽 열은 예외·로봇(발행 띠 포함)·카메라·대형 순서다.
// 한 열 단(D-359 US-009): 예외 → 지도 → 사건 → 로봇 → 카메라 → 대형·기록.
const layoutPanels = [document.querySelector('.queues-panel'), document.querySelector('[aria-labelledby="map-heading"]'),
  document.querySelector('.incident-panel'), document.querySelector('[aria-labelledby="roster-heading"]'),
  document.querySelector('.vision-preview'), document.querySelector('.ops-block')];
const MAP_PANEL = 1;
function layoutConsole() {
  const main = el("fleet-main"), primary = main.querySelector('.console-primary'), secondary = main.querySelector('.console-secondary');
  const focused = document.activeElement;
  layoutPanels.forEach((node, index) => {
    const parent = layoutMedia.matches ? (index === MAP_PANEL ? primary : secondary) : main;
    const before = layoutMedia.matches ? null : primary;
    if (parent.moveBefore) parent.moveBefore(node, before);
    else parent.insertBefore(node, before);
  });
  if (focused?.isConnected && document.activeElement !== focused) focused.focus({preventScroll: true});
}
layoutConsole();
pageScope.listen(layoutMedia, "change", layoutConsole);
pageScope.onResume(layoutConsole);

// 셸 폴링 운율과 로그 상한은 셸이 가진다. 지도 격자·오버레이 임계는 map-view.js에 있다.
const STATE_MS = 1000;
// D-457 6: a tracking position shows for at most 1 s minus its age and the request time, so
// polling at 1 s always left a gap and the markers blinked; poll well inside the lifetime.
const TRACKING_MS = 400;
const MAP_MS = 5000;
const LOG_MAX = 120;
const INCIDENT_CAUSES = {
  line_marking: "차선·바닥 표식", obstacle: "장애물", robot_fault: "로봇·센서 오류",
  localization: "위치 추정", traffic_wait: "교통 대기", unknown: "미확인",
};

// 꺼진 기능(라우트 없음 404)은 다음 로그인·토큰 저장까지 두드리지 않는다. poll-gate.js 참고.
const dispatchGate = createPollGate();
const discoveryGate = createPollGate();

// 관제 토큰 — 서버가 루프백 밖으로 열리면 모든 /api/fleet/* 이 401 로 막힌다
// (cli.run_console 강제, app.authorize). 토큰은 세션 스토리지에만 둔다 —
// localStorage 에 두면 공유 관제PC 의 다음 근무자가 그대로 물려받는다.
const auth = {
  token: sessionStorage.getItem("rosy-console-token") || "",
  role: null,
  // D-248: 잠기면 폴링이 401 을 두드리지 않는다. 수동 저장·새로고침은 막지 않는다.
  locked: false,
};
const confirmedAction = createConfirmedAction({scope: pageScope, identity: () => ({...auth}), confirm: confirmIrreversible});
function cancelAllNotice(message = "", details = false) {
  const result = el("cancel-all-result"), link = el("cancel-all-details");
  result.textContent = message;
  result.hidden = !message;
  link.hidden = !details;
}

function authHeaders() {
  return auth.token ? { "Authorization": `Bearer ${auth.token}` } : {};
}

// D-359 §6.4 — compact·medium에서 접속·역할·테마는 토글 뒤에 접힌다(세로 예산).
// 넓은 창에서는 CSS가 토글을 숨기고 항목을 줄에 세운다. 잠기면 토큰 칸을 연다.
const connectionView = createConnectionView({scope: pageScope, el});

function markLocked(reason = "auth") {
  confirmedAction.cancel();
  stopNotice();
  cancelAllNotice();
  const firstLock = !auth.locked;
  auth.locked = true;
  connectionView.open();
  auth.role = null;
  incidentReports = [];
  incidentTrafficReports = [];
  el("incident-list").replaceChildren();
  el("incident-traffic-list").replaceChildren();
  el("incident-export").disabled = true;
  el("incident-export").setAttribute("reason", "관제 접속 후 내보낼 수 있습니다");
  el("incident-status").textContent = "관제 접속 후 사건을 불러옵니다.";
  showSignedOut({fold: false, refused: reason === "auth"});
  applyRoleToControls(null, operatorControls());
  const pill = el("online-pill");
  pill.textContent = "접속 전";
  pill.setAttribute("status", "neutral");
  pill.dataset.locked = "true"; // 해제 때 문구가 아니라 이 표시로 잠금 pill을 알아본다
  if (auth.token && reason === "auth") el("console-token").setAttribute("aria-invalid", "true");
  const canvas = el("map-canvas"); canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  // D-493 — 잠기면 지도 칸의 큰 영상과 크게 보기 선택을 같이 내린다. 지난 프레임을 살아 있는 듯 두지 않는다.
  el("map-birdseye").hidden = true;
  delete el("map-stage").dataset.view;
  el("birdseye-toggle").setAttribute("aria-pressed", "false");
  connectionView.show(reason, auth.token);
  if (firstLock) {
    Object.assign(view, {robots: [], map: null, siteMap: null, sightings: [], cameraTracking: {robots: [], unknown: []},
      stateLoaded: false, stateUnavailable: false, selected: null, cursor: null, formation: null, signals: {},
      traffic: null, trafficTrips: [], endedTrips: [], trafficClock: null});
    visionView.reset(); visionView.refreshSources(); trackingView.reset();
  }
  render();
  // D-473 4 — the first 401 of a lock asks once whether this console is in development mode.
  if (firstLock && reason === "auth") renewDevelopmentSession();
  // D-519 6 — paired consoles offer 아이디·비밀번호 once per lock.
  if (firstLock && reason === "auth") loginForm.refresh(true);
}

function markUnlocked() {
  auth.locked = false;
  connectionView.hide();
  el("console-token").removeAttribute("aria-invalid");
}

function operatorControls() {
  // 화면 테마(data-theme-choice)는 이 브라우저의 표시 선호라 권한과 무관하다(D-359 §2.5).
  // 머리 토글(#topbar-more)은 접힌 칸을 여는 표시 조작이다(§6.4). 비상 정지는 fleet-header.js 규칙 하나다(D-540 2).
  return document.querySelectorAll(
    "ui-button:not(#estop):not(#token-save):not(#topbar-more):not([data-login]):not(#vision-refresh):not(#log-clear):not(#birdseye-toggle):not(#traffic-toggle):not([data-theme-choice]), main input, main select:not(#vision-source)");
}

const view = {
  map: null,
  pinning: null,   // D-593 위치를 찍을 로봇 id(운영자 핀), 아니면 null
  siteMap: null,   // D-257 천장 카메라 사각형 (GET /api/fleet/site-map)
  sightings: [],   // 카메라 관측 — 표시 전용, CORE pose 와 섞지 않는다
  cameraTracking: { robots: [], unknown: [] }, // D-457 관제 카메라 추적 — 표시·교차확인 전용
  robots: [],
  robotNames: {}, // enrolled robot_id -> verified discovery hostname; presentation only
  cardChoice: {},  // D-540 3: robot_id -> the operator's fold {open, attention}
  queueChoice: null,  // D-540 3: the queue row the operator opened or closed {key, open}
  selected: null, // 목표 지정을 기다리는 robot_id
  cursor: null, // 지도 좌표계의 col/row, 아래쪽 행이 0
  colors: [],
  formation: null,
  formationUnavailable: false,
  signals: {},    // ROSY-SIGNAL-001 — snapshot 의 signals 캐시
  pendingTasks: {},
  dispatchControl: null,
  stateUnavailable: false,
  stateLoaded: false,
  receivedAtMs: null,  // D-493: 마지막 state 응답을 받은 브라우저 시각
  addresses: {},  // robot_id -> GET /api/fleet/discovery/addresses 행(고정 주소 판정)
};
// A chooser deep link only reveals/focuses an existing card; it never arms a goal.
let requestedRobotFocus = new URLSearchParams(location.search).get("robot");

function log(text, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  const now = new Date().toTimeString().slice(0, 8);
  line.textContent = `${now}  ${text}`;
  const box = el("log");
  box.querySelector("ui-empty")?.remove();
  box.prepend(line);
  while (box.childElementCount > LOG_MAX) box.lastElementChild.remove();
}

const fleetClient = createFleetClient({ credential: () => auth.token });

async function call(path, options = {}) {
  const task = pageScope.capture();
  task.check();
  const cameraPreview = path === "/api/fleet/vision/sources" || path === "/api/fleet/vision/lease";
  try {
    const body = await fleetClient(path, {...options, signals: [...(options.signals || []), task.signal]});
    task.check();
    if (auth.locked && path !== "/api/fleet/session" && !cameraPreview) throw new DOMException("Authentication changed", "AbortError");
    if (path === "/api/fleet/session") markUnlocked();
    return body;
  } catch (error) {
    task.check();
    if (error.status === 401 && !cameraPreview) markLocked();
    throw error;
  }
}

let incidentReports = [], incidentTrafficReports = [];
function incidentLine(parent, value) {
  const line = document.createElement("p");
  line.textContent = value;
  parent.append(line);
}
function incidentReviewForm(report, path) {
  const form = document.createElement("form");
  const select = document.createElement("select");
  select.className = "ui-field";
  select.setAttribute("aria-label", `${report.robot_ids.map(incidentRobotName).join(", ")} 원인 분류`);
  for (const [value, label] of Object.entries(INCIDENT_CAUSES)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
  select.value = report.reviews.at(-1)?.root_cause || "unknown";
  const note = document.createElement("input");
  note.className = "ui-field";
  note.maxLength = 1000;
  note.placeholder = "판단 근거 또는 수정 내용";
  note.setAttribute("aria-label", `${report.robot_ids.map(incidentRobotName).join(", ")} 검토 메모`);
  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "검토 기록";
  form.append(select, note, save);
  form.addEventListener("submit", pageScope.guard(async event => {
    event.preventDefault();
    save.disabled = true;
    save.setAttribute("reason", "검토 기록을 저장하고 있습니다");
    try {
      await call(path, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({root_cause: select.value, note: note.value})});
      log(`${report.robot_ids.map(incidentRobotName).join(", ")} 사건 검토를 기록했습니다.`, "good");
      await refreshIncidents();
    } catch (error) {
      log(`사건 검토 기록 실패: ${error.message}`, "bad");
      save.disabled = false;
      save.removeAttribute("reason");
    }
  }));
  return form;
}
function incidentRobotName(robotId) {
  const name = view.robotNames[robotId];
  return name && name !== robotId ? `${name} (${robotId})` : robotId;
}

async function refreshIncidents() {
  if (auth.locked) return;
  const status = el("incident-status");
  try {
    const payload = await call("/api/fleet/incidents?limit=10");
    incidentReports = payload.reports || [];
    incidentTrafficReports = payload.traffic_reports || [];
    status.textContent = `최근 라인 정지 ${incidentReports.length}건 · AI 상황 사실 ${incidentTrafficReports.length}건`;
    el("incident-export").disabled = !incidentReports.length && !incidentTrafficReports.length;
    if (el("incident-export").disabled) el("incident-export").setAttribute("reason", "내보낼 사건이 없습니다");
    else el("incident-export").removeAttribute("reason");
    const list = el("incident-list");
    list.replaceChildren();
    for (const report of incidentReports) {
      const item = document.createElement("li");
      item.className = `stuck-item incident-row${report.closed_at ? " closed" : ""}`;
      const detail = document.createElement("details");
      const summary = document.createElement("summary");
      const core = report.evidence.core, fleet = report.evidence.fleet;
      const causeName = CAUSE_LABEL[core.cause] || "원인 미확인";
      summary.textContent = `${report.robot_ids.map(incidentRobotName).join(", ")} · ${causeName} · ${new Date(report.opened_at).toLocaleString("ko-KR")}`;
      detail.append(summary);
      incidentLine(detail, `판정: 라인 정지 (교착 여부 별도 판정) · ${report.closed_at ? "종료" : "진행 중"} · Fleet 종료 사유 ${fleet.close_reason || "미확인"}`);
      incidentLine(detail, `CORE: 단계 ${core.phase_at_open || "미확인"}, 정지 ${core.held_s_max ?? "미확인"}초, 재시도 ${core.attempts_max ?? "미확인"}`);
      incidentLine(detail, `Fleet: 위치 ${{LOCALIZED: "확정", DEGRADED: "정확도 저하", UNKNOWN: "확인 불가"}[fleet.pose_state] || "미확인"}, 관측 나이 ${fleet.pose_age_s ?? "미확인"}초, 해결 ${fleet.resolved_by || "미확인"}`);
      const cam = report.evidence.rosy_cam;
      incidentLine(detail, cam ? `Rosy Cam: ${cam.source_id}, seq ${cam.seq}, 촬영 ${new Date(cam.captured_at * 1000).toLocaleString()}`
        : "Rosy Cam: 사건 시작 ±5초 관측 없음");
      incidentLine(detail, report.closed_at
        ? "Pinky 앞 카메라: 사건 종료 후 이미지는 보존되지 않음"
        : "Pinky 앞 카메라: 진행 중 한 장은 위 개입 목록에서 확인 · 종료 후 이미지는 보존되지 않음");
      const ai = report.evidence.ai_facts || [];
      const draft = ai.find(f => f.kind === "incident_context");
      if (draft) {
        const names = {line_marking: "차선 표시 또는 인식", obstacle: "전방 장애물", unknown: "원인 미확정"};
        incidentLine(detail, `AI PC 원인 초안: ${names[draft.value.cause_draft] || "원인 미확정"} · 신뢰도 ${Math.round(draft.confidence * 100)}% · 사람 검토 필요`);
        for (const item of draft.value.support || []) incidentLine(detail, `${item.source} ${item.field}: ${JSON.stringify(item.value)}`);
        incidentLine(detail, `추가 확인: ${(draft.value.missing || []).join(", ")}`);
      }
      incidentLine(detail, ai.length ? `AI 참고: ${ai.map(f => `${f.kind} (${f.stage}, ${Math.round(f.confidence * 100)}%)`).join(" · ")}`
        : "AI 참고: 사건 시작 ±5초 사실 없음");
      incidentLine(detail, report.actions.length ? `조치: ${report.actions.map(a => `${a.decision} ${a.accepted === 1 ? "수락됨" : a.accepted === 0 ? "거절됨" : "결과 미확인"}`).join(" · ")}`
        : "조치: 기록 없음");
      const latest = report.reviews.at(-1);
      incidentLine(detail, latest ? `사람 검토: ${INCIDENT_CAUSES[latest.root_cause]} · ${latest.note || "메모 없음"} (${latest.principal_id})`
        : "사람 검토: 아직 없음");
      if (auth.role === "operator") {
        detail.append(incidentReviewForm(report,
          `/api/fleet/incidents/${encodeURIComponent(report.robot_ids[0])}/${encodeURIComponent(report.stuck_id)}/review`));
      }
      item.append(detail);
      list.append(item);
    }
    const trafficList = el("incident-traffic-list");
    trafficList.replaceChildren();
    for (const report of incidentTrafficReports) {
      const ai = report.evidence.ai_fact;
      const item = document.createElement("li");
      item.className = "stuck-item incident-row closed";
      const detail = document.createElement("details");
      const summary = document.createElement("summary");
      const name = report.classification === "wait_cycle_confirmed"
        ? ai.value?.fleet_agrees === false ? "AI 단독 대기 순환 판단" : "AI·Fleet 대기 순환 일치"
        : {wait_cycle_stale_input: "낡은 입력의 대기 순환 후보", waiting_but_moving: "대기 중 이동",
           livelock: "반복 경로 정체", stalled: "운행 정체", unknown_occupancy_long: "위치 불명 점유 지속"}[report.classification]
          || report.classification;
      summary.textContent = `${name} · ${report.robot_ids.map(incidentRobotName).join(", ")} · ${new Date(report.opened_at).toLocaleString("ko-KR")}`;
      detail.append(summary);
      incidentLine(detail, `AI ${ai.source} · ${ai.stage} · 신뢰도 ${Math.round(ai.confidence * 100)}%`);
      incidentLine(detail, `측정값: ${JSON.stringify(ai.value)} · 근거: ${JSON.stringify(ai.evidence)}`);
      incidentLine(detail, "CORE·Rosy Cam: 이 AI 사실과 연결된 영속 표본 없음");
      const latest = report.reviews.at(-1);
      incidentLine(detail, latest ? `사람 검토: ${INCIDENT_CAUSES[latest.root_cause]} · ${latest.note || "메모 없음"} (${latest.principal_id})`
        : "사람 검토: 아직 없음");
      if (auth.role === "operator") detail.append(incidentReviewForm(report,
        `/api/fleet/incidents/facts/${ai.fact_row}/review`));
      item.append(detail);
      trafficList.append(item);
    }
    if (!incidentTrafficReports.length) {
      const empty = document.createElement("li");
      empty.textContent = "저장된 AI 상황 사실이 없습니다.";
      trafficList.append(empty);
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    status.textContent = `사건 기록을 불러오지 못했습니다: ${error.message}`;
  }
}
pageScope.listen(el("incident-refresh"), "click", refreshIncidents);
pageScope.listen(el("incident-export"), "click", async () => {
  try {
    const payload = await call("/api/fleet/incidents?limit=100");
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = "rosy-incidents.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    if (error.name !== "AbortError") log(`사건 JSON 내보내기 실패: ${error.message}`, "bad");
  }
});

async function refreshDispatchControl(life = pageScope.capture()) {
  life.check();
  const title = el("dispatch-control-title");
  const detail = el("dispatch-control-detail");
  const rearm = el("dispatch-rearm");
  if (!dispatchGate.due()) return view.dispatchControl;
  try {
    const state = await call("/api/fleet/dispatch-control", {signals: [life.signal]});
    life.check();
    dispatchGate.ok();
    view.dispatchControl = state;
    // D-493 — 띠의 글은 알릴 상태가 있을 때만 보인다(styles.css가 data-state로 접는다).
    el("dispatch-control").dataset.state = state.dispatch_enabled ? "enabled"
      : state.reason === "PROCESS_RESTARTED" ? "restarted" : "latched";
    if (state.dispatch_enabled) {
      title.textContent = "발행 허용";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개`;
    } else if (state.reason === "PROCESS_RESTARTED") {
      title.textContent = "재시작 뒤 발행 대기";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
    } else {
      title.textContent = "정지 래치로 발행 차단";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
    }
    rearm.hidden = !(auth.role === "operator" && !state.dispatch_enabled);
    // D-540 9: 재허가는 대기 작업을 다시 움직이므로 이름 있는 운영자만.
    const rearmNamed = namedOperatorReason(auth.role, auth.principal);
    rearm.disabled = auth.locked || !state.rearm_available || Boolean(rearmNamed);
    if (rearm.disabled) rearm.setAttribute("reason", auth.locked ? "관제 토큰 필요" : rearmNamed || "재허가 조건 미충족");
    else rearm.removeAttribute("reason");
    return state;
  } catch (err) {
    if (err.name === "AbortError") return;
    if (auth.locked) return;
    view.dispatchControl = null;
    const absent = dispatchGate.fail(err.status, err.code) === "absent";
    el("dispatch-control").dataset.state = absent ? "absent" : "error";
    if (absent) {
      // 작업 대기열이 없는 Fleet — 발행 래치 자체가 없다. 오류가 아니다.
      title.textContent = "발행 제어 미설정";
      detail.textContent = "이 Fleet에는 작업 대기열이 설정되지 않았습니다.";
    } else {
      title.textContent = "발행 상태를 확인할 수 없음";
      detail.textContent = "상태 확인에 실패해 재허가를 사용할 수 없습니다.";
    }
    rearm.hidden = true;
    rearm.disabled = true;
    rearm.setAttribute("reason", "발행 상태 확인 불가");
    return null;
  }
}

pageScope.listen(el("dispatch-rearm"), "click", async () => {
  const state = view.dispatchControl;
  await confirmedAction.run({message: `세대 ${state?.generation}의 대기 발행을 재허가할까요?`, opener: el("dispatch-rearm"),
    eligible: () => state?.rearm_available && view.dispatchControl?.rearm_available && state.generation === view.dispatchControl.generation,
    request: async owner => {
    await call("/api/fleet/dispatch/rearm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_generation: state.generation }),
      signals: [owner.signal],
    });
    if (!owner.current()) return;
    log("대기 작업 발행을 재허가했습니다.", "good");
    await refreshDispatchControl(owner);
  }, onError: err => log(`발행 재허가 거부: ${err.message}`, "bad")});
});


// --- 로봇 목록 --------------------------------------------------------------

function render() {
  const rosterBox = el("roster");
  const focused = document.activeElement;
  const focusedCard = focused?.closest?.("#roster article");
  const focusedId = focusedCard?.dataset.robotId;
  const focusedButton = focusedCard && focused !== focusedCard
    ? [...focusedCard.querySelectorAll("ui-button, button")].indexOf(focused) : -1;
  // D-540 3 — every robot has a card; a nominal one is one line (roster.card decides). Exceptions first
  // (D-201); the colour index stays the robot's own.
  if (view.robots.length) {
    const order = [...view.robots.keys()].sort((a, b) =>
      roster.needsAttention(view.robots[b]) - roster.needsAttention(view.robots[a]));
    roster.place(rosterBox, order.map((index) => roster.card(view.robots[index], index)));
  } else {
    const message = auth.locked ? "관제에 접속하면 등록 로봇과 연결 상태를 확인할 수 있습니다."
      : view.stateUnavailable ? "Fleet 상태를 확인할 수 없습니다. 연결을 확인하세요."
      : view.stateLoaded ? "등록된 로봇이 없습니다. 발견 목록에서 페어링 상태를 확인하세요."
        : "로봇 목록 불러오는 중";
    if (rosterBox.childElementCount !== 1 ||
        rosterBox.firstElementChild?.getAttribute("role") !== "status" ||
        rosterBox.firstElementChild.textContent !== message) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.setAttribute("role", "status");
      empty.textContent = message;
      rosterBox.replaceChildren(empty);
    }
  }
  if (focusedId && document.activeElement !== focused) {  // a kept card (roster.place) still has it
    const nextCard = [...rosterBox.querySelectorAll("article")]
      .find((card) => card.dataset.robotId === focusedId);
    const nextFocused = focusedButton >= 0
      ? nextCard?.querySelectorAll("ui-button, button")[focusedButton] : nextCard;
    nextFocused?.focus({preventScroll: true});
  }
  signals.render();
  roster.fillQueues();
  roster.trip.syncConvoy();  // D-540 (d) 대형·대열
  lineStuck.render();
  tripReplan.render();

  formation.fillLeaders();
  // Map labels always show for 최우선 robots (warn causes are often fleet-wide); the rest declutter.
  view.attention = new Set(view.robots.filter((r) => roster.attentionItems(r).some((i) => i.severity === "crit")).map((r) => r.robot_id));
  mapView.draw();
  applyRoleToControls(auth.role, operatorControls());
  const hint = el("hint");
  const point = view.selected && view.cursor && view.map
    ? mapView.toWorld(view.map, view.cursor.col, view.cursor.row) : null;
  const nextHint = point
    ? `${view.selected} 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m · 방향키로 이동, Enter로 확인, Escape로 취소`
    : view.map
      ? "로봇 카드의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다."
      : view.siteMap
        ? "천장 카메라 관측 전용 지도입니다. 목표 지정은 로봇 지도가 수신되면 사용할 수 있습니다."
        : "지도가 수신되면 로봇의 목표 지정을 사용할 수 있습니다.";
  if (hint.textContent !== nextHint) hint.textContent = nextHint;
  refreshDiagnostics();
}

let pathSample = { proxy: null, fleet: null, vision: null };
let statePollInFlight = false;

function paintSitePath() {
  const list = el("site-path-list");
  const rows = [proxyRow(pathSample.proxy), fleetRow(pathSample.fleet), visionRow(pathSample.vision)];
  const summary = sitePathSummary(rows);
  const summaryNode = el("site-path-summary");
  if (summaryNode.textContent !== summary) summaryNode.textContent = summary;
  summaryNode.dataset.kind = rows.find((row) => row.kind === "crit")?.kind
    || rows.find((row) => row.kind === "warn")?.kind || "good";
  list.replaceChildren(...rows.map((row) => {
    const item = document.createElement("li");
    const name = document.createElement("b");
    name.textContent = row.name;
    const word = document.createElement("ui-tag");
    // ui-tag's nominal status is active. kind "good" is that word; "good" itself has no rule.
    word.setAttribute("status", row.kind === "good" ? "active" : row.kind);
    word.textContent = row.word;
    item.append(name, word);
    return item;
  }));
}

async function refreshHealthz() {
  const life = pageScope.capture();
  try {
    const response = await fetch("/healthz", { cache: "no-store", signal: life.signal });
    const body = await response.json();
    if (!life.current()) return;
    pathSample.proxy = { finished: true, status: response.status, body };
  } catch (err) {
    if (err.name === "AbortError") return;
    pathSample.proxy = { finished: false };
  }
  paintSitePath();
}
pageScope.onDispose(() => {
  statePollInFlight = false;
  view.selected = null;
  view.cursor = null;
  document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close("cancel"));
});
async function refreshState() {
  const life = pageScope.capture();
  life.check();
  if (auth.locked || statePollInFlight) return;
  statePollInFlight = true;
  let fleetAnswered = false;
  try {
    const snapshot = await call("/api/fleet/state");
    life.check();
    pathSample.fleet = { finished: true, status: 200 };
    fleetAnswered = true;
    paintSitePath();
    view.robots = snapshot.robots;
    view.receivedAtMs = Date.now();  // D-493: 큐 신선도는 받은 뒤 흐른 시간을 더한다
    if (requestedRobotFocus) roster.openCard(requestedRobotFocus);
    view.stateUnavailable = false;
    view.stateLoaded = true;
    if (view.selected) {
      const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
      if (!selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
        disarmGoal("안전·연결 상태가 바뀌어 목표 지정 취소");
      }
    }
    view.signals = snapshot.signals || {};
    showFleet(snapshot.fleet, snapshot.robots);
    render();
    if (requestedRobotFocus) {
      const card = [...el("roster").querySelectorAll("article")]
        .find(node => node.dataset.robotId === requestedRobotFocus);
      if (card) card.focus();
      requestedRobotFocus = null;
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    if (!fleetAnswered) {
      pathSample.fleet = typeof err.status === "number"
        ? { finished: true, status: err.status }
        : { finished: false };
      paintSitePath();
    }
    // D-248: 잠금 pill(토큰 필요)을 서버 없음으로 덮지 않는다 — 401의 이유를 남긴다.
    if (auth.locked) return;
    view.stateUnavailable = true;
    if (view.selected) disarmGoal("Fleet 상태를 확인할 수 없어 목표 지정 취소");
    render();
    const pill = el("online-pill");
    pill.textContent = "Fleet 서버 없음";
    pill.setAttribute("status", "crit");
  } finally {
    if (life.current()) statePollInFlight = false;
  }
}

function disarmGoal(reason) {
  view.selected = null;
  view.cursor = null;
  const canvas = el("map-canvas");
  canvas.classList.add("idle");
  canvas.tabIndex = -1;
  log(reason, "bad");
}

let scannerLost = false;

async function refreshDiscovery() {
  const life = pageScope.capture();
  life.check();
  // D-410 — 발견 목록·등록은 설치 화면에 있다. 운용 화면은 검색기 건강과
  // 고정 주소 판정(로스터 안내)만 이 요청에서 얻는다.
  if (auth.locked) return;
  if (!discoveryGate.due()) return;
  try {
    const snapshot = await call("/api/fleet/discovery");
    life.check();
    discoveryGate.ok();
    let names = { ...view.robotNames };
    try {
      const listing = await call("/api/fleet/enrollment/robots");
      life.check();
      names = Object.fromEntries((listing.robots || [])
        .filter((row) => row.robot_id && row.hostname)
        .map((row) => [row.robot_id, row.hostname]));
    } catch (err) {
      if (err.name === "AbortError") return;
    }
    for (const device of snapshot.devices || []) {
      if (device.status === "enrolled" && device.robot_id && device.name) names[device.robot_id] = device.name;
    }
    if (JSON.stringify(names) !== JSON.stringify(view.robotNames)) {
      view.robotNames = names;
      render();
      await refreshIncidents();
    }
    const pending = snapshot.scanner_online
      ? (snapshot.devices || []).filter((device) => device.status === "registration_pending") : [];
    const pendingNote = el("discovery-pending");
    const summary = pending.length
      ? `발견됐지만 미등록 ${pending.length}대: ${pending.map((device) => device.name).join(", ")}` : "";
    if (pendingNote.firstElementChild.textContent !== summary) pendingNote.firstElementChild.textContent = summary;
    pendingNote.hidden = !summary;
    await refreshAddresses();
    life.check();
    // 검색기 임대(45 s)가 끊기면 새 주소 안내가 멈춘다 — 대기와 구별해 알린다.
    if (snapshot.scanner_state === "expired") {
      if (!scannerLost) log("발견 검색기 끊김 — 로봇 발견·주소 이동 안내 불가", "bad");
      scannerLost = true;
      return;
    }
    if (scannerLost && snapshot.scanner_online) log("발견 검색기 다시 연결됨", "good");
    scannerLost = false;
  } catch (err) {
    if (err.name === "AbortError") return;
    if (auth.locked) return;
    if (discoveryGate.fail(err.status, err.code) === "absent") return;
  }
}

// 고정 주소 판정은 발견과 같은 주기로 읽는다. 못 읽으면 까닭 줄을 지운다(짐작하지 않는다).
let addressText = "";

// D-410 — 주소 이동 대화상자(로봇 화면 코드)는 설치 화면에 있다. 운용 화면의
// 이동 안내는 그 화면으로 가는 링크로만 말한다.
function moveLink() {
  const node = document.createElement("a");
  node.href = "/console/install";
  node.textContent = "설치 화면에서 이동";
  return node;
}

async function refreshAddresses() {
  const life = pageScope.capture();
  life.check();
  let payload = null;
  try {
    payload = await call("/api/fleet/discovery/addresses");
    life.check();
  } catch (_err) {
    if (_err.name === "AbortError") return;
    payload = null;
  }
  const banner = el("address-banner");
  const text = renumberBanner(payload, view.robots);
  banner.hidden = !text;
  if (text && banner.textContent !== text) banner.textContent = text;
  // 옮길 수 있는 로봇마다 한 줄과 그 로봇의 지름길. 옮기기마다 그 로봇의 화면 코드를 묻는다.
  const movable = movableRobots(payload);
  const next = JSON.stringify([payload?.robots || [], auth.role, auth.principal]);
  if (next !== addressText) {
    addressText = next;
    el("address-movable").replaceChildren(...movable.map((entry) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${entry.robot_id} → ${entry.seen_addresses[0]}`;
      item.append(label, moveLink());
      return item;
    }));
    view.addresses = addressMap(payload);
    render();
  }
  el("address-drift").hidden = !text && movable.length === 0;
}

async function refreshAuthorization() {
  const life = pageScope.capture();
  life.check();
  // 로그인·토큰 저장마다 꺼진 기능을 한 번씩 다시 묻는다.
  dispatchGate.reset();
  discoveryGate.reset();
  mapView.resetPolling();
  try {
    const identity = await call("/api/fleet/session");
    life.check();
    if (auth.role !== identity.role) confirmedAction.cancel();
    auth.role = identity.role;
    auth.principal = identity.principal_id;
    showSession(identity);
    // The session already proves the token: unlock now. The state gather can take seconds
    // when a robot times out, and must not hold the operator's controls locked behind it.
    const pill = el("online-pill");
    if (pill.dataset.locked === "true") {
      delete pill.dataset.locked;
      pill.textContent = "상태 확인 중";
      pill.setAttribute("status", "neutral");
    }
    applyRoleToControls(auth.role, operatorControls());
    loginForm.refresh(false);
    render();
    // Independent panels refresh side by side; one slow source does not delay the rest.
    // The map too: a token issued after a lock must not wait for the next 5 s map poll (field check 2026-10-10).
    await Promise.allSettled([
      refreshIncidents(),
      mapView.refresh(),
      refreshState(),
      refreshDispatchControl(),
      refreshDiscovery(),
      formation.refreshFormation(),
    ]);
    life.check();
    render();
  } catch (_err) {
    if (_err.name === "AbortError") return;
    if (!auth.locked) markLocked(_err.status === 401 ? "auth" : "connection");
  }
}

// --- 조작 ------------------------------------------------------------------

// D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
// ↑/↓ 로 로스터를 순회하고, Enter 로 그 로봇의 목표 지정을 누르고,
// Escape 으로 선택을 해소한다. 입력 컨트롤에 있을 땐 간섭하지 않는다.
// 포커스 링은 표면 전역 :focus-visible 규약이 그린다.
pageScope.listen(document, "keydown", (event) => {
  if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas")) return;
  const cards = [...document.querySelectorAll("#roster article")];
  if (!cards.length) return;
  const active = document.activeElement;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const idx = cards.indexOf(active);
    const next = idx < 0
      ? cards[event.key === "ArrowDown" ? 0 : cards.length - 1]
      : cards[(idx + (event.key === "ArrowDown" ? 1 : -1) + cards.length) % cards.length];
    next.focus();
  } else if (event.key === "Enter" && cards.includes(active)) {
    const aim = active.querySelector(".robot-actions ui-button");
    if (aim && !aim.disabled) {
      event.preventDefault();
      aim.click();
    }
  } else if (event.key === "Escape" && view.selected) {
    const selectedCard = cards.find((c) => c.classList.contains("selected"));
    const aim = selectedCard && selectedCard.querySelector(".robot-actions ui-button");
    if (aim) aim.click();
  }
});

async function commitGoal(col, row) {
  const life = pageScope.capture();
  life.check();
  if (!view.selected || !view.map) return;
  const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
  if (view.stateUnavailable || auth.role !== "operator" || namedReason() ||
      !selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
    disarmGoal("안전·연결·권한 상태를 확인할 수 없어 목표 지정 취소");
    render();
    return;
  }
  const point = mapView.toWorld(view.map, col, row);
  const robotId = view.selected;
  const mapSnapshot = JSON.stringify([view.map.map_id, view.map.width, view.map.height, view.map.resolution, view.map.origin]);
  await confirmedAction.run({message: `${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`, opener: el("map-canvas"),
    eligible: () => !view.stateUnavailable && view.selected === robotId && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false)
      && mapSnapshot === JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]),
    request: async owner => {
  view.selected = null;
  view.cursor = null;
  const canvas = el("map-canvas");
  canvas.classList.add("idle");
  canvas.tabIndex = -1;
  render();
  focusGoalButton(robotId);
    const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ x: point.x, y: point.y, yaw: 0 }),
      signals: [owner.signal],
    });
    if (!owner.current()) return;
    const task = result && result.task ? result.task : null;
    if (task && task.status === "QUEUED") {
      view.pendingTasks[robotId] = task;
      const why = task.reason || result.reason || "READY";
      const blockedBy = task.waiting_on?.length ? ` · ${task.waiting_on.join(", ")}` : "";
      const position = task.queue_position ? `#${task.queue_position}` : "순번 대기";
      log(`${robotId} task ${task.task_id} QUEUED · ${position} · ${why}${blockedBy} · 취소 가능`, "good");
      return;
    }
    if (task && task.status === "UNKNOWN") {
      view.pendingTasks[robotId] = task;
      log(`${robotId} task ${task.task_id} UNKNOWN · CORE 결과 수동 확인 필요`, "bad");
      return;
    }
    if (task && task.status !== "ACCEPTED") {
      log(`${robotId} task ${task.task_id} ${task.status}${task.reason ? ` · ${task.reason}` : ""}`, "bad");
      return;
    }
    if (task) delete view.pendingTasks[robotId];
    const receipt = task ? task.receipt : result;
    const where = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    if (receipt && receipt.queued) {
      log(`${robotId} → ${where} ${roster.queuedReason(result)}`,
          receipt.reason === "NO_YIELD_SPACE" ? "bad" : "");
    } else {
      log(`${robotId} → ${where} 미션 하달`, "good");
    }
  }, onError: err => log(`${robotId} 미션 거절 — ${err.message}`, "bad")});
}

function focusGoalButton(robotId) {
  [...document.querySelectorAll("#roster ui-button[data-goal-robot-id]")]
    .find(button => button.dataset.goalRobotId === robotId)?.focus({preventScroll: true});
}

// D-593 운영자 핀: 누른 점 = 위치, 끈 방향 = 로봇 앞(3 px 미만이면 지금 지도 자세의 방향, 없으면 0).
let pinStart = null;
function canvasWorld(event) {
  const rect = el("map-canvas").getBoundingClientRect();
  if (!view.map) {
    const world = view.siteToWorld?.(event.clientX - rect.left, event.clientY - rect.top);
    return world ? { ...world, px: event.clientX, py: event.clientY } : null;
  }
  const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
  const offX = (rect.width - view.map.width * scale) / 2, offY = (rect.height - view.map.height * scale) / 2;
  const col = (event.clientX - rect.left - offX) / scale, rowFromTop = (event.clientY - rect.top - offY) / scale;
  if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return null;
  const row = view.map.height - rowFromTop;
  return { x: view.map.origin.x + col * view.map.resolution, y: view.map.origin.y + row * view.map.resolution,
    px: event.clientX, py: event.clientY };
}
pageScope.listen(el("map-canvas"), "pointerdown", (event) => {
  if (!view.pinning || (!view.map && !view.siteMap)) return;
  pinStart = canvasWorld(event);
});
pageScope.listen(el("map-canvas"), "pointerup", async (event) => {
  const life = pageScope.capture();
  const start = pinStart, end = canvasWorld(event);
  pinStart = null;
  const robotId = view.pinning;
  if (!robotId || !start) return;
  const dragged = end && Math.hypot(end.px - start.px, end.py - start.py) >= 3;
  const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robotId);
  const current = guideRow?.pose;
  const yaw = dragged ? Math.atan2(end.y - start.y, end.x - start.x) : (typeof current?.yaw === "number" ? current.yaw : 0);
  view.pinning = null;
  el("map-canvas").classList.add("idle");
  render();
  // D-596 amendment (b): an LED-confirmed blob is the place; the press and drag only set the heading.
  let led = null;
  try {
    led = pinPrefill(await call("/api/fleet/tracking/identity", { signals: [life.signal] }), guideRow, robotId);
  } catch (error) {
    if (error.name === "AbortError") return;
  }
  if (!life.current()) return;
  const place = led || start;
  const deg = (yaw * 180 / Math.PI).toFixed(0);
  const where = led ? "LED로 확인된 자리" : "지도 위치";
  await confirmedAction.run({message: `${robotId}의 ${where}를 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) m, 방향 ${deg}°로 찍을까요? 로봇에는 아무것도 보내지 않습니다.`,
    opener: el("map-canvas"), eligible: () => !view.stateUnavailable && !namedReason(),
    request: async (owner) => {
      const pose = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/map-pin`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: place.x, y: place.y, yaw }), signals: [owner.signal] });
      if (!owner.current() || !life.current()) return;
      log(`${robotId} 운영자 핀 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) ${deg}° · ${{ LOCALIZED: "확정", DEGRADED: "추정" }[pose?.state] || "위치 모름"}`, "good");
      mapView.refreshGuide?.();
    }, onError: (err) => log(`${robotId} 위치 찍기 거절 — ${err.message}`, "bad")});
});

pageScope.listen(el("map-canvas"), "click", async (event) => {
  const life = pageScope.capture();
  life.check();
  if (!view.selected || !view.map) return;
  const canvas = el("map-canvas");
  const rect = canvas.getBoundingClientRect();
  // D-201 — 캔버스는 object-fit: contain 으로 그려진다. 레터박스(빈 여백)를
  // 제외한 그려진 영역 안에서만 셀 좌표가 성립한다.
  const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
  const drawnW = view.map.width * scale;
  const drawnH = view.map.height * scale;
  const offX = (rect.width - drawnW) / 2;
  const offY = (rect.height - drawnH) / 2;
  const col = ((event.clientX - rect.left - offX) / drawnW) * view.map.width;
  const rowFromTop = ((event.clientY - rect.top - offY) / drawnH) * view.map.height;
  if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) {
    return; // 여백을 찍은 것 — 목표가 아니다.
  }
  view.cursor = { col: Math.floor(col), row: view.map.height - 1 - Math.floor(rowFromTop) };
  render();
  await commitGoal(view.cursor.col, view.cursor.row);
  life.check();
});

pageScope.listen(el("map-canvas"), "keydown", async (event) => {
  const life = pageScope.capture();
  life.check();
  if (view.pinning && event.key === "Escape") {  // D-593: 위치 찍기 취소
    event.preventDefault(); view.pinning = null; el("map-canvas").classList.add("idle"); render(); return;
  }
  if (!view.selected || !view.map || !view.cursor) return;
  const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
  if (event.key in moves) {
    event.preventDefault();
    const [dx, dy] = moves[event.key];
    view.cursor.col = Math.max(0, Math.min(view.map.width - 1, view.cursor.col + dx));
    view.cursor.row = Math.max(0, Math.min(view.map.height - 1, view.cursor.row + dy));
    render();
  } else if (event.key === "Enter") {
    event.preventDefault();
    await commitGoal(view.cursor.col, view.cursor.row);
    life.check();
  } else if (event.key === "Escape") {
    event.preventDefault();
    const robotId = view.selected;
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    render();
    focusGoalButton(robotId);
  }
});

// 전체 정지는 한 번의 누름으로 즉시 실행된다(D-413 — 비상 정지는 확인 없는 비상 출구.
// D-371이 대화상자 위에서 살아 있게 한 이유를 끝까지 밀었다: 어떤 사위에도 즉시 눌린다).
bindEstop(call, {listen: (node, type, fn) => pageScope.listen(node, type, fn), life: () => pageScope.capture(), log,
  after: () => refreshDispatchControl()});


// D-421 — 래치 없는 전체 주행 취소. 응답은 CORE 응답 수이지 물리 정지가 아니다(D-298).
const CANCEL_ALL_RESULT = { failed: "실패", unreachable: "응답 없음" };
const CANCEL_ALL_STEP = { swarm: "대형 추종", navigation: "내비게이션", line_follow: "차선 추종" };
// D-540 6 (user decision 2026-10-10): a stop — no confirm, any operator, no latch; the line says it was sent.
pageScope.listen(el("cancel-all"), "click", async () => {
  if (auth.locked) return;
  const life = pageScope.capture();
  cancelAllNotice(`전체 주행 취소를 보냈습니다 · ${view.robots.length}대 · 응답 기다리는 중`);
  try {
    const result = await call("/api/fleet/cancel-all", { method: "POST", signals: [life.signal] });
    if (!life.current()) return;
    // 0/0 은 성공이 아니다 — 취소할 로봇이 없었다.
    const allAnswered = result.total > 0 && result.cancelled === result.total;
    const summary = result.total === 0 ? "주행 취소 대상 로봇 없음 — 등록된 로봇을 확인하세요"
      : `주행 취소 요청 응답: ${result.cancelled}/${result.total} · 물리 정지 미확인`;
    cancelAllNotice(result.total === 0 ? summary : `전체 주행 취소를 보냈습니다 · ${result.total}대 · ${summary}`,
      result.total > 0 && !allAnswered);
    log(summary, allAnswered ? undefined : "bad");
    result.robots.filter((r) => r.result !== "cancelled").forEach((r) => {
      const steps = Object.entries(r.steps).filter(([, step]) => !step.ok).map(([name, step]) =>
        step.error?.sent === false && name === "line_follow" ? "주소 미확인 — 차선 추종 끄기 미전송"
          : `${CANCEL_ALL_STEP[name] || name} ${step.error?.code || "—"}`);
      log(`  ${r.robot_id} 주행 취소 ${CANCEL_ALL_RESULT[r.result] || r.result} — ${steps.join(" · ")}`, "bad");
    });
    const awaiting = result.robots.reduce((n, r) => n + r.tasks.awaiting_core_result.length, 0);
    log(result.tasks.error ? "대기 작업 취소 실패 — 작업 저장소를 확인하세요"
      : `대기 작업 ${result.tasks.canceled.length}개 취소 · 로봇 취소 확인 대기 작업 ${awaiting}개`,
    result.tasks.error ? "bad" : undefined);
    // CORE 가 취소를 확인하면 그 로봇은 다시 배정되고, 확인이 없으면 작업은 대조가 필요하다.
    if (awaiting) log("  확인 대기 작업: 로봇이 취소를 알리면 다시 배정, 알리지 않으면 대조 필요", "bad");
    await refreshDispatchControl(life);
  } catch (err) {
    if (err.name === "AbortError" || !life.current()) return;
    cancelAllNotice(err.status >= 500 || !err.status
      ? "주행 취소 결과 확인 불가 — Fleet 연결과 로봇 상태를 다시 확인하세요."
      : `주행 취소 요청 거절 — ${err.message}`);
    log(`전체 주행 취소 실패 — ${err.message}`, "bad");
  }
});


// D-262: 대형 패널은 formation.js 팩토리가 가진다. 셸은 지도 오버레이와
// 명렬 렌더를 쥐고, 대형 상태는 view.formation 으로 공유한다.
// D-540 9: 움직이는 조작의 잠금 사유. 멈춤(비상 정지·취소·대형 해제·막힘 대기/중단)에는 쓰지 않는다.
const namedReason = () => namedOperatorReason(auth.role, auth.principal);
const formation = createFormation({ scope: pageScope, el, view, log, call, render, namedReason });
formation.bind();

// Fleet 분해 4: 현장 지도 뷰는 map-view.js 팩토리가 그린다.
const mapView = createMapView({ scope: pageScope,
  el, view, auth, call,
  onMapChanged: render,
  onTrafficChanged: render,
  onMapUnavailable: () => {
    const selected = view.selected;
    if (selected) disarmGoal("지도를 확인할 수 없어 목표 지정 취소");
    render();
    if (selected) focusGoalButton(selected);
  },
});

// Fleet 분해 3: 명렬 카드와 큐는 roster.js 팩토리가 그린다.
// D-410 — 주소 이동 조작은 설치 화면이 소유해서 moveAddress 훅을 주지 않는다.
const roster = createRoster({ scope: pageScope, el, view, log, call, render,
  streamEvidence: mapView.streamEvidence, isOperator: () => auth.role === "operator", namedReason, confirmedAction });
view.openLeaderTrip = (robotId) => { roster.openCard(robotId); roster.trip.focus(robotId); render(); };
// D-407 / D-540 3 — 막힘 판단과 바뀐 경로 확인은 예외 큐 행이 펼친 자리에 산다.
const lineStuck = createLineStuckPanel({ scope: pageScope, view, call, log,
  isOperator: () => auth.role === "operator", namedReason });
const tripReplan = createTripReplan({ scope: pageScope, view, call, log,
  isOperator: () => auth.role === "operator", namedReason,
  openCard: (robotId) => { roster.openCard(robotId); render(); } });

// D-415 — 로그 지우기
pageScope.listen(el("log-clear"), "click", () => {
  const box = el("log");
  box.replaceChildren(document.createElement("ui-empty"));
  box.firstChild.textContent = "지웠습니다.";
  el("cancel-all-details").hidden = true;
});

// D-415 — 진단 패널 갱신: 상태 주기·발견·로봇 오류·카메라
let lastStateOk = null;
function refreshDiagnostics() {
  const diag = (id, text) => {
    const node = el(id);
    if (node) node.textContent = text;
  };
  diag("diag-state", view.stateUnavailable ? "불가"
    : `${view.robots.length}대 · ${view.stateLoaded ? "갱신됨" : "대기"}`);
  diag("diag-scanner", scannerLost ? "끊김"
    : "정상");
  const robotErrors = view.robots
    .filter((r) => r.error)
    .map((r) => `${r.robot_id}: ${r.error.reachable === false ? "닿지 않음" : "거부"} ${r.error.code ?? ""}`.trim());
  diag("diag-robots", robotErrors.length ? robotErrors.join(" · ") : "오류 없음");
  diag("diag-vision", el("vision-state")?.textContent ?? "—");
}

// D-262: 신호등 카드는 signals.js 팩토리가 그린다.
const signals = createSignals({ scope: pageScope, el, view, log, call, refreshState,
  isOperator: () => auth.role === "operator" && !auth.locked, namedReason });
// D-410 — 운용 화면의 카메라는 영상 프리뷰만 띄운다. 경기장/맵 보정 뷰는 설치 화면이 가진다.
const visionView = createVisionView({
  scope: pageScope, el, call, rawOnly: true,
  onSources: (sample) => { pathSample.vision = sample; paintSitePath(); },
});
mapView.bindCamera(visionView);

// --- 신호등 (ROSY-SIGNAL-001) --------------------------------------------------

const trackingView = createTrackingView({ scope: pageScope, el, view, call, auth, onChanged: () => mapView.draw() });

// 토큰 입력 — Enter 와 버튼 모두 저장한다 (form 이 아니라 keydown 이다).
el("console-token").value = auth.token;
function saveToken() {
  useToken(el("console-token").value.trim());
}

function useToken(token) {
  stopNotice();
  cancelAllNotice();
  pageScope.invalidate();
  auth.token = token;
  // 새 토큰은 직접 재시도한다 — 잠금 플래그가 있으면 직접 호출도 건너뛰므로 먼저 푼다.
  auth.role = null;
  applyRoleToControls(null, operatorControls());
  incidentReports = [];
  incidentTrafficReports = [];
  el("incident-list").replaceChildren();
  el("incident-traffic-list").replaceChildren();
  el("incident-export").disabled = true;
  el("incident-export").setAttribute("reason", "관제 접속 후 내보낼 수 있습니다");
  el("incident-status").textContent = "관제 접속 후 사건을 불러옵니다.";
  if (auth.token) {
    sessionStorage.setItem("rosy-console-token", auth.token);
  } else {
    sessionStorage.removeItem("rosy-console-token");
  }
  visionView.reset();
  trackingView.reset();
  trackingView.refresh();
  refreshAuthorization();
  visionView.refreshSources();
}
pageScope.listen(el("token-save"), "click", saveToken);
// D-519 — login and logout change the cookie; drop any token so the cookie (or the lock) decides.
const loginForm = createPasswordLogin(el("password-login"), {onChange: () => {
  el("console-token").value = "";
  useToken("");
}});
pageScope.listen(el("console-token"), "keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

// D-473 — development connection mode. The badge is on only while the server says development;
// paired, 404 (an older Fleet) or an error leaves the token field as the way in.
async function connectionMode() {
  try {
    const info = await fleetClient("/api/fleet/auth/connection");
    el("development-badge").hidden = info?.mode !== "development";
    el("token-access").hidden = info?.mode === "development";
    return info?.mode === "development";
  } catch (_err) {
    return false;
  }
}

// Called on the first 401 of a lock only, so a refused or rate-limited issue (403/429) is one
// request, not a loop. useToken() invalidates in-flight polls so their stale 401s are dropped.
async function renewDevelopmentSession() {
  if (!(await connectionMode())) return;
  let token;
  try {
    token = await issueDevelopmentSession(fleetClient);  // at most one per minute per page
  } catch (_err) {
    return;
  }
  if (token) useToken(token);
}

// D-359 §4 — 로봇 계열 색은 ui.js(window.RosyPalette)가 캔버스용으로 푼다. 테마가
// 바뀌면 다시 풀고 지도를 새로 고침 없이 다시 그린다(캐시는 ui.js가 먼저 비운다).
const robotColours = () => ["--robot-1", "--robot-2", "--robot-3"].map((name) => window.RosyPalette.cssColor(name));
view.colors = robotColours();
pageScope.listen(document, "rosy:theme", () => {
  view.colors = robotColours();
  mapView.draw();
});
tickClock();
pageScope.interval(tickClock, 1000);
applyRoleToControls(null, operatorControls());
render();
paintSitePath();
connectionMode();
refreshState();
refreshAuthorization();
visionView.refreshSources();
mapView.refresh();
trackingView.refresh();
pageScope.interval(() => { if (!auth.locked) formation.refreshFormation(); }, MAP_MS);
pageScope.interval(refreshState, STATE_MS);
pageScope.interval(refreshHealthz, STATE_MS);
pageScope.interval(() => signals.presence(), STATE_MS);
pageScope.interval(() => { if (!auth.locked) refreshDispatchControl(); }, STATE_MS);
pageScope.interval(refreshDiscovery, MAP_MS);
pageScope.interval(() => mapView.refresh(), MAP_MS);
pageScope.interval(() => mapView.refreshSightings(), STATE_MS);
pageScope.interval(() => mapView.refreshTraffic(), STATE_MS);
pageScope.interval(() => mapView.refreshGuide(), STATE_MS);  // D-536
pageScope.interval(() => trackingView.refresh(), TRACKING_MS);
pageScope.interval(() => visionView.refreshFrame(), 1500);

pageScope.onResume(() => {
  visionView.reset();
  trackingView.reset();
  trackingView.refresh();
  refreshAuthorization();  // refreshes the map once the session answers
  visionView.refreshSources();
});
