// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createConnectionView } from "./connection-view.js";
import { createFormation } from "./formation.js";
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { createManualControl } from "./manual-control.js";
import { createMovePanel } from "./card-trip.js";
import { createInboxPanel } from "./inbox.js";
import { createAlertPopup, isOnScreen } from "./alert-popup.js";
import { createWorkView } from "./work-view.js";
import { createArmProposalFeed } from "./arm-proposal-view.js";
import { createChannelRequestView } from "./channel-request-view.js";
import { createIncidentView } from "./incident-view.js";
import { createLineStuckPanel } from "./line-stuck.js";
import { createDeviceWatch } from "./device-watch.js";
import { createTripReplan } from "./trip-replan.js";
import { createStationRecovery } from "./station-recovery.js";
import { createPersonRequests } from "./person-request.js";
import { createSignals } from "./signals.js";
import { createChargeBaysView } from "./charge-bays-view.js";
import { createPlatoonView } from "./platoon-view.js";
import { createTrackingView } from "./tracking-view.js";
import { createVisionView } from "/console/assets/vision-view.js";
import { applyRoleToControls, namedOperatorReason, OPERATOR_REASON } from "/console/assets/authorization.js";
// D-410 — 기기 등록·카메라 연결 승인·경기장/맵 보정은 설치 화면(install.js)이 가진다.
import { createDeviceDiscovery } from "/console/assets/device-discovery.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { createFleetClient } from "/common/fleet-client.js";
import { getAnnouncer } from "/common/announcer.js";
import { confirmIrreversible, toggletip } from "/common/ui.js";
import { createConfirmedAction } from "./confirmed-action.js";
import { createPageScope } from "/common/scope.js";
import { createSelection } from "/common/selection.js";
import { createStatePanel } from "/common/workflow-controls.js";
import { area, areaNav } from "/console/assets/area-nav.js";
import { bindEstop, noteLink, setTopbarOpen, tickClock } from "/console/assets/fleet-header.js";
// D-798 3.2 — 접속·잠금, 목표 지정, 읽기 갱신은 각자의 팩토리 파일이 가진다.
import {
  createConsoleAuth,
  createMapSelectionBar,
  navigateConsoleAlert,
  buildRosterSig,
  refreshDiagnostics,
} from "./console-auth.js";
import { createConsoleGoal } from "./console-goal.js";
import { createConsoleRefresh, mapPollPlan, STATE_HOLDOVER_MS } from "./console-refresh.js";
import { createAssistantPanel } from "/console/assets/assistant.js";
import { createRobotDockBinding } from "/console/assets/robot-dock-binding.js";
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
// B1/B2: AI 팔 제안 읽기. 예외 큐와 작업 큐가 같은 답을 쓰고, 라우트 없음(404)은 폴링 문이 닫는다.
const armProposals = createArmProposalFeed({call, gate: createPollGate(),
  onCases: feed => { view.armProposals = feed; render(); }});
const workView = createWorkView({scope: pageScope, call, el, channelRequestView,
  confirm: options => confirmedAction.run(options),
  principal: () => auth.principal,
  approveReason: () => auth.role !== "operator" ? OPERATOR_REASON : namedReason(),
  armProposals});
// D-741 8 — 기록 영역은 사건 패널(또는 관제 기록)을 본문으로 올린다. 작업 영역의 작업 목록과 같은 자리다.
const requestedView = area.get("view");
const workArea = requestedView === "work";
const recordsArea = requestedView === "records";
const robotsArea = requestedView === "robots";
const raised = recordsArea
  ? (area.get("show") === "log" ? el("log-panel") : document.querySelector(".incident-panel"))
  : robotsArea
    ? el("robots-overview")
    : el(area.get("show") === "new" ? "work-new" : "work-overview");
