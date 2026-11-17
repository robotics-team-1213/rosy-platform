import {node, action, input, select} from "./control-dom.js";
import {createFormErrors, createFilePicker, createSearchSelect, createDateRange, createDirtyGuard} from "./form-controls.js";
import {createListToolbar, createDataTable, createPagination, createSelectionBar, createPrimaryDetail} from "./collection-controls.js";
import {createTabs, createDisclosure, createActionMenu, createSupplementPanel} from "./interaction-controls.js";
import {createStatePanel, createActionBar, createOperationResult, createProgress, createTimeline, createSteps, createLogView} from "./workflow-controls.js";
import {confirmIrreversible, actionIcon, actionIconNames, toggletip} from "./ui.js";
import {setGeometry} from "./geometry.js";
import {createStopControl} from "./stop-control.js";
import {gateState} from "./account-gate.js";
import {createConnectionNotice} from "./connection-notice.js";
import {createAlertCenter} from "./alert-center.js";
import {getAnnouncer} from "./announcer.js";
import {createBusyScope} from "./busy-scope.js";
import {createCauseLine} from "./cause-line.js";
import {renderValue} from "./value-text.js";
import {statusTag} from "./status-tag.js";
import {robotProfile} from "./robot-profile.js";
import {createRobotRoster} from "./robot-row.js";
import {createChoiceList} from "./choice-list.js";
import {createChoiceGroup} from "./choice-group.js";
import {createSelection} from "./selection.js";
import {robotOptions} from "./robot-options.js";
import {localizationState} from "./localization-state.js";
import {skillState} from "./skill-state.js";
import {createEvidenceLine} from "./evidence-line.js";
import {mountRobotDockDemo} from "./robot-dock-gallery.js";
import {sampleTag, armAiCaseProblems} from "./sample-data.js";

const CONNECTION_STATE_NAME = {operate: "운용 가능", "signed-in": "로그인 · 조회만", view: "로그인 안 됨 · 조회만", unavailable: "계정 확인 불가 · 권한 없음 아님"};

const el = id => document.getElementById(id);
const mounted = [];
function mount(id, component) {el(id).append(component.element || component); if (component.dispose) mounted.push(component); return component;}

const errors = createFormErrors(el("form-example"), el("example-errors"));
document.querySelector('[role="switch"]').addEventListener("change", event => {el("name-help").hidden = !event.target.checked;});
el("form-example").addEventListener("submit", event => {
  event.preventDefault();
  if (!errors.show(el("example-name").value.trim() ? {} : {"example-name": "이름을 입력하세요"})) return;
  const failed = el("example-fail-save").checked;
  el("example-result").setAttribute("state", failed ? "error" : "ready");
  el("example-result").textContent = failed ? "저장하지 못했습니다 · 입력을 유지했습니다" : "견본 저장값을 다시 조회해 확인했습니다";
});
const file = mount("file-mount", createFilePicker({id: "file-example", label: "레시피 JSON 파일"}));
file.result.id = "file-result";
const choiceResult = node("ui-status"); choiceResult.id = "choice-result"; choiceResult.setAttribute("state", "empty");
mount("choice-mount", createSearchSelect({id: "choice", label: "카메라 선택", choices: Array.from({length: 100}, (_, i) =>
  ({value: `camera-${i + 1}`, label: `카메라 ${i + 1}`})), onChange: value => {choiceResult.textContent = value;}}));
el("choice-mount").append(choiceResult);
const range = mount("period-mount", createDateRange({id: "period", label: "조회 기간"})); range.result.id = "period-result";

const devices = Array.from({length: 24}, (_, i) => ({id: `device-${i + 1}`, label: `장비 ${i + 1}`, state: i % 3 ? "ready" : "held"}));
let query = "", filter = "", sort = "ascending", page = 1;
const pageSize = 8;
let visible = [];
const table = createDataTable({id: "device-list", columns: [{label: "장비 이름", text: item => item.label},
  {label: "상태", text: item => item.state === "held" ? "보류" : "준비"}],
  onOpen: (item, opener) => detail.open({title: item.label, body: node("p", `${item.label} · 합성 장비 상세 · 실제 장치 아님`)}, opener),
  onActiveRemoved: () => detail.unavailable(),
  onSelection: selection => {selectionBar.set(selection.size, {scope: "불러온 전체 목록"}); paintSelection(selection);}});
const toolbar = createListToolbar({id: "list", filters: [{value: "ready", label: "준비"}, {value: "held", label: "보류"}],
  onChange: next => {({query, filter, sort} = next); page = 1; paintList();}});
