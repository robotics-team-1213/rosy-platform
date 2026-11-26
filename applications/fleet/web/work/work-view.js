// Source identity stays separate; Mission and Cell Job approval use the existing server admission route.
import { setOffBy } from "/common/cause-line.js";
import { patchHidden, patchText } from "/common/control-dom.js";
import {tripWaitText} from "/console/assets/trip-display.js";
import {owns, relays, unitScope} from "/console/assets/unit-scope.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { createControlUnitView } from "/console/assets/control-unit-view.js";
import { createArmTransferView } from "/console/assets/arm-transfer-view.js";
import { createTripProposalView } from "/console/assets/trip-proposal-view.js";
import { createIntegratedControlView } from "/console/assets/integrated-control-view.js";
const states = {REQUESTED: "요청 접수", UNKNOWN: "실행 결과 미확인", PROPOSED: "승인 전", READY: "실행 준비", QUEUED: "대기", DISPATCHING: "전달 중",
  ACCEPTED: "장치 수락", RUNNING: "실행 중", ACTION_SUCCEEDED: "동작 성공 · 목표 확인 대기",
  GOAL_CONFIRMED: "목표 확인 완료", COMPLETED: "주행 완료", FAILED: "실패", HOLD: "보류",
  CANCELED: "취소", EXPIRED: "만료", CLAIMED: "사건 인수", CLOSED: "사건 종료",
  started: "운행 요청 접수", running: "운행 요청 처리 중", link_wait: "연결 대기", arrived: "도착", stopped: "운행 정지", failed: "운행 실패", canceled: "운행 취소"};
const approvals = {two_person: "두 사람 · 제안한 사람이 아닌 이름 있는 운영자가 승인", proposer_only: "제안한 사람이 승인", one_person: "한 사람 · 이름 있는 운영자"};
// D-763 8 — 서버가 준 보이는 상태(읽기 투영). 원장 상태는 상세의 「상태」 그대로다.
const visible = {approval_pending: "승인 대기", in_progress: "진행 중", waiting: "기다림", intervention: "개입 필요", ended: "끝남"};
export const workKey = row => JSON.stringify([row.source, row.source_id]);
export const workStatus = status => states[status] || "상태 확인 필요";
const workMs = v => (v == null || v === "") ? NaN : (typeof v === "number" ? (Number.isFinite(v) && v > 0 ? (v < 1e12 ? v * 1000 : v) : NaN) : new Date(v).getTime());
export const formatWorkTime = v => { const ms = workMs(v); return Number.isFinite(ms) ? new Date(ms).toLocaleString() : "미확인"; };
const workKind = row => ({task: "주행", trip: "운행", cell_job: "팔레트 적재"})[row.source] || "팔 작업";
const approvable = row => (row.source === "mission" || row.source === "cell_job") && row.status === "PROPOSED";  // one admit route takes both (mission_routes.py)
export const canAdmitWorkHere = (row, scope = unitScope()) => approvable(row) && owns("arms", scope) && !relays(scope);
const idTail = v => String(v ?? "").split("-").pop().slice(0, 8);
const shortStamp = v => { const ms = workMs(v); return Number.isFinite(ms) ? new Date(ms).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : ""; };
const tripWait = row => ["started", "running", "link_wait"].includes(row.status) ? tripWaitText(row) : "";
export const workLine = (row, disambiguate = false) => [workKind(row), row.device_id, tripWait(row) || visible[row.visible_state] || workStatus(row.status),
  ...(disambiguate ? [idTail(row.source_id), row.workcell_id || shortStamp(row.updated_at)] : [])].filter(Boolean).join(" · ");