if (raised) layoutPanels.push(raised);
if ((areaNav || robotsArea) && raised) raised.dataset.raised = "";
let roster = null, paintMove = () => {};  // paintMove is set once the work panel exists; render() may run before that
const navigateFromAlert = (target) => navigateConsoleAlert(target, { el, getInbox: () => inbox, getRoster: () => roster, render: () => render() });
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
  return document.querySelectorAll(
    "ui-button:not(#estop):not(#robot-panel-stop):not([data-always-live]):not([data-auth-focus]):not([data-select-robot-id]):not([data-work-read]):not(#map-overlay-toggles ui-button):not(#arm-transfer-recovery-request):not(#fleet-inbox):not(#token-save):not(#topbar-more):not([data-login]):not(#vision-refresh):not(#log-clear):not(#birdseye-toggle):not(#watch-ceiling):not([data-theme-choice]):not([data-theme-cycle]):not([data-context-tab]):not(.robot-panel-close):not(#alert-popup-region ui-button):not(#inbox-popover ui-button), main input:not(#arm-transfer-id):not(#map-display-mode input), main select:not(#vision-source):not([data-work-read])");
}

const view = {
  scope: pageScope,
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
  robotSelection: createSelection(null),
  mapSelection: null, // 지도에서 클릭한 장소({ kind: "place", id, place }) 또는 좌표({ kind: "point", x, y })
  chargeBaysPlan: null,
  candidateSelection: createSelection(null),
  cursor: null, // 지도 좌표계의 col/row, 아래쪽 행이 0
  colors: [],
  formation: null,
  formationUnavailable: false,
  signals: {},    // ROSY-SIGNAL-001 — snapshot 의 signals 캐시
  pendingTasks: {},
  dispatchControl: null,
  stateUnavailable: false,
  stateStale: false,
  stateLoaded: false,
  receivedAtMs: null,  // D-493: 마지막 state 응답을 받은 브라우저 시각
  addresses: {},  // robot_id -> GET /api/fleet/discovery/addresses 행(고정 주소 판정)
  armProposals: null,  // B1/B2: GET /api/fleet/arm-proposals 답({sample, cases}) | null(기능 없음)
  isOperator: () => auth.role === "operator" && !namedReason(),
};
const inbox = createInboxPanel({scope: pageScope, el, readView: () => view,
  getAlerts: () => alertPopup?.getItems() || []});
const alertPopup = createAlertPopup({ mount: el("alert-popup-region"), onNavigate: navigateFromAlert,
  onChange: () => inbox?.refresh(), announcer: getAnnouncer() });
