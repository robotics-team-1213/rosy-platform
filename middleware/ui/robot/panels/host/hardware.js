// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
// D-204 device surface: CORE owns the board probe and short hardware test.

const REFRESH_MS = 10_000;

// D-359 §5.2 — tag는 공용 <ui-tag status> 어휘다. status는 서버 어휘 그대로 남긴다.
const STATES = {
  ok: {label: "정상", status: "OK", tag: "active"},
  no_response: {label: "응답 없음", status: "ERROR", tag: "crit"},
  bus_missing: {label: "버스 없음", status: "WARNING", tag: "warn"},
  driver_missing: {label: "드라이버 없음", status: "WARNING", tag: "warn"},
  needs_human: {label: "사람 확인 필요", tag: "neutral"},
  not_measured: {label: "측정 안 함", tag: "neutral"},
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
  const chip = node("ui-tag", "hardware-device-state", state.label);
  chip.setAttribute("status", state.tag);
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
  const actionNote = node("p", "hardware-action-note", "");
  actionNote.id = "hardware-action-note";
  actionNote.setAttribute("role", "status");
  actionNote.setAttribute("aria-live", "polite");
  const list = node("ul", "hardware-device-list");
  list.setAttribute("aria-label", "보드 장치별 상태와 근거");
  const refresh = node("ui-button", "hardware-refresh", "다시 점검");
  refresh.setAttribute("kind", "quiet");
  refresh.type = "button";
  setOff(refresh, ctx.role !== "administrator", "관리자 권한 필요");
  refresh.setAttribute("aria-label", "보드 장치 점검 요청");
  refresh.setAttribute("aria-describedby", actionNote.id);
  const lampTest = node("ui-button", "hardware-lamp-test", "후면 램프 자가 시험");
  lampTest.setAttribute("kind", "quiet");
  lampTest.type = "button";
  lampTest.setAttribute("aria-describedby", actionNote.id);
  setOff(lampTest, true, "램프 상태 확인 중");
  actionNote.hidden = true;

  el.append(head, facts, note, list, refresh, lampTest, actionNote);

  let lampAvailable = false;
  let requestedLamp = null;

  function render(payload) {
    const dd = facts.querySelector("dd");
    if (payload?.available !== true) {
      lampAvailable = false;
      setOff(lampTest, true, "램프 상태 확인 필요");
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
    const lamp = (payload.devices || []).find((device) => device.id === "lamp");
    lampAvailable = Boolean(lamp && lamp.state !== "driver_missing");
    setOff(lampTest, ctx.role !== "administrator" || !lampAvailable,
      ctx.role !== "administrator" ? "관리자 권한 필요" : "램프 시험 불가");
    if (requestedLamp && payload.test?.request_id === requestedLamp) {
      actionNote.hidden = false;
      actionNote.textContent = payload.test.state === "done"
        ? `장치 시험 완료 (${requestedLamp}). Rosy Cam 영상에서 몸체를 확인하세요.`
        : payload.test.state === "failed"
          ? `램프 시험 실패 (${requestedLamp}): ${payload.test.detail || "장치 결과를 확인하세요."}`
          : `램프 시험 진행 중 (${requestedLamp}).`;
    }
    if (payload.stale === true) {
      note.textContent = "오래된 측정 결과입니다. 관리자가 다시 점검을 요청할 수 있습니다.";
    } else if (!(payload.devices || []).length) {
      note.textContent = "측정 결과에 등록된 장치가 없습니다.";
    } else {
      note.textContent = `${payload.devices.length}개 장치의 관측 결과입니다. 사람 확인 필요와 미측정 상태는 정상 판정이 아닙니다.`;
    }
  }

  function fail(error) {
    lampAvailable = false;
    setOff(lampTest, true, "램프 상태 확인 실패");
    facts.dataset.available = "false";
    // Keep the last readout visible, but never let an old response look current.
    facts.dataset.stale = "true";
    note.textContent = error.status === 403
      ? "장치 상태를 볼 권한이 없습니다."
      : `장치 상태를 가져오지 못했습니다: ${error.message}`;
  }

  let refreshing = false; let disposed = false;
  const onRefresh = async () => {
    if (disposed || refreshing || ctx.role !== "administrator") return;
    refreshing = true;
    refresh.disabled = true;
    actionNote.hidden = false;
    actionNote.textContent = "새 장치 점검을 요청하고 있습니다.";
    try {
      const reply = await ctx.api("/api/v1/host/hardware/refresh", {method: "POST"});
      if (disposed) return;
      actionNote.textContent = reply.accepted === true
        ? "점검 요청을 접수했습니다. 완료 여부는 마지막 측정 시각과 장치 상태에서 확인하세요."
        : (reply.detail || "최근 요청이 있어 점검을 다시 요청하지 않았습니다.");
    } catch (error) {
      if (disposed) return;
      actionNote.textContent = error.status === 403
        ? "장치 점검을 요청할 권한이 없습니다."
        : `장치 점검 요청 실패: ${error.message}`;
    } finally {
      refreshing = false;
      if (!disposed) setOff(refresh, ctx.role !== "administrator", "관리자 권한 필요");
    }
  };
  refresh.addEventListener("click", onRefresh);

  const onLampTest = async () => {
    if (disposed || !lampAvailable || ctx.role !== "administrator" || lampTest.disabled) return;
    setOff(lampTest, true, "시험 요청 중");
    actionNote.hidden = false;
    actionNote.textContent = "램프 자가 시험을 요청하고 있습니다.";
    try {
      const reply = await ctx.api("/api/v1/host/hardware/test", {
        method: "POST", body: JSON.stringify({device: "lamp"}),
      });
      if (disposed) return;
      requestedLamp = reply.accepted === true ? reply.request_id : null;
      actionNote.textContent = requestedLamp
        ? `램프 시험 요청 ${requestedLamp} 접수. 장치 완료와 Rosy Cam 영상을 확인하세요.`
        : (reply.detail || "램프 시험 요청이 접수되지 않았습니다.");
    } catch (error) {
      if (!disposed) actionNote.textContent = `램프 시험 요청 실패: ${error.message}`;
    } finally {
      if (!disposed) setOff(lampTest, ctx.role !== "administrator" || !lampAvailable,
        ctx.role !== "administrator" ? "관리자 권한 필요" : "램프 시험 불가");
    }
  };
  lampTest.addEventListener("click", onLampTest);

  const stop = ctx.store.poll("/api/v1/host/hardware", REFRESH_MS, render, fail);
  return () => {
    disposed = true;
    stop();
    refresh.removeEventListener("click", onRefresh);
    lampTest.removeEventListener("click", onLampTest);
  };
}