export const requestsNotice = s => s === 404 ? "대화 요청 접수가 설정되지 않았습니다." : s === 403 ? "대화 요청을 보려면 기명 운영자로 로그인해야 합니다." : s === 401 ? "기명 운영자 접속이 필요합니다." : "대화 요청 조회 실패";
export const requestsPause = status => status === 403;
export function summarizeWorkCounts(rows = []) {
  let pending = 0, active = 0, intervention = 0;
  for (const row of rows) {
    if (row?.visible_state === "approval_pending") pending++;
    else if (row?.visible_state === "in_progress" || row?.visible_state === "waiting") active++;
    else if (row?.visible_state === "intervention") intervention++;
  }
  return { total: rows.length, pending, active, intervention };
}
// D-865 P3 — 승인 범위 판정과 문구는 순수 함수다(node 시험 대상). 화면은 범위 사실을 읽어
// 표시만 하고 승인 자체는 서버의 정책 principal이 한다: 사람 승인과 같은 검사를 전부 통과한
// 제안만 범위 안에서 자동 승인된다. law(FL-*)·사람 점유·E-stop은 이 표시로 해제되지 않는다.
export const autoAdmitScope = (row, policy) => {
  if (!policy?.scope?.enabled || !row || !approvable(row)) return {member: false};
  if (!policy.scope.step_approval_kinds?.includes(row.approval)) return {member: false};
  if (!policy.scope.robots?.includes(row.device_id)) return {member: false};
  if (!(policy.admits_remaining > 0)) return {member: false, exhausted: true};
  return {member: true, remaining: policy.admits_remaining, revision: policy.scope.scope_revision};
};
export const autoAdmitDetail = (row, policy) => {
  if (!policy?.scope || !row || !approvable(row)) return null;
  if (!policy.scope.enabled) return "꺼짐 · 사람 승인";
  const scope = autoAdmitScope(row, policy);
  return scope.member ? `범위 안 · 잔여 ${scope.remaining}회 · 범위 ${scope.revision}` : "범위 밖 · 사람 승인";
};