// The map usage note is a one-line toggletip beside the title (touch and keyboard reach it), not standing copy.
toggletip(el("map-help"), "로봇 카드의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다");
const robotsOverview = el("robots-overview");
if (robotsOverview) robotsOverview.hidden = !robotsArea;
layoutPanels[MAP_PANEL].hidden = workArea || recordsArea || robotsArea;
const isMapHidden = () => Boolean(
  layoutPanels[MAP_PANEL]?.hidden
  || workArea
  || recordsArea
  || (robotsArea && !view.selected && !view.pinning),
);
if (recordsArea) {
  el("incident-side").hidden = false;
  if (inbox.choice !== "inbox") inbox.select("evidence");
}
function layoutConsole() {
  const main = el("fleet-main"), primary = main.querySelector('.console-primary'), secondary = main.querySelector('.console-secondary');
  const focused = document.activeElement;
  const ordered = (areaNav || robotsArea) && raised ? [raised, document.querySelector('.console-context'),
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
delete document.documentElement.dataset.areaPending;
inbox.focusInitial();
pageScope.listen(layoutMedia, "change", layoutConsole);
pageScope.onResume(layoutConsole);

// 셸은 폴링 운율, inbox.js는 로그 상한을 가진다. 지도 격자·오버레이 임계는 map-view.js에 있다.
// bad 로그는 #log 기록(live 아님)에 남고, 카드는 호출 실패와 같은 사건이면 alert-popup이 한 장·한 번
// 낭독으로 합친다(D-1117). 로그 창과 카드의 이중 낭독은 #log의 live 역할을 뺀 것으로 끊었다.
const log = (text, kind, popupMeta = null) => {
  inbox.log(text, kind);
  if (kind === "bad") alertPopup.pushLogError(text, popupMeta);
};
alertPopup.attachWindowErrors(pageScope);

const fleetApi = createFleetClient({ credential: () => auth.token });
// D-741 3 — any answer keeps the link word live. Only the state poll may call it down: Fleet answers
// 502/503 for a refusing robot or a feature that is off.
const fleetClient = (path, options) => fleetApi(path, options).then(body => { noteLink(); return body; }, error => {
  if (path === "/api/fleet/state" || error.status < 500) noteLink(error);
  throw error;
});

function isStateWithinHoldover(path) {
  if (!view.stateLoaded || view.stateUnavailable) return false;
  const withinWindow = view.receivedAtMs == null || (Date.now() - view.receivedAtMs) < STATE_HOLDOVER_MS;
  if (path === "/api/fleet/state") return withinWindow;
  return Boolean(view.stateStale && withinWindow);
}

async function call(path, options = {}) {
  const task = pageScope.capture();
  task.check();
  const cameraPreview = path === "/api/fleet/vision/sources" || path === "/api/fleet/vision/lease";
  try {
    const body = await fleetClient(path, {...options, signals: [...(options.signals || []), task.signal]});
    task.check();
    if (auth.locked && path !== "/api/fleet/session" && !cameraPreview) throw new DOMException("Authentication changed", "AbortError");
    if (path === "/api/fleet/session") markUnlocked();
    if (typeof alertPopup !== "undefined") alertPopup.clearCallError(path);
    return body;
  } catch (error) {
    task.check();
    if ((error.status === 401 || error.code === 'PASSWORD_CHANGE_REQUIRED') && !cameraPreview) markLocked();
    if (!(cameraPreview && error.code === "VISION_PREVIEW_DISABLED") && typeof alertPopup !== "undefined") {
      alertPopup.pushCallError(path, options, error, auth.locked, {
        isStaleHoldover: isStateWithinHoldover(path),
      });
    }
    throw error;
  }
}

const incidents = createIncidentView({scope: pageScope, el, view, call, log, auth,
  onReports: (reports) => { view.incidents = reports; channelRequestView.setIncidents?.(reports); }});
const closeTransientPopovers = () => {
  if (el("topbar-extra")?.dataset.open === "true") setTopbarOpen(false);
};
let robotDock = null;
const assistant = createAssistantPanel({
  scope: pageScope,
  call,
  el,
  readSelection: () => view.robotSelection.get(),
  onOpen: () => {
    closeTransientPopovers();
    robotDock?.close();
  },
});

// 발행 제어 띠·현장 경로·상태 폴링·전체 주행 취소는 console-refresh.js 팩토리가 가진다(D-798 3.2).
// 목표 해제와 카드 열기는 아래에서 만들어지므로 부를 때 찾는다.
const { cancelAllNotice, refreshDispatchControl, pathSample, paintSitePath, refreshHealthz, refreshState } = createConsoleRefresh({
  pageScope, el, view, auth, call, fleetApi, log, render, confirmedAction, dispatchGate, resetRobotApps,
  disarmGoal: (reason) => disarmGoal(reason),
  openCard: (robotId) => roster.openCard(robotId),
  onStateRecovered: () => { void mapView?.refresh?.(); void mapView?.refreshGuide?.(); },
});

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  queueMicrotask(() => {
    renderQueued = false;
    render();
  });
}
let lastRoleApplyKey = "";
let lastRosterSig = "";
let renderMapSelectionBar = null;

// --- 로봇 목록 --------------------------------------------------------------

// F1 — 큐 패널은 hidden이 아니어도 뷰포트 밖(스크롤·앱바 가림)이면 보이는 알림 표면이 아니다.
// 창 클립에서 고정 앱바 높이만큼 깎고, 스크롤 조상(overflow auto/scroll)의 클립과도 겹쳐야 한다.
// 판정을 모르면 알리는 쪽(토스트)으로 기운다 — 긴급 알림이 조용히 사라지지 않게.
function queuesPanelOnScreen(panel) {
  if (!panel || panel.hidden) return false;
  const appbarBottom = document.querySelector("header.fleet-header")?.getBoundingClientRect().bottom || 0;
  const clips = [{ top: appbarBottom, bottom: window.innerHeight, left: 0, right: window.innerWidth }];
  for (let node = panel.parentElement; node && node !== document.body; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflow;
    if (overflow.includes("auto") || overflow.includes("scroll")) clips.push(node.getBoundingClientRect());
  }
  return isOnScreen(panel.getBoundingClientRect(), clips);
}

function render() {
  // 지도 캔버스는 무장(목표 선택·위치 찍기)했을 때만 누를 수 있는 단추다 — role이 무장 상태를 따라간다.
  // 해제하면 뷰가 소유한 role로 돌린다(사이트 뷰는 img). 계층이 부여한 값을 덮어쓰지 않는다(WCAG 4.1.2).
  const picking = Boolean(view.selected || view.pinning);
  if (robotsArea) {
    if (robotsOverview) robotsOverview.hidden = picking;
    layoutPanels[MAP_PANEL].hidden = !picking;
  }
  const stageEl = el("fleet-robot-stage");
  if (stageEl) stageEl.dataset.mapPicking = String(picking);
  const goalCanvas = el("map-canvas");
  if (picking) goalCanvas.setAttribute("role", "button");
  else if (goalCanvas.getAttribute("role") === "button") {
    if (!view.map && view.siteMap) goalCanvas.setAttribute("role", "img");
    else goalCanvas.removeAttribute("role");
  }
  if (workArea) {
    const rosterBox = el("roster");
    const focused = document.activeElement;
    const focusedCard = focused?.closest?.("#roster .robot-row, #robot-panel-mount article");
    const focusedBox = focusedCard?.closest("#robot-panel-mount") ? el("robot-panel-mount") : rosterBox;
    const focusedId = focusedCard?.dataset.robotId;
    const focusedButton = focusedCard && focused !== focusedCard
      ? [...focusedCard.querySelectorAll("ui-button, button")].indexOf(focused) : -1;
    // 연락이 끊긴 로봇도 이유와 함께 보여야 운영자가 상태를 구분할 수 있다.
    const visibleIndices = [...view.robots.keys()];
    if (visibleIndices.length) {
      const rosterSig = buildRosterSig(view, auth, view.robotSelection?.get?.());
      const hasRows = Boolean(rosterBox.firstElementChild?.classList?.contains("robot-rows"));
      if (rosterSig !== lastRosterSig || !hasRows) {
        lastRosterSig = rosterSig;
        const order = visibleIndices.sort((a, b) =>
          roster.needsAttention(view.robots[b]) - roster.needsAttention(view.robots[a]));
        const list = document.createElement("ul");
        list.className = "robot-rows";
        list.append(...order.map((index) => roster.summary(view.robots[index], index)));
        roster.place(rosterBox, [list]);
      }
    } else {
      lastRosterSig = "";
      const state = auth.locked ? { state: "forbidden", title: "접속이 필요합니다", detail: "관제에 접속하면 등록 로봇과 연결 상태를 확인할 수 있습니다." }
        : view.stateUnavailable ? { state: "unavailable", title: "Fleet 상태를 확인할 수 없습니다", detail: "연결을 확인하세요." }
        : view.stateLoaded ? { state: "empty", title: "등록된 로봇이 없습니다", detail: "발견 목록에서 페어링 상태를 확인하세요." }
          : { state: "pending", title: "로봇 목록 불러오는 중", detail: "" };
      rosterStatePanel.set(state);
      if (rosterBox.firstElementChild !== rosterStatePanel.element || rosterBox.childElementCount !== 1) {
        rosterBox.replaceChildren(rosterStatePanel.element);
      }
    }
    if (focusedId && document.activeElement !== focused) {  // a kept workspace picker still has it
      const nextCard = [...focusedBox.querySelectorAll(".robot-row, article")]
        .find((card) => card.dataset.robotId === focusedId);
      const nextFocused = focusedButton >= 0
        ? nextCard?.querySelectorAll("ui-button, button")[focusedButton] : nextCard;
      nextFocused?.focus({preventScroll: true});
    }
  }
  manualControl.update();
  robotDock?.sync();
  signals.render();
  roster.fillQueues();
  const queuesPanel = document.querySelector(".queues-panel");
  alertPopup.syncCritRows(
    el("critical-list"),
    Boolean(view.stateLoaded && !view.stateUnavailable),
    { panelVisible: queuesPanelOnScreen(queuesPanel) },
  );
  inbox.refresh();
  roster.syncConvoy();  // D-540 (d) 대형·대열
  if (!el("work-new").hidden) paintMove();
  lineStuck.render();
  deviceWatch.render();
  tripReplan.render();
  stationRecovery.render();
  personRequests.render();

  formation.fillLeaders();
  // Map labels always show for 최우선 robots (warn causes are often fleet-wide); the rest declutter.
  view.attention = new Set(view.robots.filter((r) => roster.attentionItems(r).some((i) => i.severity === "crit")).map((r) => r.robot_id));
  if (!layoutPanels[MAP_PANEL]?.hidden) mapView.draw();
  renderMapSelectionBar?.();
  const roleApplyKey = [
    auth.role || "", auth.locked ? 1 : 0, view.robots.length,
    view.robots.map((r) => r.robot_id).join(","),
    view.robotSelection?.get?.() || "", view.mapSelection?.kind || "", view.selected || "",
  ].join("|");
  if (roleApplyKey !== lastRoleApplyKey) {
    lastRoleApplyKey = roleApplyKey;
    applyRoleToControls(auth.role, operatorControls());
  }
  const hint = el("hint");
  if (hint) {
    hint.hidden = !picking;
    const point = view.selected && view.cursor && view.map
      ? mapView.toWorld(view.map, view.cursor.col, view.cursor.row) : null;
    const nextHint = point
      ? `${view.selected} 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m · 방향키로 이동, Enter로 확인, Escape로 취소`
      : view.pinning
        ? `${view.pinning} 위치 찍기 — 지도에서 위치를 클릭하거나 드래그하여 방향을 정하세요 (Escape로 취소)`
        : view.selected
          ? `${view.selected} 목표 지정 — 지도에서 목표 위치를 클릭하세요 (Escape로 취소)`
          : view.map || view.siteMap
            ? "로봇을 선택하고 지도를 찍으면 확인 후 목표를 보냅니다."
            : "지도가 수신되면 로봇의 목표 지정을 사용할 수 있습니다.";
    if (hint.textContent !== nextHint) hint.textContent = nextHint;
  }
  if (el("console-diagnostics")?.open) refreshDiagnostics(el, view, deviceDirectory);
}

const deviceDirectory = createDeviceDiscovery({pageScope, auth, discoveryGate, view, call, render, incidents, el, log});
const refreshDiscovery = () => deviceDirectory.refreshDiscovery();
const refreshRobotApps = () => deviceDirectory.refreshRobotApps();
function resetRobotApps() { deviceDirectory.resetRobotApps(); }

// --- 조작 ------------------------------------------------------------------

// 로스터 키보드·지도 목표 지정·운영자 핀은 console-goal.js 팩토리가 가진다(D-798 3.2).
// 지도 좌표와 큐 사유는 아래의 mapView·roster가 답하므로 부를 때 찾는다.
const goalControl = createConsoleGoal({ pageScope, el, view, auth, inbox, log, call,
  render, confirmedAction, namedReason,
  toWorld: (grid, col, row) => mapView.toWorld(grid, col, row),
  refreshGuide: () => mapView.refreshGuide?.(),
  queuedReason: (result) => roster.queuedReason(result),
  drawMap: () => mapView.draw(),
  onSelectRobot: (robotId) => { view.mapSelection = null; roster.openCard(robotId); },
});
const { disarmGoal, focusGoalButton, commitWorldGoal, clearPinStart } = goalControl;
view.dispatchGoalToPoint = (point, placeLabel = "", placeId = "", overrideRobotId = null) =>
  commitWorldGoal(point, placeLabel, placeId, overrideRobotId);

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
  onMapChanged: scheduleRender,
  onTrafficChanged: scheduleRender,
  onSelectRobotFromMap: (robotId) => { view.mapSelection = null; roster.openCard(robotId); },
  onSelectPlaceFromMap: (place) => { view.mapSelection = { kind: "place", id: String(place.id), place }; render(); },
  onSelectPoint: (point) => goalControl.handlePointSelect(point, { toggleSelection: false }),
  onHoverEntity: (entity, clientX, clientY) => goalControl.handleHoverEntity(entity, clientX, clientY),
  onMapUnavailable: () => {
    const selected = view.selected;
    if (selected) disarmGoal("지도를 확인할 수 없어 목표 지정 취소");
    scheduleRender();
    if (selected) focusGoalButton(selected);
  },
});

