// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createConnectionView } from "./connection-view.js";
import { createFormation } from "./formation.js";
import { motionCommandReason } from "./motion-readiness.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { cardTripLine, placeOptions } from "./card-trip.js";
import { createInboxPanel } from "./inbox.js";
import { createWorkView } from "./work-view.js";
import { createChannelRequestView } from "./channel-request-view.js";
import { createIncidentView } from "./incident-view.js";
import { createLineStuckPanel } from "./line-stuck.js";
import { createDeviceWatch } from "./device-watch.js";
import { createTripReplan } from "./trip-replan.js";
import { createSignals } from "./signals.js";
import { createTrackingView } from "./tracking-view.js";
import { createVisionView } from "/console/assets/vision-view.js";
import { applyRoleToControls, namedOperatorReason, OPERATOR_REASON } from "/console/assets/authorization.js";
// D-410 — 기기 등록·카메라 연결 승인·경기장/맵 보정은 설치 화면(install.js)이 가진다.
import { createDeviceDiscovery } from "/console/assets/device-discovery.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { createFleetClient } from "/common/fleet-client.js";
import { confirmIrreversible } from "/common/ui.js";
import { createConfirmedAction } from "./confirmed-action.js";
import { createPageScope } from "/common/scope.js";
import { area, areaNav } from "/console/assets/area-nav.js";
import { bindEstop, noteLink, tickClock } from "/console/assets/fleet-header.js";
// D-798 3.2 — 접속·잠금, 목표 지정, 읽기 갱신은 각자의 팩토리 파일이 가진다.
import { createConsoleAuth } from "./console-auth.js";
import { createConsoleGoal } from "./console-goal.js";
import { createConsoleRefresh } from "./console-refresh.js";
import { createAssistantPanel } from "/console/assets/assistant.js";
const pageScope = createPageScope();
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.


const el = (id) => document.getElementById(id);
const layoutMedia = matchMedia("(min-width: 64rem)");
// Current intervention stays outside context tabs; hidden panels keep their owners mounted.
const layoutPanels = [document.querySelector('.queues-panel'), document.querySelector('[aria-labelledby="map-heading"]'),
  document.querySelector('.console-context')];
const MAP_PANEL = 1;
const channelRequestView = createChannelRequestView({scope: pageScope, call, el,
  robots: () => view.robots,
  canManage: () => !auth.locked && auth.role === "operator" && !namedReason(),
  canSubmit: robotId => !auth.locked && auth.role === "operator" && !namedReason() && !view.stateUnavailable
    && !motionCommandReason(view, robotId, "goal")
    && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false),
  confirm: options => confirmedAction.run(options)});
const workView = createWorkView({scope: pageScope, call, el, channelRequestView,
  principal: () => auth.principal,
  approveReason: () => auth.role !== "operator" ? OPERATOR_REASON : namedReason()});
// D-741 8 — 기록 영역은 사건 패널(또는 관제 기록)을 본문으로 올린다. 작업 영역의 작업 목록과 같은 자리다.
const raised = area.get("view") !== "records" ? el(area.get("show") === "new" ? "work-new" : "work-overview") : area.get("show") === "log" ? el("log-panel") : document.querySelector(".incident-panel");
layoutPanels.push(raised);
if (areaNav) raised.dataset.raised = "";
const inbox = createInboxPanel({scope: pageScope, el, readView: () => view});
pageScope.listen(el("focus-robot-choice"), "click", () => {
  inbox.select("status");
  el("robot-choice").scrollIntoView({block: "center"});
  el("robot-choice").focus({preventScroll: true});
});
if (!raised.id.startsWith("work-")) {
  layoutPanels[MAP_PANEL].hidden = true;
  el("incident-side").hidden = false;
  if (inbox.choice !== "inbox") inbox.select("evidence");
}
function layoutConsole() {
  const main = el("fleet-main"), primary = main.querySelector('.console-primary'), secondary = main.querySelector('.console-secondary');
  const focused = document.activeElement;
  const ordered = areaNav ? [raised, document.querySelector('.console-context'),
    ...layoutPanels.filter(node => node !== raised && !node.matches('.console-context'))] : layoutPanels;
  ordered.forEach((node) => {
    const parent = layoutMedia.matches ? (node === layoutPanels[MAP_PANEL] || node === raised ? primary : secondary) : main;
    const before = layoutMedia.matches ? null : primary;
    if (parent.moveBefore) parent.moveBefore(node, before);
    else parent.insertBefore(node, before);
  });
  inbox.select(inbox.choice);
  if (focused?.isConnected && document.activeElement !== focused) focused.focus({preventScroll: true});
}
layoutConsole();
inbox.focusInitial();
pageScope.listen(layoutMedia, "change", layoutConsole);
pageScope.onResume(layoutConsole);

