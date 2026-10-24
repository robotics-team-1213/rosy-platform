// Read projections and explicit stop requests share the Work area's existing authentication and lifetime.
import {fitView} from "/console/assets/site-map-model.js";
import {EVIDENCE_LABEL, MODE_LABEL, evidenceAgeText} from "/common/core_ui_logic.js";

const prefix = "/api/fleet/control-unit";
const availability = {AVAILABLE: "연결됨", STALE: "이전 정보", UNAVAILABLE: "정보 없음"};
const stopStates = {PENDING: "전달 대기", SENDING: "전달 중", ACKNOWLEDGED: "요청 수신",
  PARTIAL: "일부 응답", UNKNOWN: "전달 결과 미확인", STALE_FENCE: "정지 세대 변경 · 실행 안 함",
  NOT_REACHED: "미전달", SUPERSEDED_BY_OPERATOR_RECOMMISSIONING: "운영자 재시운전 확인 기록"};
const omxStates = {NOT_CONFIGURED: "미설정", REQUESTED: "요청됨", LOCAL_LATCHED: "국소 래치 응답",
  UNKNOWN: "미확인", PARTIAL: "일부 응답"};
const node = (tag, text = "", className = "") => Object.assign(document.createElement(tag), {textContent: text, className});
const button = (text, readOnly = false) => {
  const result = node("ui-button", text);
  // The shared role lock treats unmarked dynamic buttons as operator actions.
  if (readOnly) result.dataset.workRead = "";
  result.setAttribute("kind", "quiet"); result.setAttribute("type", "button"); return result;
};
function guard(control, reason) {
  control.disabled = Boolean(reason);
  if (reason) control.setAttribute("reason", reason); else control.removeAttribute("reason");
}
const age = (row, elapsed) => Number.isFinite(row.age_s) && row.age_s >= 0 ? row.age_s + elapsed : null;
const fresh = (row, elapsed) => row.availability === "AVAILABLE" && age(row, elapsed) !== null && age(row, elapsed) <= 5;

export function stopControls(overview, target, elapsed = 0) {
  const included = new Set([target]), rows = overview.units || [];
  if (!rows.some(row => row.unit_id === target)) return {};
  for (let pass = 0; pass < rows.length; pass++)
    for (const row of rows) if (included.has(row.parent)) included.add(row.unit_id);
  return Object.fromEntries(rows.filter(row => included.has(row.unit_id) && fresh(row, elapsed)
    && Number.isSafeInteger(row.dispatch?.authority_epoch) && row.dispatch.authority_epoch >= 0
    && Number.isSafeInteger(row.dispatch?.generation) && row.dispatch.generation >= 0)
    .map(row => [row.unit_id, {...row.dispatch}]));
}

function drawMap(holder, snapshot) {
  holder.replaceChildren();
  const model = {places: snapshot.places, edges: snapshot.lanes.map(lane => ({
    polyline: lane.points.map(point => [point.x, point.y])}))};
  if (!model.places.length && !model.edges.length) {
    holder.append(node("ui-empty", "활성 지도에 표시할 장소·차로가 없습니다.")); return;
  }
  const view = fitView(model, 640, 360), svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 640 360"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", snapshot.unit_id + " 관제 활성 지도 · 읽기 전용");
  const shape = (tag, attributes) => {
    const element = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    svg.append(element); return element;
  };
  for (const lane of snapshot.lanes) shape("polyline", {
    points: lane.points.map(point => view.toPx(point.x, point.y).join(",")).join(" ")});
  for (const place of snapshot.places) {
    const [x, y] = view.toPx(place.x, place.y);
    shape("circle", {cx: x, cy: y, r: 4});
    shape("text", {x: x + (x > 320 ? -8 : 8), y: y - 8, "text-anchor": x > 320 ? "end" : "start"}).textContent = place.label;
  }
  holder.append(svg);
}