// Fleet 분해 3: 명렬 카드와 큐는 roster.js 팩토리가 그린다.
// D-410 — 주소 이동 조작은 설치 화면이 소유해서 moveAddress 훅을 주지 않는다.
roster = createRoster({ scope: pageScope, el, view, log, call, render,
  streamEvidence: mapView.streamEvidence, isOperator: () => auth.role === "operator", namedReason, confirmedAction,
  onSelectionChanged: () => { clearPinStart(); } });
const manualControl = createManualControl({scope: pageScope, view, call: fleetClient,
  confirmedAction, refreshState,
  onStatusChange: () => { if (!el("map-selection-bar")?.hidden) renderMapSelectionBar(); },
  namedReason: () => auth.locked ? "관제에 다시 접속하세요." : auth.role !== "operator" ? OPERATOR_REASON : namedReason()});
robotDock = createRobotDockBinding({
  scope: pageScope,
  el,
  view,
  call,
  roster,
  manualControl,
  assistant,
  onOpen: closeTransientPopovers,
  isOperator: () => auth.role === "operator",
  namedReason,
  refresh: () => chargeBays?.refresh(),
  render,
});
pageScope.onDispose(view.robotSelection.subscribe((id, meta) => {
  if (meta?.source === "selectRobot") return;
  confirmedAction?.cancel();
  if (meta?.source === "panel-close" || !id) {
    view.focusAnchorId = null;
  } else {
    view.selected = null;
    view.pinning = null;
    view.cursor = null;
    view.focusAnchorId = id;
    roster.closeTrip?.();
    clearPinStart();
    if (typeof id === "string" && !id.startsWith("arm_")) {
      const stage = el("map-stage");
      if (view.displayMode === "camera" || stage?.dataset?.view === "camera") {
        if (typeof view.setDisplayMode === "function") view.setDisplayMode("coordinates");
        else if (stage) stage.dataset.view = "map";
        el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
      }
      const canvas = el("map-canvas");
      if (canvas) { canvas.classList.toggle("idle", true); canvas.tabIndex = -1; }
    }
  }
  if (meta?.source !== "render" && meta?.source !== "refresh") render();
}));