// 셸은 폴링 운율, inbox.js는 로그 상한을 가진다. 지도 격자·오버레이 임계는 map-view.js에 있다.
const STATE_MS = 1000;
// D-457 6: a tracking position shows for at most 1 s minus its age and the request time, so
// polling at 1 s always left a gap and the markers blinked; poll well inside the lifetime.
const TRACKING_MS = 400;
const MAP_MS = 5000;


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
// D-540 9: 움직이는 조작의 잠금 사유. 멈춤(비상 정지·취소·대형 해제·막힘 대기/중단)에는 쓰지 않는다.
const namedReason = () => namedOperatorReason(auth.role, auth.principal);
const confirmedAction = createConfirmedAction({scope: pageScope, identity: () => ({...auth}), confirm: confirmIrreversible});

// D-359 §6.4 — compact·medium에서 접속·역할·테마는 토글 뒤에 접힌다(세로 예산).
// 넓은 창에서는 CSS가 토글을 숨기고 항목을 줄에 세운다. 잠기면 토큰 칸을 연다.
const connectionView = createConnectionView({scope: pageScope, el});

function operatorControls() {
  // 화면 테마(data-theme-choice)와 천장 구석 보기(#watch-ceiling)는 표시 선호라 권한과 무관하다(D-359 §2.5).
  // 머리 토글(#topbar-more)은 접힌 칸을 여는 표시 조작이다(§6.4). 비상 정지는 fleet-header.js 규칙 하나다(D-540 2).
  return document.querySelectorAll(
    "ui-button:not(#estop):not([data-auth-focus]):not([data-select-robot-id]):not([data-work-read]):not(#fleet-inbox):not(#token-save):not(#topbar-more):not([data-login]):not(#vision-refresh):not(#log-clear):not(#birdseye-toggle):not(#watch-ceiling):not(#traffic-toggle):not([data-theme-choice]):not([data-theme-cycle]):not([data-context-tab]), main input, main select:not(#vision-source):not(#robot-choice):not([data-work-read])");
}

const view = {
  map: null,
  pinning: null,   // D-593 위치를 찍을 로봇 id(운영자 핀), 아니면 null
  siteMap: null,   // D-257 천장 카메라 사각형 (GET /api/fleet/site-map)
  sightings: [],   // 카메라 관측 — 표시 전용, CORE pose 와 섞지 않는다
  cameraTracking: { robots: [], unknown: [] }, // D-457 관제 카메라 추적 — 표시·교차확인 전용
  robots: [],
  robotPeers: [], // authenticated peer catalogue; navigation only, never control authority
  robotNames: {}, // enrolled robot_id -> verified discovery hostname; presentation only
  queueChoice: null,  // D-540 3: the queue row the operator opened or closed {key, open}
  selected: null, // 목표 지정을 기다리는 robot_id
  focusRobot: null, // 화면에서 살펴보고 작업을 배정할 로봇; 목표 지정 arm과 별개
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
const log = inbox.log;

const fleetApi = createFleetClient({ credential: () => auth.token });
// D-741 3 — any answer keeps the link word live. Only the state poll may call it down: Fleet answers
// 502/503 for a refusing robot or a feature that is off.
const fleetClient = (path, options) => fleetApi(path, options).then(body => { noteLink(); return body; }, error => {
  if (path === "/api/fleet/state" || error.status < 500) noteLink(error);
  throw error;
});

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
    if ((error.status === 401 || error.code === 'PASSWORD_CHANGE_REQUIRED') && !cameraPreview) markLocked();
    throw error;
  }
}

const incidents = createIncidentView({scope: pageScope, el, view, call, log, auth, onReports: channelRequestView.setIncidents});
const assistant = createAssistantPanel({scope: pageScope, call, el, readSelection: () => view.focusRobot});

