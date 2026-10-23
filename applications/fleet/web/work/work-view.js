// Source identity stays separate; Mission and Cell Job approval use the existing server admission route.
import { tripWaitText } from "/console/assets/site-map-model.js";
import { createControlUnitView } from "/console/assets/control-unit-view.js";
const states = {REQUESTED: "요청 접수", UNKNOWN: "실행 결과 미확인", PROPOSED: "승인 전", READY: "실행 준비", QUEUED: "대기", DISPATCHING: "전달 중",
  ACCEPTED: "장치 수락", RUNNING: "실행 중", ACTION_SUCCEEDED: "동작 성공 · 목표 확인 대기",
  GOAL_CONFIRMED: "목표 확인 완료", COMPLETED: "주행 완료", FAILED: "실패", HOLD: "보류",
  CANCELED: "취소", EXPIRED: "만료", CLAIMED: "사건 인수", CLOSED: "사건 종료",
  started: "운행 출발", running: "운행 중", link_wait: "연결 대기", arrived: "도착", stopped: "운행 정지", failed: "운행 실패", canceled: "운행 취소"};
const approvals = {two_person: "두 사람 · 제안한 사람이 아닌 이름 있는 운영자가 승인", proposer_only: "제안한 사람이 승인", one_person: "한 사람 · 이름 있는 운영자"};
// D-763 8 — 서버가 준 보이는 상태(읽기 투영). 원장 상태는 상세의 「상태」 그대로다.
const visible = {approval_pending: "승인 대기", in_progress: "진행 중", waiting: "기다림", intervention: "개입 필요", ended: "끝남"};
export const workKey = row => JSON.stringify([row.source, row.source_id]);
export const workStatus = status => states[status] || "상태 확인 필요";
export const workKind = row => ({task: "주행", trip: "운행", cell_job: "Cell 적재"})[row.source] || "팔 작업";
const approvable = row => (row.source === "mission" || row.source === "cell_job") && row.status === "PROPOSED";  // one admit route takes both (mission_routes.py)
export const workLine = row => [workKind(row), row.device_id, tripWaitText(row) || visible[row.visible_state] || workStatus(row.status)].join(" · ");