renderMapSelectionBar = createMapSelectionBar({
  pageScope, el, view, auth, namedReason,
  getRoster: () => roster, manualControl, disarmGoal, clearPinStart, commitWorldGoal, render,
});
view.focusRobotWorkspace = (robotId) => roster.openCard(robotId);
view.openFormationWorkspace = () => {
  confirmedAction.cancel(); roster.closeTrip(); view.pinning = null; clearPinStart();
  if (view.selected) disarmGoal('대형 관리로 목표 지정 취소');
  render();
  inbox.select('tools');
  const heading = el('formation-heading'); heading.tabIndex = -1;
  heading.focus({preventScroll: false});
};
view.openLeaderTrip = (robotId) => { inbox.select("status"); roster.openTrip(robotId); render(); };
paintMove = createMovePanel({ scope: pageScope, el, view, getRoster: () => roster, render });
// D-407 / D-540 3 — 막힘 판단과 바뀐 경로 확인은 예외 큐 행이 펼친 자리에 산다.
const operatorDeps = { scope: pageScope, view, call, log, isOperator: () => auth.role === "operator", namedReason };
const lineStuck = createLineStuckPanel(operatorDeps);
const deviceWatch = createDeviceWatch({ scope: pageScope, el, view });
const stationRecovery = createStationRecovery(operatorDeps);
const personRequests = createPersonRequests(operatorDeps);
const tripReplan = createTripReplan({ ...operatorDeps, openCard: (robotId) => { roster.openCard(robotId); render(); } });