// 발행 제어 띠·현장 경로·상태 폴링·전체 주행 취소는 console-refresh.js 팩토리가 가진다(D-798 3.2).
// 목표 해제와 카드 열기는 아래에서 만들어지므로 부를 때 찾는다.
const { cancelAllNotice, refreshDispatchControl, pathSample, paintSitePath, refreshHealthz, refreshState } = createConsoleRefresh({
  pageScope, el, view, auth, call, fleetApi, log, render, confirmedAction, dispatchGate, resetRobotApps,
  disarmGoal: (reason) => disarmGoal(reason), openCard: (robotId) => roster.openCard(robotId) });


// --- 로봇 목록 --------------------------------------------------------------

function render() {
  const rosterBox = el("roster");
  const focused = document.activeElement;
  const focusedCard = focused?.closest?.("#roster article, #robot-workspace article");
  const focusedBox = focusedCard?.closest("#robot-workspace") ? el("robot-workspace") : rosterBox;
  const focusedId = focusedCard?.dataset.robotId;
  const focusedButton = focusedCard && focused !== focusedCard
    ? [...focusedCard.querySelectorAll("ui-button, button")].indexOf(focused) : -1;
  // D-540 3 — every robot has a card; a nominal one is one line (roster.card decides). Exceptions first
  // (D-201); the colour index stays the robot's own.
  if (view.robots.length) {
    const order = [...view.robots.keys()].sort((a, b) =>
      roster.needsAttention(view.robots[b]) - roster.needsAttention(view.robots[a]));
    roster.place(rosterBox, order.map((index) => roster.summary(view.robots[index], index)));
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
  roster.workspace();
  if (focusedId && document.activeElement !== focused) {  // a kept workspace picker still has it
    const nextCard = [...focusedBox.querySelectorAll("article")]
      .find((card) => card.dataset.robotId === focusedId);
    const nextFocused = focusedButton >= 0
      ? nextCard?.querySelectorAll("ui-button, button")[focusedButton] : nextCard;
    nextFocused?.focus({preventScroll: true});
  }
  signals.render();
  roster.fillQueues();
  inbox.refresh();
  roster.trip.syncConvoy();  // D-540 (d) 대형·대열
  if (!el("work-new").hidden) paintMove();
  lineStuck.render();
  deviceWatch.render();
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

const deviceDirectory = createDeviceDiscovery({pageScope, auth, discoveryGate, view, call, render, incidents, el, log});
const refreshDiscovery = () => deviceDirectory.refreshDiscovery();
const refreshRobotApps = () => deviceDirectory.refreshRobotApps();
function resetRobotApps() { deviceDirectory.resetRobotApps(); }

// --- 조작 ------------------------------------------------------------------

// 로스터 키보드·지도 목표 지정·운영자 핀은 console-goal.js 팩토리가 가진다(D-798 3.2).
// 지도 좌표와 큐 사유는 아래의 mapView·roster가 답하므로 부를 때 찾는다.
const { disarmGoal, focusGoalButton, clearPinStart } = createConsoleGoal({ pageScope, el, view, auth, inbox, log, call,
  render, confirmedAction, namedReason,
  toWorld: (grid, col, row) => mapView.toWorld(grid, col, row),
  refreshGuide: () => mapView.refreshGuide?.(),
  queuedReason: (result) => roster.queuedReason(result) });

// 전체 정지는 한 번의 누름으로 즉시 실행된다(D-413 — 비상 정지는 확인 없는 비상 출구.
// D-371이 대화상자 위에서 살아 있게 한 이유를 끝까지 밀었다: 어떤 사위에도 즉시 눌린다).
bindEstop(call, {listen: (node, type, fn) => pageScope.listen(node, type, fn), life: () => pageScope.capture(), log,
  after: () => refreshDispatchControl()});


// D-262: 대형 패널은 formation.js 팩토리가 가진다. 셸은 지도 오버레이와
// 명렬 렌더를 쥐고, 대형 상태는 view.formation 으로 공유한다.
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
  streamEvidence: mapView.streamEvidence, isOperator: () => auth.role === "operator", namedReason, confirmedAction,
  onSelectionChanged: () => { clearPinStart(); } });