export function createWorkView({scope, call, el, channelRequestView, approveReason, principal, confirm}) {
  const query = new URLSearchParams(location.search), area = query.get("view") === "work", fresh = area && query.get("show") === "new", active = area && !fresh;
  // D-741 7 — 승인 대기와 끝난 작업은 같은 조회 결과를 화면에서 상태로 거른 것이다.
  const shown = {__proto__: null, pending: ["approval_pending"], done: ["ended"]}[query.get("show")];  // D-763 8: the server's visible state
  let rows = [], selected = null, inFlight = false, detailVersion = 0, busy = false, refusal = "";
  let lastListSig = "", lastDetailSig = "", lastRequestsSig = "", requestsPaused = false;  // 403 pause until reset()
  const newStatus = Object.assign(document.createElement("p"), {id: "work-new-status", role: "status",
    textContent: "만들 수 있는 작업을 확인하고 있습니다."});
  el("work-new").querySelector("ul").before(newStatus);
  const list = el("work-list"), detail = el("work-detail"), admit = el("work-admit");
  const anchor = el("work-integrations-anchor");
  el("work-integrations").open = query.has("arm_transfer") || query.has("trip_proposal");
  const units = createControlUnitView({scope, call, anchor, active, approveReason, principal});
  const arms = createArmTransferView({scope, call, anchor, active, approveReason, principal, confirm});
  const trips = createTripProposalView({scope, call, anchor, active, approveReason, principal, confirm});
  const integrated = createIntegratedControlView({scope, call, anchor, active,
    approveReason, principal, taskStatus: workStatus});
  const clear = () => { lastDetailSig = ""; if (detail.childElementCount) detail.replaceChildren(); patchHidden(admit, true); };
  // D-763 9 — 새 작업은 서버가 여기서 실행할 수 있다고 답한 종류만 보인다. 답이 없으면 아무 종류도 없다.
  function showKinds(kinds = []) {
    patchHidden(el("work-new-move-item"), !kinds.includes("trip"));
    patchHidden(el("work-new-cell-item"), !kinds.includes("CELL_TRANSFER"));
    patchText(newStatus, kinds.includes("trip") || kinds.includes("CELL_TRANSFER")
      ? "작업 종류를 선택하세요. 실행 전 장치 상태와 권한을 다시 확인합니다."
      : "현재 만들 수 있는 작업이 없습니다. 장치 연결과 작업 설정을 확인하세요.");
  }
  el("work-overview").hidden = !active;
  const opsZone = el("work-ops-zone") || el("work-overview");
  // D-793 — 학습 정책의 단계·승인 창·확인 요청은 자기 화면에서 다룬다(하단 연동·정책 구역으로 이동).
  if (active && !document.getElementById("work-policy-link")) {
    const policyLink = Object.assign(document.createElement("a"),
      {id: "work-policy-link", className: "ui-action-link", href: "/console/policy",
        textContent: "정책에서 자동 승인과 학습 승인 관리"});
    policyLink.dataset.kind = "quiet";
    opsZone.append(policyLink);
  }
  function paintKpis(allRows = null) {
    if (!el("work-kpi-total")) return;
    const counts = allRows ? summarizeWorkCounts(allRows) : null;
    patchText(el("work-kpi-total"), counts ? String(counts.total) : "—");
    patchText(el("work-kpi-pending"), counts ? String(counts.pending) : "—");
    patchText(el("work-kpi-active"), counts ? String(counts.active) : "—");
    patchText(el("work-kpi-intervention"), counts ? String(counts.intervention) : "—");
    for (const [key, value] of [["pending", counts?.pending || 0], ["intervention", counts?.intervention || 0]]) {
      const box = document.querySelector(`.work-kpi[data-kpi="${key}"]`);
      if (!box) continue;
      if (value > 0) box.dataset.alert = "true";
      else delete box.dataset.alert;
    }
  }
  let policy = null;
  const policyGate = createPollGate();
  async function refreshPolicy(life) {
    if (!policyGate.due()) return;
    try {
      const read = await call("/api/fleet/policy-admission");
      life.check();
      policyGate.ok(); policy = read.status ?? null;
    } catch (error) {
      if (!life.current()) return;
      policy = null;
      policyGate.fail(error.status, error.code);
    }
  }
  el("work-new").hidden = !fresh;
  if (area) {
    document.querySelector('[aria-labelledby="map-heading"]').hidden = true;
    el("work-context").hidden = fresh;
    document.querySelector('[aria-labelledby="roster-heading"]').hidden = true;
  }
  function clearRequests(message) {
    lastRequestsSig = "";
    const requests = el("channel-requests"), state = el("channel-requests-state");
    const focused = requests.contains(document.activeElement);
    if (requests.childElementCount) requests.replaceChildren();
    patchText(state, message);
    if (focused) state.focus({preventScroll: true});
  }
  function reset(message = "접속 후 작업을 확인할 수 있습니다.", preserveUnits = false) {
    if (!preserveUnits) { units.reset(); arms.reset(); trips.reset(); integrated.reset(); }
    channelRequestView.reset();
    policy = null; policyGate.reset(); requestsPaused = false;
    rows = []; selected = null; detailVersion++; lastListSig = "";
    showKinds();
    patchText(newStatus, message);
    if (list.childElementCount) list.replaceChildren();
    clear();
    clearRequests(message);
    paintKpis(null);
    patchText(el("work-state"), message);
    patchText(el("work-evidence"), "작업을 선택하세요.");
  }
  function showDetail(row) {
    const canAdmitHere = canAdmitWorkHere(row);
    const reason = busy ? "요청 처리 중입니다" : approveReason() || refusal;
    const autoText = autoAdmitDetail(row, policy);
    const detailRows = [
      ["업무", {navigate: "이동", trip: "이동", PICK_PLACE: "파지·배치", CELL_TRANSFER: "팔레트 적재"}[row.action_kind] || "기타 작업"],
      ["담당 장치", row.device_id],
      ["작업 공간", row.workcell_id || "주행 지도 · 작업 공간 지정 없음"],
      ["실행 책임", row.source === "task" || row.source === "trip" ? "CORE · 주행" : "OMX · 팔"],
      ["상태", tripWait(row) || workStatus(row.status)],
      ...(row.approval ? [["승인 조건", approvals[row.approval] || "승인 조건 확인 필요"]] : []),
      ...(autoText ? [["자동 승인", autoText]] : []),
      ["최근 원장 갱신", formatWorkTime(row.updated_at)],
      ["사유", row.reason || "기록된 사유 없음"],
      ["작업 식별자", row.source_id],
      ...(approvable(row) && !canAdmitHere ? [["승인 위치", "이 팔을 맡은 셀 관제 화면에서 승인"]] : []),
    ];
    const detailSig = JSON.stringify([detailRows, canAdmitHere, reason]);
    if (detailSig !== lastDetailSig || !detail.firstElementChild) {
      lastDetailSig = detailSig;
      detail.replaceChildren(...detailRows.flatMap(([label, value]) => {
        const term = document.createElement("dt"), text = document.createElement("dd");
        term.textContent = label; text.textContent = value || "미확인";
        return [term, text];
      }));
    }
    patchHidden(admit, !canAdmitHere);
    setOffBy(admit, reason);
  }
  async function select(row) {
    selected = workKey(row); refusal = ""; paint(); showDetail(row);
    const version = ++detailVersion, life = scope.capture();
    patchText(el("work-evidence"), "결과 근거 조회 중");
    try {
      const path = {task: "tasks", trip: "trips", cell_job: "cell-jobs"}[row.source] || "missions";
      const result = await call(`/api/fleet/${path}/${encodeURIComponent(row.source_id)}`);
      life.check();
      if (version !== detailVersion) return;
      const current = result.task || result.mission || result.job || {...result, status: result.state, wait: result.wait || null};
      showDetail({...row, ...current, source: row.source, source_id: row.source_id, device_id: row.device_id});
      const count = result.history?.length || 0;
      patchText(el("work-evidence"), `${tripWait(current) || workStatus(current?.status)} · 최근 이력 ${count}건${result.history_truncated ? " · 이전 이력 더 있음" : ""}`);
    } catch (error) {
      if (!life.current() || version !== detailVersion) return;
      patchText(el("work-evidence"), error.status === 404 ? "이 작업의 상세를 조회할 수 없습니다." : "결과 근거를 확인할 수 없습니다.");
    }
  }
  function paint() {
    const filter = el("work-filter").value;
    const selection = rows.find(row => workKey(row) === selected);
    if (selection && filter !== "all" && selection.source !== filter) {
      selected = null; detailVersion++; clear();
      patchText(el("work-evidence"), "필터에 맞는 작업을 선택하세요.");
    }
    const visibleRows = rows.filter(row => filter === "all" || row.source === filter);
    const labelCounts = new Map();
    for (const row of visibleRows) { const base = workLine(row); labelCounts.set(base, (labelCounts.get(base) || 0) + 1); }
    const rowLabel = row => workLine(row, labelCounts.get(workLine(row)) > 1);
    const listSig = JSON.stringify(visibleRows.map(row => [
      workKey(row), selected === workKey(row), row.status, row.visible_state || "", rowLabel(row), autoAdmitScope(row, policy).member,
    ]));
    if (listSig !== lastListSig || (visibleRows.length > 0 && !list.firstElementChild)) {
      lastListSig = listSig;
      const focused = document.activeElement?.closest('[data-work-key]')?.dataset.workKey;
      list.replaceChildren();
      for (const row of visibleRows) {
        const item = document.createElement("li"), button = document.createElement("ui-button");
        item.dataset.visibleState = row.visible_state || "";
        button.setAttribute("kind", "toggle"); button.setAttribute("type", "button");  // toggle: aria-pressed draws the selection
        button.dataset.workKey = workKey(row);
        button.setAttribute("data-work-read", "");
        button.setAttribute("aria-pressed", String(selected === workKey(row)));
        button.title = `${row.source} · ${row.source_id} · ${row.status}`;
        button.textContent = rowLabel(row);
        button.addEventListener("click", () => select(row));
        item.append(button);
        // D-865 P3 — 승인 대기 행의 자동 승인 범위 소속 표시(auto_admit 표기 규칙).
        if (autoAdmitScope(row, policy).member) {
          const badge = document.createElement("span");
          badge.className = "work-auto-admit"; badge.textContent = "자동 승인";
          badge.title = "승인 범위 안의 작업입니다. 사람 클릭 없이 정책이 승인할 수 있습니다.";
          item.append(badge);
        }
        list.append(item);
        if (focused === workKey(row)) button.focus({preventScroll: true});
      }
    }
    patchHidden(el("work-empty"), list.childElementCount > 0);
  }
  // 승인은 Cell·대화 검토와 같은 원장 경로다: 현재 정지 세대를 읽어 그대로 보내고, 판단은 서버가 한다.
  async function approve() {
    const row = rows.find(row => workKey(row) === selected), life = scope.capture();
    if (!row || busy || refusal || approveReason() || !canAdmitWorkHere(row)) return;
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
    if (!area) return channelRequestView.refresh();
    if (inFlight) return;
    const life = scope.capture(); inFlight = true;
    try {
      await Promise.all([units.refresh(), arms.refresh(), trips.refresh(), integrated.refresh(), refreshPolicy(life)]);
      const result = await call("/api/fleet/work"); life.check();
      showKinds(result.kinds);
      if (fresh) return;
      paintKpis(result.rows);
      const previous = rows.find(row => workKey(row) === selected);
      rows = shown ? result.rows.filter(row => shown.includes(row.visible_state)) : result.rows;
      const changed = rows.find(row => workKey(row) === selected);
      if (previous && changed && previous.updated_at !== changed.updated_at) {
        detailVersion++;
        patchText(el("work-evidence"), "작업 상태가 갱신됐습니다. 작업을 다시 선택해 결과 근거를 확인하세요.");
      }
      patchText(el("work-state"), `${shown && result.truncated_sources.length ? `최근 ${result.rows.length}건 중 ` : ""}${rows.length}건 · 조회 ${new Date(result.observed_at).toLocaleTimeString()}${result.truncated_sources.length ? " · 최근 목록 일부" : ""}`);
      patchText(el("work-sources"), [result.tasks_available ? "주행 원장" : "주행 원장 미설정",
        result.missions_available ? "내 팔 작업 원장" : "팔 작업 원장 미설정",
        result.cell_jobs_available ? "팔레트 적재 작업 원장" : "팔레트 적재 작업 원장 미설정", "운행 기록"].join(" · "));
      const current = rows.find(row => workKey(row) === selected);
      if (selected && !current) { selected = null; detailVersion++; clear(); patchText(el("work-evidence"), "선택한 작업이 현재 조회 범위에 없습니다."); }
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
    if (requestsPaused) return;  // 권한이 없으면 같은 403을 매 주기 두드리지 않는다
    try {
      const result = await call("/api/fleet/channel-requests"); life.check();
      const reqSig = JSON.stringify(result.rows.map(row => [row.request_id, row.received_at, row.content]));
      if (reqSig !== lastRequestsSig) {
        lastRequestsSig = reqSig;
        const focused = requests.contains(document.activeElement) ? document.activeElement?.closest("[data-request-id]")?.dataset.requestId : null;
        let restored;
        requests.replaceChildren();
        for (const row of result.rows) {
          const item = document.createElement("li"), text = document.createElement("p"), info = document.createElement("p");
          text.textContent = row.content;
          info.className = "hint";
          info.textContent = `접수 · ${formatWorkTime(row.received_at)} · ${row.request_id}`;
          item.append(text, info); requests.append(item);
          const button = document.createElement("ui-button");
          button.dataset.requestId = row.request_id;
          button.setAttribute("kind", "quiet"); button.setAttribute("type", "button");
          button.textContent = "요청 검토";
          button.addEventListener("click", () => channelRequestView.select(row)); item.append(button);
          if (focused === row.request_id) restored = button;
        }
        if (focused) (restored || state).focus({preventScroll: true});
      }
      patchText(state, `${result.rows.length}건 · 접수된 원문입니다. 실행 승인은 별도로 확인합니다.`);
    } catch (error) {
      if (!life.current()) return;
      channelRequestView.reset();
      if (requestsPause(error.status)) requestsPaused = true;
      clearRequests(requestsNotice(error.status));
    }
  }
  scope.listen(el("work-filter"), "change", paint);
  scope.listen(el("work-refresh"), "click", refresh);
  scope.listen(admit, "click", approve);
  return {active, refresh, reset};
}