// D-262: 신호등 카드는 signals.js 팩토리가 그린다.
const signals = createSignals({ scope: pageScope, el, view, log, call, refreshState,
  isOperator: () => auth.role === "operator" && !auth.locked, namedReason });
// D-410 — 운용 화면의 카메라는 영상 프리뷰만 띄운다. 경기장/맵 보정 뷰는 설치 화면이 가진다.
const visionView = createVisionView({
  scope: pageScope, el, call, rawOnly: true,
  isActive: () => inbox.choice === "tools" || el("map-stage")?.dataset.view === "camera"
    || view.displayMode === "overlay" || view.displayMode === "twin3d",
  onSources: (sample) => { pathSample.vision = sample; paintSitePath(); },
});
mapView.bindCamera(visionView);

// --- 신호등 (ROSY-SIGNAL-001) --------------------------------------------------

const rosterStatePanel = createStatePanel({ id: "roster-state", retryLabel: "다시 조회", onRetry: () => refreshState() });
const chargeBays = createChargeBaysView({
  scope: pageScope, el, call, auth, confirmedAction,
  robotSelection: view.robotSelection,
  onPlan: (plan) => { view.chargeBaysPlan = plan; robotDock?.sync(); },
});
const platoon = createPlatoonView({ scope: pageScope, el, call, auth });
const trackingView = createTrackingView({ scope: pageScope, el, view, call, auth, onChanged: () => mapView.draw() });