const pager = createPagination({id: "list", onChange: next => {page = next; paintList();}});
const bulkResult = node("ui-status"); bulkResult.id = "bulk-result"; bulkResult.setAttribute("state", "empty");
const selectionBar = createSelectionBar({id: "list-selection", onClear: () => table.clearSelection(), actions: [
  {label: "선택 자료 보류 견본", onClick: () => {
    const selected = [...table.selection];
    const failed = selected.slice(0, 1);
    for (const item of devices) if (selected.includes(item.id) && !failed.includes(item.id)) item.state = "held";
    bulkResult.setAttribute("state", "warning");
    bulkResult.textContent = `${selected.length - failed.length}개 적용 · ${failed.length}개 실패 · 합성 변경 · 선택 유지`;
    paintList();
  }},
]});
const pageCheck = input("select-page", "현재 페이지 항목 선택", "checkbox");
pageCheck.control.addEventListener("change", () => table.selectPage(pageCheck.control.checked));
function paintSelection(selection) {
  const count = visible.filter(item => selection.has(item.id)).length;
  pageCheck.control.checked = Boolean(visible.length) && count === visible.length;
  pageCheck.control.indeterminate = count > 0 && count < visible.length;
}
function paintList() {
  const matching = devices.filter(item => item.label.includes(query.trim()) && (!filter || item.state === filter))
    .sort((a, b) => sort === "descending" ? b.label.localeCompare(a.label, "ko", {numeric: true}) : a.label.localeCompare(b.label, "ko", {numeric: true}));
  page = Math.min(page, Math.max(1, Math.ceil(matching.length / pageSize)));
  visible = matching.slice((page - 1) * pageSize, page * pageSize);
  toolbar.count.textContent = `${matching.length}개`;
  table.set(visible, {allIds: devices.map(item => item.id), label: "합성 장비 목록"});
  pager.set({page, totalPages: Math.max(1, Math.ceil(matching.length / pageSize))});
  paintSelection(table.selection);
}
const list = node("div", "", "ui-control-stack"); list.append(toolbar.element, pageCheck.element, selectionBar.element, bulkResult, table.element, pager.element);
const detail = createPrimaryDetail({id: "devices", label: "장비 상세", list}); detail.detail.id = "device-detail";
mount("collection-mount", detail); mounted.push(toolbar);
selectionBar.set(0); paintList();
let shown = 3;
const cursorItems = node("ul");
const appendItems = start => {for (let at = start; at < shown; at++) cursorItems.append(node("li", `합성 사건 ${at + 1}`));};
appendItems(0); el("cursor-count").after(cursorItems);
el("more-items").addEventListener("click", () => {
  const previous = shown; shown += 3; appendItems(previous);
  el("cursor-count").textContent = `${shown}개 표시 · 전체 개수 미확인`;
});

const state = createStatePanel({id: "state-example", retryLabel: "자료 다시 조회", onRetry: () => state.set({state: "ready"})});
const stateChoice = select("state-choice", "표시할 상태", ["pending", "empty", "forbidden", "error", "unavailable", "ready"].map(value =>
  ({value, label: {pending: "로딩", empty: "자료 없음", forbidden: "권한 거절", error: "조회 실패", unavailable: "연결 불가", ready: "조회 완료"}[value]})));
stateChoice.control.addEventListener("change", () => state.set({state: stateChoice.control.value}));
el("state-mount").append(stateChoice.element, state.element); state.set({state: "pending"});
const operation = mount("operation-mount", createOperationResult({id: "operation-result"})); operation.set({state: "unknown"});
const start = action("요청 접수 견본", () => operation.set({state: "accepted"})); start.id = "operation-start";
const readback = action("실제 결과 확인 견본", () => operation.set({state: "confirmed"})); readback.id = "operation-readback";
el("operation-mount").append(start, readback);
const actions = createActionBar([
  {label: "대기", onClick: () => operation.set({state: "accepted", detail: "대기 의도 견본 · 실제 명령 아님"})},
  {label: "경로를 다시 계획해 확인", onClick: () => operation.set({state: "unknown", detail: "재계획 의도 견본 · 실제 명령 아님"})},
  {label: "후진 후 재시도 확인", reason: "뒤쪽 공간을 먼저 확인하세요"},
]); actions.id = "action-example"; mount("actions-mount", actions);