if (el("robot-choice")) pageScope.listen(el("robot-choice"), "change", () => {
  roster.openCard(el("robot-choice").value || null);
  render();
});
view.focusRobotWorkspace = (robotId) => roster.openCard(robotId);
view.openFormationWorkspace = () => {
  confirmedAction.cancel(); roster.trip.close(); view.pinning = null; clearPinStart();
  if (view.selected) disarmGoal('대형 관리로 목표 지정 취소');
  render();
  inbox.select('tools');
  const heading = el('formation-heading'); heading.tabIndex = -1;
  heading.focus({preventScroll: false});
};
view.openLeaderTrip = (robotId) => { inbox.select("status"); roster.openCard(robotId); roster.trip.focus(robotId); render(); };
// D-763 6·9 — 새 작업의 이동은 로봇 카드의 운행 폼(card-trip.js) 그 자체다: 같은 계획·시작 요청, 같은 거절.
// 이동이 종류 목록에 서는지는 서버의 종류 목록이 정한다(work-view.js showKinds, D-763 9). 꺼진 단추로 보이지 않는다.
function paintMove() {
  const pick = el("work-move-robot"), box = el("work-move-form"), focused = document.activeElement;
  el("work-move").hidden = el("work-new-move-item").hidden || el("work-new-move").getAttribute("aria-pressed") !== "true";
  const id = placeOptions(pick, view.robots.map(row => ({id: row.robot_id})), pick.value, row => view.robotNames?.[row.id] || row.id);
  const robot = view.stateUnavailable ? null : view.robots.find(row => row.robot_id === id);  // as roster.js
  el("work-move-state").textContent = robot ? cardTripLine(view, id) : "";
  if (el("work-move").hidden || (focused?.tagName === "SELECT" && box.contains(focused))) return;  // as roster.place
  const controls = () => [...box.querySelectorAll("ui-button, select")], at = controls().indexOf(focused);
  if (robot && !roster.trip.section(robot)) roster.trip.focus(id);  // another robot, or reopened after a start
  box.replaceChildren(...(robot ? [roster.trip.section(robot)] : []));
  controls()[at]?.focus({preventScroll: true});
}
pageScope.listen(el("work-new-move"), "click", ({currentTarget: button}) => {
  for (const name of ["aria-pressed", "aria-expanded"]) button.setAttribute(name, String(button.getAttribute(name) !== "true"));
  render();
});
pageScope.listen(el("work-move-robot"), "change", () => render());
// D-407 / D-540 3 — 막힘 판단과 바뀐 경로 확인은 예외 큐 행이 펼친 자리에 산다.
const lineStuck = createLineStuckPanel({ scope: pageScope, view, call, log,
  isOperator: () => auth.role === "operator", namedReason });
const deviceWatch = createDeviceWatch({ scope: pageScope, el, view });
const tripReplan = createTripReplan({ scope: pageScope, view, call, log,
  isOperator: () => auth.role === "operator", namedReason,
  openCard: (robotId) => { roster.openCard(robotId); render(); } });

// D-415 — 진단 패널 갱신: 상태 주기·발견·로봇 오류·카메라
function refreshDiagnostics() {
  const diag = (id, text) => {
    const node = el(id);
    if (node) node.textContent = text;
  };
  diag("diag-state", view.stateUnavailable ? "불가"
    : `${view.robots.length}대 · ${view.stateLoaded ? "갱신됨" : "대기"}`);
  diag("diag-scanner", deviceDirectory.scannerLost ? "끊김"
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

// 잠금·세션 확인·토큰 입력·비밀번호 로그인·개발 접속은 console-auth.js 팩토리가 가진다(D-798 3.2).
const { markLocked, markUnlocked, refreshAuthorization, connectionMode } = createConsoleAuth({ pageScope, el, view, auth, assistant,
  call, fleetClient, render, operatorControls, confirmedAction, connectionView, workView, incidents, visionView,
  trackingView, mapView, formation, dispatchGate, discoveryGate, cancelAllNotice, resetRobotApps, refreshState,
  refreshRobotApps, refreshDispatchControl, refreshDiscovery });

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
pageScope.interval(() => { if (!auth.locked) workView.refresh(); }, MAP_MS);
pageScope.interval(refreshHealthz, STATE_MS);
pageScope.interval(() => signals.presence(), STATE_MS);
pageScope.interval(() => { if (!auth.locked) refreshDispatchControl(); }, STATE_MS);
pageScope.interval(refreshDiscovery, MAP_MS);
pageScope.interval(refreshRobotApps, MAP_MS);
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