// 잠금·세션 확인·토큰 입력·비밀번호 로그인·개발 접속은 console-auth.js 팩토리가 가진다(D-798 3.2).
const { markLocked, markUnlocked, refreshAuthorization, connectionMode } = createConsoleAuth({ pageScope, el, view, auth, assistant,
  call, fleetClient, render, operatorControls, confirmedAction, connectionView, workView, incidents, visionView,
  trackingView, mapView, formation, dispatchGate, discoveryGate, cancelAllNotice, resetRobotApps, refreshState,
  refreshRobotApps, refreshDispatchControl, refreshDiscovery });

const robotColours = () => ["--robot-1", "--robot-2", "--robot-3"].map((name) => window.RosyPalette.cssColor(name));
view.colors = robotColours();
pageScope.listen(document, "rosy:theme", () => { view.colors = robotColours(); mapView.draw(); });
if (el("console-diagnostics")) {
  pageScope.listen(el("console-diagnostics"), "toggle", () => {
    if (el("console-diagnostics")?.open) refreshDiagnostics(el, view, deviceDirectory);
  });
}
tickClock();
pageScope.interval(tickClock, 1000);
applyRoleToControls(null, operatorControls());
render();
paintSitePath();
connectionMode();
refreshAuthorization();
armProposals.refresh();
visionView.refreshSources();
mapView.refreshGuide();
if (!isMapHidden()) { trackingView.refresh(); platoon.refresh(); }
chargeBays.refresh();
stationRecovery.refresh();
personRequests.refresh();
pageScope.interval(() => {
  if (document.hidden) return;
  refreshState(); refreshHealthz(); signals.presence();
  const plan = mapPollPlan(isMapHidden());
  if (plan.sightings) mapView.refreshSightings();
  if (plan.traffic) mapView.refreshTraffic();
  if (plan.guide) mapView.refreshGuide();
  if (!auth.locked) { refreshDispatchControl(); stationRecovery.refresh(); personRequests.refresh(); }
}, STATE_MS);
pageScope.interval(() => {
  if (document.hidden) return;
  refreshDiscovery(); refreshRobotApps();
  const plan = mapPollPlan(isMapHidden());
  if (plan.siteMap) mapView.refresh();
  if (plan.platoon) platoon.refresh();
  chargeBays.refresh();
  if (!auth.locked) { formation.refreshFormation(); workView.refresh(); armProposals.refresh(); }
}, MAP_MS);
pageScope.interval(() => { if (!document.hidden && !isMapHidden()) trackingView.refresh(); }, TRACKING_MS);
pageScope.interval(() => { if (!document.hidden && !isMapHidden()) visionView.refreshFrame(); }, 1500);

pageScope.onResume(() => {
  visionView.reset(); trackingView.reset(); trackingView.refresh();
  refreshAuthorization(); visionView.refreshSources();
});