mount("tabs-mount", createTabs({id: "context", tabs: [{label: "상태 견본", panelId: "tab-state", content: node("p", "현재 상태와 근거")},
  {label: "근거 견본", panelId: "tab-evidence", content: node("p", "관측 근거 · 출처·시각 미확인")}]}));
mount("tabs-mount", createDisclosure({label: "상세 진단 보기", content: node("p", "진단은 필요한 경우에만 엽니다.")}));
function focusExample(id) {
  const target = el(id); target.tabIndex = -1;
  target.scrollIntoView({block: "start"}); target.focus({preventScroll: true});
}
for (const name of actionIconNames()) {
  const row = node("li"); row.dataset.icon = name;
  for (const px of [16, 20, 24]) { const cell = node("span"); cell.dataset.px = px; row.append(actionIcon(cell, name)); }
  row.append(node("code", name)); el("icon-sheet").append(row);
}
const infoButton = node("ui-button"); infoButton.setAttribute("kind", "quiet"); infoButton.setAttribute("type", "button");
infoButton.setAttribute("aria-label", "근거 보기"); infoButton.setAttribute("data-icon-only", "");
infoButton.id = "toggletip-button"; el("toggletip-mount").append(infoButton); actionIcon(infoButton, "info");
toggletip(infoButton, "관측 14:02 · Fleet 직접 조회 · 30초 전");
mount("menu-mount", createActionMenu({id: "menu-open", label: "보조 동작", actions: [
  {label: "목록 견본으로 이동", onClick: () => focusExample("collections")},
  {label: "기록 견본으로 이동", onClick: () => focusExample("procedure")},
]}));
const panel = mount("panel-mount", createSupplementPanel({id: "supplement", title: "보조 근거", content: node("p", "선택한 대상의 보조 설명입니다. 정지·주요 조작을 숨기지 않습니다.")}));
const panelButton = action("보조 상세 열기", () => panel.open(panelButton)); panelButton.id = "panel-open";
el("panel-mount").prepend(panelButton);
const dirty = createDirtyGuard(el("draft-form")); mounted.push(dirty);
el("draft-leave").addEventListener("click", async () => {el("draft-result").textContent = await dirty.canLeave() ? "이동 확인" : "편집 유지";});
el("danger-example").addEventListener("click", () => confirmIrreversible({message: '"합성 작업"을 취소할까요? 실제 장치는 움직이지 않습니다.', action: "작업 취소"}));
const sampleStop = createStopControl({button: el("gallery-stop"), status: el("stop-result"),
  accept: async response => response.ok && (await response.json()).estop === true,  // stricter than ok: the body must say so (async)
  send: async () => { if (el("stop-slow").checked) await new Promise(done => setTimeout(done, 600)); return new Response(JSON.stringify({estop: !el("stop-no-estop").checked}), {status: el("stop-refuse").checked ? 403 : 200}); }});
el("stop-note").addEventListener("click", () => sampleStop.note("합성 안내: 로그아웃 처리가 지연 중입니다.", "error"));  // 합성 요청 · 실제 로봇 정지 아님
const gateSamples = [["operate", {authenticated: true, can_operate: true}], ["signed-in", {authenticated: true, can_operate: false}],
  ["view", {authenticated: false}], ["unavailable", null]];
for (const [state, sample] of gateSamples) el("gate-" + state).textContent = gateState(sample) === state ? CONNECTION_STATE_NAME[state] : "계약 위반";
for (const state of ["fresh", "delayed", "auth-wait", "unavailable", "disconnected"]) createConnectionNotice(el("notice-" + state)).set(state);
createConnectionNotice(el("notice-disconnected-danger")).set("disconnected", "연결 끊김 · 주행 중", {danger: true});  // the caller knows the operating risk

