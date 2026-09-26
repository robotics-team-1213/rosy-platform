// D-204 device surface: read-only view of the board probe. Refresh asks CORE
// to signal the root probe; the browser never inspects device nodes itself.

const REFRESH_MS = 10_000;

const STATES = {
  ok: {label: "정상", status: "OK"},
  no_response: {label: "응답 없음", status: "ERROR"},
  bus_missing: {label: "버스 없음", status: "WARNING"},
  driver_missing: {label: "드라이버 없음", status: "WARNING"},
  needs_human: {label: "사람 확인 필요"},
  not_measured: {label: "측정 안 함"},
};

function node(tag, className, value) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value !== undefined) item.textContent = value;
  return item;
}

function measuredText(payload) {
  const stamp = Date.parse(payload.measured_at || "");
  if (!Number.isFinite(stamp)) return "측정 시각 없음";
  const time = new Date(stamp).toLocaleString("ko-KR", {hour12: false});
  const age = Math.max(0, Math.floor(Number(payload.age_s) || 0));
  const ago = age < 60 ? `${age}초 전`
    : age < 3600 ? `${Math.floor(age / 60)}분 전`
      : `${Math.floor(age / 3600)}시간 전`;
  return `측정 ${time} · ${ago}`;
}

function deviceRow(device) {
  const row = node("li", "hardware-device");
  row.dataset.state = Object.hasOwn(STATES, device.state) ? device.state : "not_measured";
  const identity = node("div", "hardware-device-identity");
  identity.append(node("strong", "", device.label || device.id || "이름 없음"));
  if (device.bus) identity.append(node("small", "hardware-device-bus", device.bus));

  const state = STATES[device.state] || STATES.not_measured;
  const chip = node("span", "mode-chip hardware-device-state", state.label);
  if (state.status) chip.dataset.status = state.status;

  const evidence = node("p", "hardware-device-evidence", device.evidence || "근거 없음");
  row.append(identity, chip, evidence);
  return row;
}

export function mount(el, ctx) {
  const head = node("ui-head", "", "보드 장치 상태");
  const facts = node("dl", "hardware-facts");
  const measured = node("div", "hardware-measured");
  measured.append(node("dt", "", "마지막 측정"), node("dd", "", "불러오는 중"));
  facts.append(measured);

  const note = node("p", "hardware-note", "측정 결과를 불러오는 중입니다.");
  note.setAttribute("role", "status");
  const list = node("ul", "hardware-device-list");
  list.setAttribute("aria-label", "보드 장치별 상태와 근거");
  const refresh = node("ui-button", "hardware-refresh", "다시 점검");
  refresh.setAttribute("kind", "quiet");
  refresh.type = "button";
  refresh.disabled = ctx.role !== "administrator";
  refresh.setAttribute("aria-label", "관리자 보드 장치 점검 요청");

  el.append(head, facts, note, list, refresh);

  function render(payload) {
    const dd = facts.querySelector("dd");
    if (payload?.available !== true) {
      facts.dataset.available = "false";
      facts.dataset.stale = "false";
      dd.textContent = "측정 결과 없음";
      note.textContent = payload?.detail || "장치 점검 결과를 아직 받지 못했습니다.";
      list.replaceChildren();
      return;
    }

    facts.dataset.available = "true";
    facts.dataset.stale = payload.stale === true ? "true" : "false";
    dd.textContent = measuredText(payload);
    list.replaceChildren(...(payload.devices || []).map(deviceRow));
    if (payload.stale === true) {
      note.textContent = "오래된 측정 결과입니다. 관리자가 다시 점검을 요청할 수 있습니다.";
    } else if (!(payload.devices || []).length) {
      note.textContent = "측정 결과에 등록된 장치가 없습니다.";
    } else {
      note.textContent = `${payload.devices.length}개 장치의 관측 결과입니다. 사람 확인 필요와 미측정 상태는 정상 판정이 아닙니다.`;
    }
  }

  function fail(error) {
    facts.dataset.available = "false";
    // Keep the last readout visible, but never let an old response look current.
    facts.dataset.stale = "true";
    note.textContent = error.status === 403
      ? "장치 상태를 볼 권한이 없습니다."
      : `장치 상태를 가져오지 못했습니다: ${error.message}`;
  }

  let refreshing = false;
  const onRefresh = async () => {
    if (refreshing || ctx.role !== "administrator") return;
    refreshing = true;
    refresh.disabled = true;
    note.textContent = "새 장치 점검을 요청하고 있습니다.";
    try {
      const reply = await ctx.api("/api/v1/host/hardware/refresh", {method: "POST"});
      note.textContent = reply.accepted === true
        ? "점검을 요청했습니다. 새 측정 시각과 장치 상태로 결과를 확인하세요."
        : (reply.detail || "최근 요청이 있어 점검을 다시 요청하지 않았습니다.");
    } catch (error) {
      note.textContent = error.status === 403
        ? "장치 점검을 요청할 권한이 없습니다."
        : `장치 점검 요청 실패: ${error.message}`;
    } finally {
      refreshing = false;
      refresh.disabled = ctx.role !== "administrator";
    }
  };
  refresh.addEventListener("click", onRefresh);

  const stop = ctx.store.poll("/api/v1/host/hardware", REFRESH_MS, render, fail);
  return () => {
    stop();
    refresh.removeEventListener("click", onRefresh);
  };
}
