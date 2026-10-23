import {node, action, input, select} from "./control-dom.js";
import {createFormErrors, createFilePicker, createSearchSelect, createDateRange, createDirtyGuard} from "./form-controls.js";
import {createListToolbar, createDataTable, createPagination, createSelectionBar, createPrimaryDetail} from "./collection-controls.js";
import {createTabs, createDisclosure, createActionMenu, createSupplementPanel} from "./interaction-controls.js";
import {createStatePanel, createActionBar, createOperationResult, createProgress, createTimeline, createSteps, createLogView} from "./workflow-controls.js";
import {confirmIrreversible} from "/common/ui.js";

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
el("gallery-stop").addEventListener("click", () => {el("stop-result").textContent = "정지 조작 견본 · 실제 로봇 정지 아님"; el("stop-result").setAttribute("state", "ready");});

const steps = mount("steps-mount", createSteps({id: "steps-example", labels: ["파일 선택", "검증", "미리보기", "결과 확인"]}));
let step = 0; steps.set(step);
const nextStep = action("다음 단계 견본", () => steps.set(step = (step + 1) % 4)); nextStep.id = "step-next"; el("steps-mount").append(nextStep);
const progress = mount("progress-mount", createProgress({id: "progress-example", label: "자료 전송 견본"})); progress.set(null);
const known = action("40% 진행 견본", () => progress.set(40)); known.id = "progress-known"; el("progress-mount").append(known);
const timeline = mount("timeline-mount", createTimeline({id: "timeline-example", label: "작업 이력 견본"}));
timeline.set([{label: "접수", at: "2026-10-23T09:00:00+09:00"}, {label: "완료 미확인", detail: "현재 상태를 다시 조회해야 합니다"}]);
mount("log-mount", createLogView({label: "공개 진단 견본", text: "task=sample-1\nstate=accepted\nresult=unknown\n실제 계정·토큰·장치 주소를 기록하지 않습니다."}));
window.addEventListener("pagehide", () => mounted.forEach(component => component.dispose()), {once: true});
el("kit-ready").setAttribute("state", "ready"); el("kit-ready").textContent = "견본 준비 완료";