const steps = mount("steps-mount", createSteps({id: "steps-example", labels: ["파일 선택", "검증", "미리보기", "결과 확인"]}));
let step = 0; steps.set(step);
const nextStep = action("다음 단계 견본", () => steps.set(step = (step + 1) % 4)); nextStep.id = "step-next"; el("steps-mount").append(nextStep);
const progress = mount("progress-mount", createProgress({id: "progress-example", label: "자료 전송 견본"})); progress.set(null);
const known = action("40% 진행 견본", () => progress.set(40)); known.id = "progress-known"; el("progress-mount").append(known);
const timeline = mount("timeline-mount", createTimeline({id: "timeline-example", label: "작업 이력 견본"}));
timeline.set([{label: "접수", at: "2026-10-23T09:00:00+09:00"}, {label: "완료 미확인", detail: "현재 상태를 다시 조회해야 합니다"}]);
mount("log-mount", createLogView({label: "공개 진단 견본", text: "task=sample-1\nstate=accepted\nresult=unknown\n실제 계정·토큰·장치 주소를 기록하지 않습니다."}));
// C2 busy scope: the action waits for "작업 끝내기"; the background refresh waits for its own button and never locks.
let finishBusy, finishRefresh;
const scope = createBusyScope(el("busy-region"), {status: el("busy-status")});
el("busy-save").addEventListener("click", () => scope.run(() => new Promise(resolve => {finishBusy = resolve;}), {label: "저장 결과를 확인하고 있습니다."}).then(() => {el("busy-status").textContent = "저장 견본 완료";}));
el("busy-finish").addEventListener("click", () => finishBusy?.());
el("refresh-start").addEventListener("click", () => scope.refresh(() => new Promise(resolve => {finishRefresh = resolve;}),
  () => {el("refresh-status").textContent = "배경 조회 결과 적용";}, () => {el("refresh-status").textContent = "배경 조회 실패";}));
el("refresh-finish").addEventListener("click", () => finishRefresh?.());
// C1 cause line: one line for the group, kept in step with every `disabled` change.
const cause = createCauseLine(el("cause-group"));
el("cause-lock").addEventListener("click", () => {cause.set([el("cause-a"), el("cause-b")], "합성 견본: 아직 권한을 확인하지 못했습니다"); countCause();});
el("cause-open-b").addEventListener("click", () => {el("cause-b").disabled = false; cause.sync();});
el("cause-clear").addEventListener("click", () => cause.set([el("cause-a"), el("cause-b")], ""));
// a rebuilt control replaces the old one; the line must not keep tracking the one that left the document
function countCause() {el("cause-count").textContent = `추적 ${cause.size}개`;}
el("cause-rebuild").addEventListener("click", () => {
  const fresh = el("cause-b").cloneNode(true); el("cause-b").replaceWith(fresh); fresh.id = "cause-b";
  cause.set([fresh], "합성 견본: 아직 권한을 확인하지 못했습니다"); cause.sync(); countCause();
});
countCause();
// C1+C2 together: a cause set during a run is applied when the run ends, and nothing opens early.
let finishBc;
const bcCause = createCauseLine(el("bc-region")), bcScope = createBusyScope(el("bc-region"), {cause: bcCause});
el("bc-run").addEventListener("click", () => bcScope.run(async () => {
  bcCause.set([el("bc-a")], "합성 사유: 처리가 끝나도 A는 닫혀 있습니다");
  bcCause.set([el("bc-b"), el("bc-input")], "");
  await new Promise(resolve => {finishBc = resolve;});
}));
el("bc-finish").addEventListener("click", () => finishBc?.());
// C4 unknown values
renderValue(el("value-missing"), undefined, {unit: "%"}); renderValue(el("value-zero"), 0, {unit: "%"});
renderValue(el("value-stale"), 42, {unit: "%", age: 12}); renderValue(el("value-down"), 42, {evidence: "disconnected"});
for (const value of document.querySelectorAll('[data-layout-token]')) {
  value.textContent = getComputedStyle(document.documentElement).getPropertyValue(value.dataset.layoutToken).trim();
}
for (const [label, value] of [["25%", "25%"], ["80%", "80%"], ["값 오류(NaN)", Number.NaN]]) {
  el("geometry-buttons").append(action(`폭 ${label}`, () => {
    const ok = setGeometry(el("geometry-fill"), {width: value});
    el("geometry-result").textContent = ok ? `폭 ${label}` : "값이 틀려 기본 폭으로 돌아감";
  }));
}
// C11/C12: status tags and panel icons are built by the shared recipes; the HTML holds only the layout.
for (const host of document.querySelectorAll("[data-status-tag]")) host.replaceWith(statusTag(host.dataset.statusTag, host.dataset.text, {icon: host.dataset.icon}));
for (const head of document.querySelectorAll("[data-panel-icon]")) {const holder = document.createElement("span"); actionIcon(holder, head.dataset.panelIcon); head.prepend(holder.firstElementChild);}
// C14: arms and mobile robots in one row form (synthetic samples: normal, torque off, stale, lost, unknown, alarms).
const robotSamples = [
  {id: "arm_a", name: "OMX-AI A", kind: "arm", online: true, ageS: 1, torque: true, servo: {currentMa: 120, temperatureC: 31}, task: "화물 집기", place: "S2 셀 A", detail: "관절 6축 정상 · 서보 12.0 V"},
  {id: "arm_b", name: "OMX-AI B", kind: "arm", online: true, ageS: 2, torque: false, servo: {currentMa: 0, temperatureC: 29}, task: "대기", place: "S5 셀 B"},
  {id: "arm_s", name: "OMX-AI S", kind: "arm", online: true, ageS: 14, torque: true, servo: {currentMa: 210, temperatureC: 38}, task: "하역 셔틀 적재", place: "S3 셀 S"},
  {id: "rosy_40", kind: "mobile", online: true, ageS: 1, battery: {percent: 82, charging: false}, estop: false, task: "C1 대기", place: "C1 충전소"},
  {id: "rosy_41", name: "Pinky 41", kind: "mobile", online: true, ageS: 1, battery: {percent: 14, charging: false}, estop: false, task: "S1로 이동", pose: {x: 0.5, y: -0.25}, detail: "배터리 8.1 V · 충전소 복귀 필요"},
  {id: "rosy_42", kind: "mobile", online: true, ageS: 1, battery: {percent: 55, charging: true}, estop: false, task: "충전", place: "C3 충전소"},
  {id: "rosy_43", kind: "mobile", online: false, ageS: 95, battery: {percent: 61}, estop: false, task: "S1로 이동", place: "S1 반출대 앞"},
  {id: "rosy_44", kind: "mobile"},
  {id: "rosy_45", kind: "mobile", online: true, ageS: 1, battery: {percent: 47}, estop: true, task: "정지", place: "S2 정지선"},
];
mount("robot-roster-mount", createRobotRoster(robotSamples.map(source => robotProfile(source)), {selectedId: "rosy_40", onSelect: () => {}}));
const panelStates = [["pending", {}], ["empty", {detail: "선택한 기간에 기록된 작업이 없습니다"}], ["error", {detail: "서버 응답을 받지 못했습니다"}]];
for (const [name, extra] of panelStates) {
  const stateCard = createStatePanel({id: "panel-state-" + name, onRetry: () => stateCard.set({state: "pending"})}); stateCard.set({state: name, ...extra});
  el("panel-states").append(stateCard.element);
}
// K3 / K1 / K5 / K6 / K9 choice parts and S1 shared selection (synthetic samples).
const say = (id, text) => {el(id).setAttribute("state", "ready"); el(id).textContent = text;};
let refreshes = 0;
const frames = () => Array.from({length: 6}, (_, i) => ({id: `frame-${i + 1}`, label: `프레임 ${i + 1}`, secondary: `검출 ${(i * 2 + refreshes) % 5}개 · 합성`,
  status: i === 2 ? {state: "delayed", text: "14초 늦음", icon: "history"} : i === 4 ? "caution" : i === 5 ? {state: "locked", text: "승격됨"} : undefined, disabled: i === 5}));