export function createWorkView({scope, call, el, channelRequestView, approveReason, principal}) {
  const query = new URLSearchParams(location.search), area = query.get("view") === "work", fresh = area && query.get("show") === "new", active = area && !fresh;
  // D-741 7 — 승인 대기와 끝난 작업은 같은 조회 결과를 화면에서 상태로 거른 것이다.
  const shown = {__proto__: null, pending: ["approval_pending"], done: ["ended"]}[query.get("show")];  // D-763 8: the server's visible state
  let rows = [], selected = null, inFlight = false, detailVersion = 0, busy = false, refusal = "";
  const list = el("work-list"), detail = el("work-detail"), admit = el("work-admit");
  const units = createControlUnitView({scope, call, anchor: el("channel-requests-heading"), active, approveReason, principal});
  const clear = () => { detail.replaceChildren(); admit.hidden = true; };
  // D-763 9 — 새 작업은 서버가 여기서 실행할 수 있다고 답한 종류만 보인다. 답이 없으면 아무 종류도 없다.
  function showKinds(kinds = []) {
    el("work-new-move-item").hidden = !kinds.includes("trip");
    el("work-new-cell-item").hidden = !kinds.includes("CELL_TRANSFER");
  }
  el("work-overview").hidden = !active;
  // D-793 — 학습 정책의 단계·승인 창·확인 요청은 자기 화면에서 다룬다.
  if (active && !document.getElementById("work-policy-link")) {
    el("work-overview").prepend(Object.assign(document.createElement("a"),
      {id: "work-policy-link", href: "/console/policy", textContent: "학습 정책 승인 — 단계·승인 창·확인 요청"}));
  }
  el("work-new").hidden = !fresh;
  if (area) {
    document.querySelector('[aria-labelledby="map-heading"]').hidden = true;
    el("work-context").hidden = fresh;
    document.querySelector('[aria-labelledby="roster-heading"]').hidden = true;
  }
  function reset(message = "접속 후 작업을 확인할 수 있습니다.", preserveUnits = false) {
    if (!preserveUnits) units.reset();
    channelRequestView.reset();
    rows = []; selected = null; detailVersion++;
    showKinds();
    list.replaceChildren(); clear();
    el("channel-requests").replaceChildren();
    el("channel-requests-state").textContent = message;
    el("work-state").textContent = message;
    el("work-evidence").textContent = "작업을 선택하세요.";
  }
  function field(label, value) {
    const term = document.createElement("dt"), text = document.createElement("dd");
    term.textContent = label; text.textContent = value || "미확인";
    detail.append(term, text);
  }
  function showDetail(row) {
    clear();
    field("업무", {navigate: "이동", trip: "이동", PICK_PLACE: "파지·배치", CELL_TRANSFER: "Cell 적재"}[row.action_kind] || "기타 작업");
    field("담당 장치", row.device_id);
    field("작업 공간", row.workcell_id || "주행 지도 · 작업 공간 지정 없음");
    field("실행 책임", row.source === "task" || row.source === "trip" ? "CORE · 주행" : "OMX · 팔");
    field("상태", workStatus(row.status));
    // D-763 7 — the step-kind registry's rule on the work read (PROPOSED rows only); read-only, no approve here.
    if (row.approval) field("승인 조건", approvals[row.approval] || "승인 조건 확인 필요");
    field("최근 원장 갱신", new Date(row.updated_at).toLocaleString());
    field("사유", row.reason || "기록된 사유 없음");
    field("작업 식별자", row.source_id);
    // D-741 7 — 막힌 단추에 그 이유를 적는다. 권한은 세션에서, 그 밖의 거절은 서버가 답한 말 그대로다.
    admit.hidden = !approvable(row);
    const reason = busy ? "요청 처리 중입니다" : approveReason() || refusal;
    if (reason) admit.setAttribute("reason", reason); else admit.removeAttribute("reason");
    admit.disabled = Boolean(reason);
  }
  async function select(row) {
    selected = workKey(row); refusal = ""; paint(); showDetail(row);
    const version = ++detailVersion, life = scope.capture();
    el("work-evidence").textContent = "결과 근거 조회 중";
    try {
      const path = {task: "tasks", trip: "trips", cell_job: "cell-jobs"}[row.source] || "missions";
      const result = await call(`/api/fleet/${path}/${encodeURIComponent(row.source_id)}`);
      life.check();
      if (version !== detailVersion) return;
      const current = result.task || result.mission || result.job || {...result, status: result.state};
      showDetail({...row, ...current, source: row.source, source_id: row.source_id, device_id: row.device_id});
      const count = result.history?.length || 0;
      el("work-evidence").textContent = `${workStatus(current?.status)} · 최근 이력 ${count}건${result.history_truncated ? " · 이전 이력 더 있음" : ""}`;
    } catch (error) {
      if (!life.current() || version !== detailVersion) return;
      el("work-evidence").textContent = error.status === 404 ? "이 작업의 상세를 조회할 수 없습니다." : "결과 근거를 확인할 수 없습니다.";
    }
  }
  function paint() {
    const filter = el("work-filter").value;
    const selection = rows.find(row => workKey(row) === selected);
    if (selection && filter !== "all" && selection.source !== filter) {
      selected = null; detailVersion++; clear();
      el("work-evidence").textContent = "필터에 맞는 작업을 선택하세요.";
    }
    const focused = document.activeElement?.closest('[data-work-key]')?.dataset.workKey;
    list.replaceChildren();
    for (const row of rows.filter(row => filter === "all" || row.source === filter)) {
      const item = document.createElement("li"), button = document.createElement("ui-button");
      button.setAttribute("kind", "toggle"); button.setAttribute("type", "button");  // toggle: aria-pressed draws the selection
      button.dataset.workKey = workKey(row);
      button.setAttribute("data-work-read", "");
      button.setAttribute("aria-pressed", String(selected === workKey(row)));
      button.title = `${row.source} · ${row.source_id} · ${row.status}`;
      button.textContent = workLine(row);
      button.addEventListener("click", () => select(row));
      item.append(button); list.append(item);
      if (focused === workKey(row)) button.focus({preventScroll: true});
    }
    el("work-empty").hidden = list.childElementCount > 0;
  }
  // 승인은 Cell·대화 검토와 같은 원장 경로다: 현재 정지 세대를 읽어 그대로 보내고, 판단은 서버가 한다.
  async function approve() {
    const row = rows.find(row => workKey(row) === selected), life = scope.capture();
    if (!row || busy || refusal || approveReason() || !approvable(row)) return;
    busy = true; refusal = ""; showDetail(row);
    try {
      const control = await call("/api/fleet/dispatch-control"); life.check();
      await call(`/api/fleet/missions/${encodeURIComponent(row.source_id)}/admit`, {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({expected_generation: control.generation})});
    } catch (error) {
      // a late answer belongs to its own row; a newer selection keeps its own (clear) refusal
      if (workKey(row) === selected) refusal = error.status >= 400 && error.status < 500 ? `승인이 거절됐습니다 · ${error.message}`
        : "승인 결과 미확인 · 다시 보내지 않았습니다. 원장을 확인하세요.";
    } finally { busy = false; }
    if (!life.current()) return;
    if (workKey(row) === selected) showDetail(row);
    await refresh();
  }
  async function refresh() {
    if (!area || inFlight) return;
    const life = scope.capture(); inFlight = true;
    try {
      await units.refresh();
      const result = await call("/api/fleet/work"); life.check();
      showKinds(result.kinds);
      if (fresh) return;
      const previous = rows.find(row => workKey(row) === selected);
      rows = shown ? result.rows.filter(row => shown.includes(row.visible_state)) : result.rows;
      channelRequestView.setSources(result.rows);
      const changed = rows.find(row => workKey(row) === selected);
      if (previous && changed && previous.updated_at !== changed.updated_at) {
        detailVersion++;
        el("work-evidence").textContent = "작업 상태가 갱신됐습니다. 작업을 다시 선택해 결과 근거를 확인하세요.";
      }
      el("work-state").textContent = `${shown && result.truncated_sources.length ? `최근 ${result.rows.length}건 중 ` : ""}${rows.length}건 · 조회 ${new Date(result.observed_at).toLocaleTimeString()}${result.truncated_sources.length ? " · 최근 목록 일부" : ""}`;
      el("work-sources").textContent = [result.tasks_available ? "주행 원장" : "주행 원장 미설정",
        result.missions_available ? "내 팔 작업 원장" : "팔 작업 원장 미설정",
        result.cell_jobs_available ? "Cell 작업 원장" : "Cell 작업 원장 미설정", "운행 기록"].join(" · ");
      const current = rows.find(row => workKey(row) === selected);
      if (selected && !current) { selected = null; detailVersion++; clear(); el("work-evidence").textContent = "선택한 작업이 현재 조회 범위에 없습니다."; }
      if (current) showDetail(current);
      paint();
      await refreshRequests(life);
      await channelRequestView.refresh();
    } catch (error) {
      if (life.current()) reset(error.status === 401 || error.status === 403 ? "작업 조회 권한을 확인하세요." : "작업 조회 실패 · 이전 목록을 사용할 수 없습니다.", true);
    } finally { inFlight = false; }
  }
  async function refreshRequests(life) {
    const requests = el("channel-requests"), state = el("channel-requests-state");
    try {
      const result = await call("/api/fleet/channel-requests"); life.check();
      requests.replaceChildren();
      for (const row of result.rows) {
        const item = document.createElement("li"), text = document.createElement("p"), info = document.createElement("p");
        text.textContent = row.content;
        info.className = "hint";
        info.textContent = `접수 · ${new Date(row.received_at).toLocaleString()} · ${row.request_id}`;
        item.append(text, info); requests.append(item);
        const button = document.createElement("ui-button");
        button.setAttribute("kind", "quiet"); button.setAttribute("type", "button");
        button.textContent = "요청 검토";
        button.addEventListener("click", () => channelRequestView.select(row)); item.append(button);
      }
      state.textContent = `${result.rows.length}건 · 접수된 원문입니다. 실행 승인은 별도로 확인합니다.`;
    } catch (error) {
      if (!life.current()) return;
      requests.replaceChildren();
      channelRequestView.reset();
      state.textContent = error.status === 404 ? "대화 요청 접수가 설정되지 않았습니다." :
        error.status === 401 || error.status === 403 ? "기명 운영자 접속이 필요합니다." : "대화 요청 조회 실패";
    }
  }
  scope.listen(el("work-filter"), "change", paint);
  scope.listen(el("work-refresh"), "click", refresh);
  scope.listen(admit, "click", approve);
  return {active, refresh, reset};
}