export function createIntegratedControlView({scope, call, anchor, active, approveReason, principal, taskStatus}) {
  const panel = node("section"), heading = node("h2", "통합 관제"), status = node("p", "", "hint"),
    list = node("ul", "", "work-list"), selectedName = node("h3"), detail = node("div"),
    map = node("div", "", "integrated-map"), mapInfo = node("p", "", "hint"),
    mapRead = button("선택 관제 지도 보기", true), notice = node("p"), stop = button("선택한 하위 관제에 정지 요청"),
    newStop = button("새 정지 요청 준비"), readStop = button("같은 정지 기록 확인", true),
    results = node("ul", "", "work-list"), history = node("ul", "", "work-list"),
    historyState = node("p", "", "hint"), historyFold = node("details", "", "ui-disclosure"),
    historyHeading = node("summary", "이 관제의 정지 요청 기록"), stopIdentity = node("p", "", "hint");
  panel.id = "integrated-control"; heading.id = "integrated-control-heading";
  panel.setAttribute("aria-labelledby", heading.id); panel.hidden = true;
  list.setAttribute("aria-label", "관제 구성과 상태"); detail.id = "integrated-control-detail";
  results.id = "integrated-stop-results"; results.setAttribute("aria-label", "관제별 정지 요청 결과");
  history.id = "integrated-stop-history";
  status.setAttribute("role", "status"); notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
  stop.id = "integrated-stop"; stop.setAttribute("data-always-live", "");
  const actions = node("div", "", "ui-actions"); actions.append(stop, newStop, readStop);
  historyFold.append(historyHeading, historyState, history);
  const reconcileFold = node("details", "", "ui-disclosure"), form = node("form", "", "ui-form"),
    attestations = [], evidence = node("textarea"), reconcile = button("이 관제의 재시운전 확인 기록");
  reconcileFold.id = "integrated-reconcile"; reconcileFold.hidden = true;
  reconcileFold.append(node("summary", "미확인 전송의 운영자 확인"));
  form.append(node("p", "이 관제에서 실제 전송 연결 종료와 영향 receiver 재시운전을 마친 기명 운영자만 기록하세요. 정지 해제·재무장·물리 정지 증명이 아닙니다."));
  for (const [id, text] of [["channels", "기존 정지 전송 연결을 종료했습니다"],
    ["receivers", "영향받은 receiver의 재시운전을 확인했습니다"]]) {
    const label = node("label", text), input = node("input"); input.type = "checkbox"; input.className = "ui-field"; input.required = true;
    input.id = "integrated-confirm-" + id; label.htmlFor = input.id; label.prepend(input);
    form.append(label); attestations.push(input);
  }
  const evidenceLabel = node("label", "전송 종료·재시운전 확인 근거");
  evidence.id = "integrated-reconcile-evidence"; evidence.className = "ui-field";
  evidence.required = true; evidence.minLength = 16; evidence.maxLength = 2048; evidenceLabel.htmlFor = evidence.id;
  form.append(evidenceLabel, evidence, reconcile); reconcileFold.append(form);
  panel.append(heading, node("p", "상단 비상 정지는 이 관제의 직접 장치에 적용됩니다. 아래 하위 관제 정지 요청은 관제별 전달 결과를 확인해야 합니다.", "hint"),
    status, list, selectedName, detail, mapRead, mapInfo, map,
    node("h3", "선택한 하위 관제의 정지 요청"), node("p", "최신 정지 세대가 있는 관제만 요청에 포함합니다. 정보 없는 관제는 미전달일 수 있습니다. 물리 정지는 미확인입니다.", "hint"),
    actions, notice, stopIdentity, results, historyFold, reconcileFold);
  anchor.before(panel);
  let epoch = 0, overview = null, sampled = 0, target = null, inFlight = false, busy = false,
    selection = 0, detailRevision = 0, mapRef = null, pending = null, snapshot = null, reference = null, owner = null;
  const elapsed = () => Math.max(0, (performance.now() - sampled) / 1000);
  const valid = (life, version) => life.current() && version === epoch;
  const localFence = () => {
    if (!overview) return null;
    const fences = stopControls(overview, overview.unit_id, elapsed());
    return Object.hasOwn(fences, overview.unit_id) ? fences[overview.unit_id] : null;
  };
  function controls() {
    const reason = busy ? "요청 결과를 확인하고 있습니다" : approveReason();
    const fences = overview && target ? stopControls(overview, target, elapsed()) : {};
    const targetRow = overview?.units.find(row => row.unit_id === target);
    stop.textContent = target ? target + " 하위 관제에 정지 요청" : "선택한 하위 관제에 정지 요청";
    guard(stop, reason || (pending ? "같은 정지 기록을 먼저 확인하세요" :
      !targetRow || !fresh(targetRow, elapsed()) || !Object.hasOwn(fences, target) ? "선택 관제의 최신 정지 세대를 확인하세요" : ""));
    guard(newStop, reason || (pending && !snapshot ? "미확인 요청의 원장을 먼저 확인하세요" : ""));
    guard(readStop, busy ? "요청 결과를 확인하고 있습니다" : !pending ? "정지 요청 기록을 선택하세요" : "");
    guard(mapRead, !mapRef ? "선택 관제의 활성 지도 정보를 확인하세요" : "");
    const localResult = snapshot?.results.find(row => row.unit_id === overview?.unit_id);
    reconcileFold.hidden = !(reference?.local_reconciliation_required
      && ["UNKNOWN", "PARTIAL"].includes(localResult?.state));
    guard(reconcile, reason || (!localFence() ? "이 관제의 최신 정지 세대를 확인하세요" : ""));
  }
  function reset() {
    epoch++; selection++; overview = null; target = null; mapRef = null; pending = null; snapshot = null; reference = null;
    list.replaceChildren(); detail.replaceChildren(); map.replaceChildren(); results.replaceChildren(); history.replaceChildren();
    notice.textContent = ""; stopIdentity.textContent = ""; mapInfo.textContent = ""; panel.hidden = true;
    status.textContent = ""; selectedName.textContent = ""; historyState.textContent = "";
    form.reset(); reconcileFold.open = false; historyFold.open = false; controls();
  }
  scope.onDispose(reset);
  function paintUnits() {
    const focused = document.activeElement?.closest("[data-integrated-unit]")?.dataset.integratedUnit;
    list.replaceChildren();
    const items = new Map();
    for (const row of overview.units) {
      const item = node("li"), choose = button(row.unit_id + " · " + (row.parent ? "직접 상위 " + row.parent : "독립 관제"), true);
      choose.dataset.integratedUnit = row.unit_id; choose.setAttribute("aria-pressed", String(target === row.unit_id));
      choose.setAttribute("kind", "toggle");
      const info = node("p", (availability[row.availability] || "정보 없음") + evidenceAgeText(age(row, elapsed()))
        + " · 로봇 " + row.robots_online + "/" + row.robots_total + " · 미완료 작업 " + row.tasks_active
        + " · 미확인 정지 " + row.stop_pending
        + (row.sampled_at ? " · 수집 " + new Date(row.sampled_at).toLocaleTimeString() : " · 수집 시각 미확인"), "hint");
      info.dataset.evidence = fresh(row, elapsed()) ? "fresh" : row.availability === "UNAVAILABLE" ? "unavailable" : "delayed";
      choose.addEventListener("click", () => selectUnit(row.unit_id));
      item.append(choose, info); items.set(row.unit_id, item);
    }
    for (const row of overview.units) {
      const parent = items.get(row.parent), item = items.get(row.unit_id);
      if (parent) {
        let children = parent.querySelector(":scope > ul");
        if (!children) { children = node("ul", "", "work-list integrated-branches"); parent.append(children); }
        children.append(item);
      } else list.append(item);
    }
    items.get(focused)?.querySelector("ui-button")?.focus({preventScroll: true});
  }
  async function selectUnit(unitId) {
    target = unitId; selection++; mapRef = null; map.replaceChildren(); mapInfo.textContent = "";
    selectedName.textContent = unitId + " 관제 직접 자원"; detail.replaceChildren(node("p", "직접 자원 조회 중"));
    controls(); if (overview) paintUnits();
    await readDetail();
  }
  async function readDetail() {
    if (!overview || !target) return;
    const life = scope.capture(), version = epoch, current = selection, read = ++detailRevision, selected = target;
    try {
      const value = await call(prefix + "/units/" + encodeURIComponent(selected)); life.check();
      if (!valid(life, version) || current !== selection || read !== detailRevision) return;
      if (value.unit_id !== selected || value.config_revision !== overview.config_revision) throw new Error("unit identity changed");
      detail.replaceChildren(node("p", (availability[value.availability] || "정보 없음") + evidenceAgeText(value.age_s)
        + (value.sampled_at ? " · 수집 " + new Date(value.sampled_at).toLocaleString() : " · 수집 시각 미확인"), "hint"));
      for (const robot of value.robots) {
        const row = node("p", robot.robot_id + " · " + (robot.online ? "연결됨" : "연결 끊김") + evidenceAgeText(robot.state_age_s));
        const observed = channel => ["fresh", "delayed"].includes(robot.evidence[channel]);
        row.append(node("span", " · " + (Object.hasOwn(MODE_LABEL, robot.mode) ? MODE_LABEL[robot.mode] : "모드 미확인")));
        for (const [channel, label, text] of [
          ["battery", "배터리", observed("battery") && Number.isFinite(robot.battery_percent) ? robot.battery_percent + "%" : "미확인"],
          ["safety", "비상 정지", observed("safety") && typeof robot.estop === "boolean" ? robot.estop ? "켜짐" : "꺼짐" : "미확인"],
          ["pose", "위치", observed("pose") && robot.pose?.frame === "map" && robot.pose.map_id ? robot.pose.map_id + " · " + robot.pose.x + ", " + robot.pose.y : "미확인"]]) {
          const evidenceRow = node("span", " · " + label + " " + text + " (" + (EVIDENCE_LABEL[robot.evidence[channel]] || "미확인") + ")");
          evidenceRow.dataset.evidence = robot.evidence[channel] || "unknown"; row.append(evidenceRow);
        }
        detail.append(row);
      }
      detail.append(node("p", value.robots.length ? "직접 로봇 " + value.robots.length + "대" : "직접 소유 로봇이 없습니다.", "hint"));
      for (const task of value.tasks) detail.append(node("p", task.robot_id + " · " + task.task_id + " · " + taskStatus(task.status)
        + " · " + new Date(task.updated_at).toLocaleString()));
      detail.append(node("p", "직접 작업 " + value.tasks.length + "건" + (value.tasks_truncated ? " · 이전 작업 더 있음" : ""), "hint"));
      if (JSON.stringify(mapRef) !== JSON.stringify(value.map)) { map.replaceChildren(); mapInfo.textContent = ""; }
      mapRef = value.map; controls();
    } catch {
      if (valid(life, version) && current === selection && read === detailRevision) {
        mapRef = null; map.replaceChildren(); detail.replaceChildren(node("ui-empty", "직접 자원 조회 실패 · 관제 연결과 권한을 확인하세요.")); controls();
      }
    }
  }
  scope.listen(mapRead, "click", async () => {
    if (!mapRef || !overview || !target) return;
    const life = scope.capture(), version = epoch, current = selection, expected = {...mapRef}, selected = target;
    map.replaceChildren(node("p", "활성 지도 조회 중")); mapInfo.textContent = "";
    try {
      const value = await call(prefix + "/units/" + encodeURIComponent(selected) + "/map"); life.check();
      if (!valid(life, version) || current !== selection) return;
      if (value.unit_id !== selected || value.config_revision !== overview.config_revision
          || value.map.map_id !== expected.map_id || value.map.version !== expected.version
          || value.map.frame !== "unit_local" || mapRef?.map_id !== expected.map_id
          || mapRef?.version !== expected.version) throw new Error("map identity changed");
      mapInfo.textContent = selected + " · 지도 " + value.map.map_id + " · 버전 " + value.map.version
        + " · 관제 고유 좌표 · 읽기 전용";
      drawMap(map, value);
    } catch {
      if (valid(life, version) && current === selection) map.replaceChildren(node("ui-empty", "활성 지도 조회 실패 · 새 지도 정보를 확인하세요."));
    }
  });
  function paintSnapshot(value) {
    if (!pending || value.unit_id !== overview?.unit_id || value.origin_id !== pending.origin || value.stop_id !== pending.body.stop_id
        || value.target_unit !== pending.body.target_unit || value.config_revision !== pending.body.config_revision)
      throw new Error("stop identity changed");
    snapshot = value; results.replaceChildren();
    stopIdentity.textContent = "정지 요청 " + value.origin_id + " / " + value.stop_id + " · 대상 " + value.target_unit;
    for (const row of value.results) {
      const item = node("li"), state = node("p", row.unit_id + " · " + (stopStates[row.state] || "결과 미확인"));
      state.title = row.state; item.dataset.physicalStop = row.physical_stop;
      item.append(state, node("p", "로봇 응답 " + row.acknowledged_robots + " · 미확인 " + row.unknown_robots
        + " · OMX " + (omxStates[row.omx_state] || "미확인"), "hint"),
      node("p", "물리 정지 미확인 · 수신 응답은 실제 정지 확인과 별개입니다.", "hint"));
      if (row.dispatch) item.append(node("p", "원래 관제 세대 " + row.dispatch.authority_epoch + " / " + row.dispatch.generation, "hint"));
      results.append(item);
    }
    controls();
  }
  async function readRecord() {
    if (!pending || busy) return;
    const life = scope.capture(), version = epoch, expected = pending;
    try {
      const value = await call(prefix + "/stops/" + encodeURIComponent(expected.origin) + "/" + encodeURIComponent(expected.body.stop_id));
      life.check(); if (!valid(life, version) || pending !== expected) return;
      paintSnapshot(value); notice.textContent = "같은 정지 요청의 원장을 확인했습니다. 정지를 다시 보내지 않았습니다.";
    } catch {
      if (valid(life, version) && pending === expected) notice.textContent = "정지 기록 미확인 · 자동으로 다시 보내지 않았습니다. 연결·권한과 같은 요청 기록을 확인하세요.";
    }
  }
  async function write(path, body) {
    const life = scope.capture(), version = epoch, expected = pending; busy = true; controls();
    try {
      const value = await call(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      life.check(); if (!valid(life, version) || pending !== expected) return;
      paintSnapshot(value); notice.textContent = "요청 결과를 기록했습니다. 관제별 응답과 미확인 결과를 확인하세요.";
    } catch {
      if (valid(life, version)) notice.textContent = "정지 요청 결과 미확인 · 자동으로 다시 보내지 않았습니다. 같은 요청의 원장을 확인하세요.";
    } finally {
      busy = false; if (valid(life, version)) { controls(); await readHistory(); }
    }
  }
  scope.listen(stop, "click", () => {
    if (busy || pending || approveReason() || !overview || !target) return;
    const fences = stopControls(overview, target, elapsed());
    if (!Object.hasOwn(fences, target)) { controls(); return; }
    pending = {origin: overview.unit_id, body: {stop_id: crypto.randomUUID(), target_unit: target,
      config_revision: overview.config_revision, expected_controls: fences}};
    reference = null; snapshot = null; results.replaceChildren(); controls();
    stopIdentity.textContent = "정지 요청 " + pending.origin + " / " + pending.body.stop_id;
    write(prefix + "/stops", pending.body);
  });
  scope.listen(newStop, "click", () => {
    if (busy || approveReason() || pending && !snapshot) return;
    pending = null; snapshot = null; reference = null; form.reset(); results.replaceChildren(); stopIdentity.textContent = "";
    notice.textContent = "새 정지 요청을 준비했습니다. 선택 대상과 최신 관제 세대를 확인하세요."; controls();
  });
  scope.listen(readStop, "click", readRecord);
  scope.listen(form, "submit", event => event.preventDefault());
  scope.listen(reconcile, "click", () => {
    if (busy || approveReason() || reconcileFold.hidden || !pending || !form.reportValidity()
        || !attestations.every(input => input.checked) || evidence.value.trim().length < 16
        || !localFence()) return;
    write(prefix + "/stops/" + encodeURIComponent(pending.origin) + "/" + encodeURIComponent(pending.body.stop_id) + "/reconcile",
      {expected_generation: localFence().generation, receiver_channels_terminated: true, receivers_recommissioned: true,
        evidence: evidence.value.trim(), affected_units: [overview.unit_id]});
  });
  async function readHistory() {
    if (!overview) return;
    const life = scope.capture(), version = epoch;
    try {
      const value = await call(prefix + "/stops"); life.check();
      if (!valid(life, version)) return;
      if (value.unit_id !== overview.unit_id || value.config_revision !== overview.config_revision) throw new Error("history identity changed");
      const focused = document.activeElement?.closest("[data-integrated-stop]")?.dataset.integratedStop;
      history.replaceChildren(); historyState.textContent = value.stops.length + "건 · 이 관제의 최근 정지 기록";
      for (const row of value.stops) {
        const item = node("li"), choose = button(row.origin_id + " / " + row.stop_id + " · 대상 " + row.target_unit
          + (row.incomplete ? " · 결과 미확인" : " · 결과 기록됨"), true);
        choose.dataset.integratedStop = JSON.stringify([row.origin_id, row.stop_id]);
        choose.addEventListener("click", () => {
          if (busy) return;
          pending = {origin: row.origin_id, body: {stop_id: row.stop_id, target_unit: row.target_unit, config_revision: row.config_revision}};
          reference = row; snapshot = null; form.reset(); results.replaceChildren(); controls(); readRecord();
        });
        guard(choose, busy ? "요청 결과를 확인하고 있습니다" : "");
        item.append(choose); history.append(item);
        if (focused === choose.dataset.integratedStop) choose.focus({preventScroll: true});
        if (pending && pending.origin === row.origin_id && pending.body.stop_id === row.stop_id) reference = row;
      }
      controls();
    } catch {
      if (valid(life, version)) {
        reference = null; history.replaceChildren(); historyState.textContent = "정지 기록 조회 실패 · 이 관제의 접속 권한과 연결을 확인하세요."; controls();
      }
    }
  }
  async function refresh() {
    if (!active || inFlight) return;
    if (owner !== principal()) { owner = principal(); reset(); }
    const life = scope.capture(), version = epoch; inFlight = true;
    try {
      const value = await call(prefix + "/overview"); life.check();
      if (!valid(life, version)) return;
      if (overview && (value.unit_id !== overview.unit_id || value.config_revision !== overview.config_revision)) {
        reset(); return;
      }
      overview = value; sampled = performance.now(); panel.hidden = false;
      status.textContent = value.unit_id + " · 구성 " + value.config_revision + " · 관제별 수집 시각과 연결 상태";
      if (!target || !value.units.some(row => row.unit_id === target)) {
        target = value.unit_id; selection++; selectedName.textContent = target + " 관제 직접 자원";
      }
      paintUnits(); controls(); await Promise.all([readDetail(), readHistory()]);
    } catch (error) {
      if (valid(life, version)) {
        overview = null; mapRef = null; list.replaceChildren(); detail.replaceChildren(); map.replaceChildren(); controls();
        panel.hidden = error.status === 404;
        status.textContent = "통합 관제 조회 실패 · 접속 권한과 연결을 확인하세요.";
        if (error.status === 401 || error.status === 403) reset();
      }
    } finally { inFlight = false; }
  }
  return {refresh, reset};
}