const frameList = mount("choice-list-mount", createChoiceList({id: "frame-list", label: "프레임 후보", items: frames(), onChange: id => say("choice-list-result", `선택 ${id}`)}));
el("choice-list-refresh").addEventListener("click", () => {refreshes += 1; frameList.set(frames());});
const speedItems = () => ["1", "2", "4", "8"].map(value => ({value, label: `${value}배속`}));
const speed = mount("choice-single-mount", createChoiceGroup({id: "speed-step", label: "재생 속도", mode: "single", value: "1", onChange: value => say("choice-single-result", `${value}배속`),
  items: speedItems()}));
el("choice-single-poll").addEventListener("click", () => speed.setItems(speedItems()));
el("choice-list-poll").addEventListener("click", () => frameList.set(frames()));
const fit = mount("choice-empty-mount", createChoiceGroup({id: "fit-mode", label: "맞춤 방식", mode: "single", allowEmpty: true, value: null,
  items: [{value: "fit", label: "맞춤"}, {value: "fill", label: "채움"}], onChange: value => say("choice-empty-result", `맞춤 방식 ${value}`)}));
el("choice-empty-clear").addEventListener("click", () => {fit.set(null); say("choice-empty-result", "값 없음(화면이 비움)");});
mount("choice-locked-mount", createChoiceGroup({id: "drive-mode", label: "주행 방식", mode: "single", value: "auto",
  items: [{value: "auto", label: "자동", disabled: true, reason: "정지 중에는 바꿀 수 없습니다"}, {value: "manual", label: "수동", disabled: true, reason: "정지 중에는 바꿀 수 없습니다"}]}));
const layerItems = [["obstacle", "장애물"], ["route", "경로"], ["grid", "지도 격자"], ["traffic", "교통"], ["charger", "충전소"]].map(([value, label]) => ({value, label}));
mount("choice-toggle-mount", createChoiceGroup({id: "map-layers", label: "지도 겹", mode: "toggle", items: layerItems, value: ["obstacle", "route", "traffic"], master: {label: "전체"},
  onChange: value => say("choice-toggle-result", `겹 ${value.length}개 켬`)}));
mount("choice-toggle-max-mount", createChoiceGroup({id: "robot-filter", label: "표시할 로봇 (최대 2)", mode: "toggle", max: 2, items: ["arm_a", "arm_b", "rosy_40", "rosy_41"].map(value => ({value, label: value}))}));
mount("choice-check-mount", createChoiceGroup({id: "data-kinds", label: "자료 종류", mode: "check", max: 3, value: ["image", "video"],
  items: [{value: "image", label: "이미지"}, {value: "video", label: "영상"}, {value: "label", label: "라벨"}, {value: "log", label: "로그", disabled: true, reason: "권한 없음"}],
  onChange: value => say("choice-check-result", `자료 종류 ${value.length}개`)}));
const choiceTabs = mount("choice-tabs-mount", createTabs({id: "choice-tabs", label: "견본 맥락", onChange: key => say("choice-tabs-result", `탭 ${key}`),
  tabs: [{label: "상태", id: "state", panelId: "choice-tab-state", content: node("p", "현재 상태와 근거")}, {label: "근거", id: "evidence", panelId: "choice-tab-evidence", content: node("p", "관측 근거 · 출처·시각")},
    {label: "도구", id: "tools", panelId: "choice-tab-tools", content: node("p", "보조 도구")}]}));
el("choice-tabs-select").addEventListener("click", () => {choiceTabs.select("evidence"); say("choice-tabs-result", "프로그램 선택: evidence (알림 없음)");});
const delay = ms => new Promise(done => setTimeout(done, ms));
mount("choice-tabs2-mount", createTabs({id: "tabs2", label: "견본 보기", activation: "automatic", onChange: key => say("choice-tabs2-result", `탭 ${key}`),
  beforeChange: async () => {await delay(120); return !el("choice-tabs2-veto").checked;},
  tabs: [{label: "기록", id: "history", icon: "history", iconOnly: true, panelId: "tab2-history", content: node("p", "기록 면")},
    {label: "도구", id: "tools", icon: "tools", iconOnly: true, panelId: "tab2-tools", content: node("p", "도구 면"), disabled: true, reason: "정지 중에는 도구를 쓸 수 없습니다"},
    {label: "근거", id: "evidence", icon: "info", panelId: "tab2-evidence", content: node("p", "근거 면")}]}));
// C20/C21/A3: skill states, evidence lines and the sample-data contract (every case is sample: true and the area says so).
for (const host of document.querySelectorAll("[data-sample-tag]")) host.replaceWith(sampleTag());
const evidence = (label, value, source, extra = {}) => ({label, value, source, ...extra});
const skillCases = [
  {id: "s1", title: "로봇을 막지 않는 제안", lifecycle: "waiting_approval", executor: "ik_chunk"},
  {id: "s2", title: "로봇을 막는 제안", lifecycle: "waiting_approval", executor: "ik_chunk", blocking: true},
  {id: "s3", title: "다른 운영자가 승인", lifecycle: "approved", executor: "ik_chunk"},
  {id: "s4", title: "스크립트", lifecycle: "running", executor: "ik_chunk", step: {n: 2, of: 5}, ageS: 1},
  {id: "s5", title: "학습 정책", lifecycle: "running", executor: "act", policyId: "act-pick", version: "0123456789abcdef", step: {n: 3, of: 5}, leaseS: 12, ageS: 2, guard: "ok"},
  {id: "s6", title: "놓임 확인", lifecycle: "measured_success", executor: "ik_chunk", measured: "verify_placed"},
  {id: "s7", title: "목표 칸 밖에 놓임", lifecycle: "measured_failure", executor: "ik_chunk", guard: "ok"},
  {id: "s8", title: "비상 정지 버튼", lifecycle: "stopped", executor: "act", guard: "estop"},
  {id: "s9", title: "owner 가드", lifecycle: "stopped", executor: "act", guard: "hold"},
  {id: "s10", title: "리스 만료", lifecycle: "timed_out", executor: "act", guard: "hold"},
  {id: "s11", title: "정책 실패 뒤", lifecycle: "fallback_proposed", executor: "ik_chunk"},
  {id: "s12", title: "알 수 없는 값", lifecycle: "dreaming"},
];
for (const item of skillCases) {
  const view = skillState(item), li = node("li");
  li.dataset.skillCase = item.id;
  if (view.tag) li.append(statusTag(view.tag.state, undefined, {icon: view.tag.icon}), " ");
  li.append(`${item.title} · `, node("strong", view.text), view.readout.length ? ` · ${view.readout.map(r => `${r.label} ${r.value}`).join(" · ")}` : "");
  el("skill-states").append(li);
}
const lines = [
  ["측정이 앞, 모델 값은 뒤", [evidence("모델 신뢰도", "0.82", "model"), evidence("이 구역 IK", "12/15 성공", "ledger"), evidence("놓임 확인", "성공", "measured", {ageS: 3, staleAfterS: 10})]],
  ["낡은 근거", [evidence("이 구역 IK", "12/15 성공", "ledger"), evidence("프레임", "물체 1개", "measured", {ageS: 42, staleAfterS: 10})]],
  ["값 없음·출처 없음", [evidence("이 구역 IK", "", "ledger"), evidence("모델 신뢰도", "0.5", undefined)]],
];
for (const [name, items] of lines) {
  const card = node("div"); card.dataset.evidenceCase = name; card.append(node("p", name), createEvidenceLine(items)); el("evidence-lines").append(card);
}
const selfApproval = {id: "self-1", sample: true, title: "적재 2단 제안", lifecycle: "waiting_approval", requested_by: "operator-a", evidence: [], candidates: [{id: "c1", label: "후보 1", reason: "빈 칸"}],
  approval_attempt: {by: "operator-a", result: "refused", reason: "제안자는 자기 제안을 승인할 수 없습니다"}};
const contractProblems = armAiCaseProblems(selfApproval);
if (contractProblems.length) throw new Error(`sample contract: ${contractProblems.join("; ")}`);
const approveBtn = action("승인", () => {}, "primary"), approveCause = createCauseLine(el("self-approval-mount"));
el("self-approval-mount").prepend(approveBtn, statusTag("locked"));
approveCause.set([approveBtn], selfApproval.approval_attempt.reason);
// S1: the roster, the pick select, the map-marker strip and the detail line all read ONE store.
const robots = robotSamples.map(source => robotProfile(source)), robotName = id => robots.find(robot => robot.id === id)?.name;
const robotSelection = createSelection("rosy_40");
mount("selection-roster-mount", createRobotRoster(robots, {selection: robotSelection}));
const pick = select("robot-pick", "로봇 고르기", robotOptions(robots));
pick.control.addEventListener("change", () => robotSelection.set(pick.control.value, {source: "pick"}));
el("selection-pick-mount").append(pick.element);
for (const robot of robots) {
  const item = node("li"), marker = action(robot.name, () => robotSelection.set(robot.id, {source: "map"}), "toggle");
  item.dataset.markerId = robot.id; marker.dataset.markerId = robot.id; item.append(marker); el("selection-markers").append(item);
}
function paintRobotSelection(id) {
  pick.control.value = id ?? "";
  for (const item of el("selection-markers").children) {
    const on = item.dataset.markerId === id, marker = item.firstElementChild;
    item.toggleAttribute("data-selected", on); marker.setAttribute("aria-pressed", String(on)); marker.textContent = on ? `선택됨 · ${robotName(item.dataset.markerId)}` : robotName(item.dataset.markerId);
  }
  say("selection-detail", id ? `선택: ${robotName(id)}` : "선택 없음");
}
mounted.push({dispose: robotSelection.subscribe(paintRobotSelection)}); paintRobotSelection(robotSelection.get());
// C15: 3D views load three.js only when this section nears the viewport (a page without a view never fetches it).
const views3d = [];
async function startRobotViews() {
  const {createRobotView} = await import("./robot-3d.js");
  const jointsA = {joint1: 0.5, joint2: 0.45, joint3: -0.6, joint4: 0.7, joint5: 0, gripper_joint_1: 0.2};
  const cases = [
    {id: "view-arm", of: 0, selected: false, joints: jointsA}, {id: "view-arm-selected", of: 0, selected: true, joints: jointsA},
    {id: "view-pinky", of: 3, selected: false, pose: {x: 0.5, y: -0.25, yaw: 0.9}}, {id: "view-pinky-selected", of: 3, selected: true, pose: {x: 0.5, y: -0.25, yaw: 0.9}},
    {id: "view-arm-stale", of: 2, selected: false, joints: {joint1: -0.4, joint2: 0.3, joint3: -0.3, joint4: 0.5, joint5: 0, gripper_joint_1: 0.1}},
  ];
  for (const item of cases) {
    const slot = document.createElement("div"); slot.id = item.id; el("robot-3d-mount").append(slot);
    const profile = robotProfile(robotSamples[item.of]);
    views3d.push(createRobotView(slot, {kind: profile.kind, profile, selected: item.selected, joints: item.joints, pose: item.pose}));
  }
  const skillSlot = document.createElement("div"); skillSlot.id = "view-arm-skill"; el("ai-skill-3d").append(skillSlot); // C20: the facts line gains the skill text, the drawing is the same
  views3d.push(createRobotView(skillSlot, {kind: "arm", profile: robotProfile(robotSamples[0]), joints: jointsA, skill: "규칙 운반 · 2/5"}));
  // S1: the same store as the roster above; a view cannot choose, it only follows
  for (const [robotId, sample, extra] of [["arm_a", 0, {joints: jointsA}], ["rosy_40", 3, {pose: {x: 0.5, y: -0.25, yaw: 0.9}}]]) {
    const slot = document.createElement("div"); slot.id = `selection-3d-${robotId}`; el("selection-3d").append(slot);
    const profile = robotProfile(robotSamples[sample]);
    views3d.push(createRobotView(slot, {kind: profile.kind, profile, selection: robotSelection, robotId, ...extra}));
  }
  const drawn = await Promise.all(views3d.map(view => view.ready));
  el("robot-3d-mount").dataset.drawn = drawn.every(Boolean) ? "all" : "fallback";
}
const startViews = () => {observer?.disconnect(); startRobotViews();};
const observer = "IntersectionObserver" in window ? new IntersectionObserver(entries => {if (entries.some(entry => entry.isIntersecting)) startViews();}, {rootMargin: "200px"}) : null;
if (observer) observer.observe(el("robot-3d")); else startViews();
window.addEventListener("pagehide", () => {mounted.forEach(component => component.dispose()); views3d.forEach(view => view.dispose());}, {once: true});
// C19: all localization states via localizationState + statusTag.
const locSamples = [
  {},
  {session_left_s: 18},
  {motion: {allowed: true, last_operator_request: {by: "alice"}}},
  {localization: {state: "CANDIDATES"}, report: {request_id: "r1", candidates: [{x: 1, y: 2, yaw: 0.2, scan_fit: 0.84}, {x: 1, y: 2, yaw: 3.34, scan_fit: 0.71}]}},
  {confirming: true},
  {localization: {state: "LOCALIZED"}, age_s: 5},
  {localization: {state: "LOCALIZED"}, age_s: 45},
  {localization: {state: "SUSPECT"}, age_s: 12},
  {anchor_blocked: true, anchor_refused_reason: "CAUTION_ACTIVE"},
  {localization: {state: "UNKNOWN", reason: "timeout"}},
  {stopped: true},
  {mission_result: "operator_required"},
];
for (const sample of locSamples) {
  const loc = localizationState(sample);
  const item = node("li");
  item.append(statusTag(loc.tag, loc.tag_text));
  if (loc.text !== loc.tag_text) item.append(node("span", loc.text));  // the sentence only where the short tag word adds less
  if (loc.reason && !loc.text.includes(loc.reason)) {
    const reason = node("span", loc.reason, "kit-loc-reason");
    item.append(reason);
  }
  el("localization-states-mount").append(item);
}
mountRobotDockDemo(el("robot-dock-demo"));
{
  const center = createAlertCenter({listEl: el("alert-center-list"), toastEl: el("alert-center-toasts"), announcer: getAnnouncer(document), isOnScreen: () => true});
  const crit = {kind: "crit", key: "demo-crit", title: "긴급", message: "rosy_42 연결이 끊겼습니다.", code: "LINK_LOST"};
  center.publish(crit);
  center.publish(crit);  // the same key is one item, x2
  center.publish({kind: "warn", key: "demo-warn", title: "주의", message: "배터리가 20% 아래입니다."});
}
el("kit-ready").setAttribute("state", "ready"); el("kit-ready").textContent = "견본 준비 완료";
