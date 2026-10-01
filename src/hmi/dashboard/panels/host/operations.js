import { NETWORK_MODE_LABEL, enumLabel } from "/common/core_ui_logic.js";

// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
// Read-only host-agent views. An unreachable agent remains visibly unavailable.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 카드 상태는 원본 증거다. 무엇을 막았고 다음에 무엇을 할지는 작업 묶음 상태 한 곳이 말한다.
function unavailableLabel(code) {
  if (code === "HOST_AGENT_TIMEOUT") return "호스트 에이전트 응답 시간 초과";
  if (code === "HOST_AGENT_UNREADABLE_RESPONSE") return "호스트 에이전트 응답을 읽지 못함";
  if (code === "HOST_AGENT_UNAVAILABLE") return "호스트 에이전트 응답 없음";
  return "호스트 에이전트 상태 확인 불가";
}

// D-359 US-009 — 같은 에이전트 상태가 모든 작업을 막으면 원인·다음 단계는 묶음 상태 하나에만
// 있고, 버튼은 짧은 "위 사유"를 aria-describedby로 그 상태에 잇는다.
const SEE_ABOVE = "위 사유";
function agentBlock(wrap, work) {
  if (wrap.dataset.forbidden === "true") return `권한이 없어 ${work} 상태를 읽지 못해 작업을 막았습니다. 관리자 권한을 확인하세요.`;
  return wrap.dataset.evidence === "delayed"
    ? `호스트 에이전트 원본 조회가 지연되어 ${work} 작업을 막았습니다. 새 조회를 기다리세요.`
    : `호스트 에이전트에 연결할 수 없어 ${work} 작업을 막았습니다. 장치 전원과 서비스를 확인하세요.`;
}
let noteSerial = 0;
function pointAt(button, note, on) {
  const ids = (button.getAttribute("aria-describedby") || "").split(/\s+/).filter((id) => id && id !== note.id);
  if (on) ids.unshift(note.id);
  if (ids.length) button.setAttribute("aria-describedby", ids.join(" "));
  else button.removeAttribute("aria-describedby");
}

function card(title, path, interval, ctx, describe, summarize) {
  const wrap = el("section", "ui-readback");
  wrap.append(el("h3", "", title));
  const headline = el("p", "host-card-headline", "원본 상태 확인 중");
  const body = el("dl", "ui-readout");
  const status = el("ui-status", "", "상태를 불러오는 중입니다.");
  status.setAttribute("state", "pending");
  const readout = el("details", "surface-disclosure host-card-readout");
  readout.append(el("summary", "", `${title} 전체 상태 보기`), body);
  const detail = el("details", "surface-disclosure");
  detail.append(el("summary", "", "응답 세부 정보"));
  const detailText = el("p", "surface-message");
  detail.append(detailText);
  const recovery = el("details", "surface-disclosure");
  recovery.append(el("summary", "", "복구 안내"));
  const recoveryText = el("p", "surface-message");
  recovery.append(recoveryText);
  detail.hidden = true;
  recovery.hidden = true;
  wrap.append(headline, status, readout, detail, recovery);
  let currentData = {};
  let onUpdate = () => {};
  function clearReadout() {
    currentData = {};
    headline.textContent = "현재 값을 확인할 수 없습니다.";
    body.replaceChildren(el("dt", "", "상태"), el("dd", "", "확인할 수 없음"));
  }
  const stop = ctx.store.poll(path, interval, (payload) => {
    body.replaceChildren();
    delete wrap.dataset.forbidden;
    const commissioning = path === "/api/v1/host/commissioning";
    const evidence = commissioning ? null : payload?.evidence?.evidence || "unavailable";
    if (!commissioning) wrap.dataset.evidence = evidence;
    if (!commissioning && (payload?.available !== true || !["fresh", "delayed"].includes(evidence))) {
      clearReadout();
      status.textContent = evidence === "disconnected"
        ? `연결 끊김 · ${unavailableLabel(payload?.code)}`
        : `정보 없음 · ${payload?.evidence?.reason || unavailableLabel(payload?.code)}`;
      status.setAttribute("state", evidence === "disconnected" ? "error" : "unavailable");
      detailText.textContent = payload?.detail || "";
      detail.hidden = !payload?.detail;
      recoveryText.textContent = payload?.recovery || "";
      recovery.hidden = !payload?.recovery;
      wrap.dataset.available = "false";
      onUpdate();
      return;
    }
    wrap.dataset.available = commissioning || (evidence === "fresh" && payload.ok === true) ? "true" : "false";
    const data = commissioning ? payload : (payload.data || {});
    currentData = data;
    headline.textContent = `${commissioning ? "CORE 보고값" : "마지막 조회값"} · ${summarize(data)}`;
    detailText.textContent = payload?.detail || "";
    detail.hidden = !payload?.detail;
    recoveryText.textContent = payload?.recovery || "";
    recovery.hidden = !payload?.recovery;
    for (const [label, value] of describe(data)) {
      body.append(el("dt", "", label), el("dd", "", value == null || value === "" ? "—" : String(value)));
    }
    status.textContent = evidence === "delayed"
      ? payload.evidence.age_s == null ? "지연 · 원본 조회 시각 정보 없음. 새 조회를 기다리세요."
        : `지연 · 호스트 에이전트 원본 조회 ${payload.evidence.age_s}초 전. 새 조회를 기다리세요.`
      : payload.ok === false ? "호스트 에이전트가 확인이 필요한 상태를 보고했습니다."
      : commissioning ? "CORE 커미셔닝 상태를 확인했습니다." : "호스트 에이전트 상태를 확인했습니다.";
    status.setAttribute("state", evidence === "delayed" || payload.ok === false ? "warning" : "ready");
    onUpdate();
  }, (error) => {
    clearReadout();
    wrap.dataset.available = "false";
    wrap.dataset.evidence = "unavailable";
    wrap.dataset.forbidden = String(error.status === 403);
    detailText.textContent = "";
    detail.hidden = true;
    recoveryText.textContent = "";
    recovery.hidden = true;
    status.textContent = error.status === 403 ? "이 상태를 볼 권한이 없습니다. 관리자 권한을 확인하세요."
      : `상태를 가져오지 못했습니다: ${error.message}. 다음 조회를 기다리거나 호스트 에이전트 연결을 확인하세요.`;
    status.setAttribute("state", error.status === 403 ? "forbidden" : "error");
    onUpdate();
  });
  return {wrap, readout, stop, get data() { return currentData; }, onUpdate(callback) { onUpdate = callback; }};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "네트워크 및 장치 운영 상태");
  const network = card("네트워크", "/api/v1/host/network", 10_000, ctx, (data) => [["모드", data.mode == null ? null : enumLabel(NETWORK_MODE_LABEL, data.mode)], ["SSID", data.ssid], ["액세스 포인트", data.ap_active == null ? null : data.ap_active ? "켜짐" : "꺼짐"], ["IPv4", data.ipv4], ["기본 경로", data.default_route], ["DNS", (data.dns || []).join(", ")], ["인터넷", data.internet == null ? null : data.internet ? "도달" : "도달 안 됨"], ["단말 접근", data.peer_reachable == null ? null : data.peer_reachable ? "가능" : "확인 필요"]],
    (data) => `${enumLabel(NETWORK_MODE_LABEL, data.mode, "모드 미확인")} · ${data.ssid || "SSID 없음"}`);
  const release = card("릴리스", "/api/v1/host/release", 15_000, ctx, (data) => [["상태", data.state], ["현재 버전", data.current], ["이전 버전", data.previous], ["대기 버전", data.staged], ["마지막 실패", data.last_failure], ["리비전", data.git_revision], ["설정/데이터 스키마", data.config_schema == null ? null : `${data.config_schema} / ${data.data_schema}`]],
    (data) => `${data.state || "상태 미확인"} · 현재 ${data.current || "버전 미확인"} · 이전 ${data.previous || "없음"}`);
  const commissioning = card("커미셔닝", "/api/v1/host/commissioning", 15_000, ctx, (data) => [["실행 모드", data.runtime_mode], ["동작 차단 사유", data.motion_reason], ["모터", data.motor_hold ? "승인 대기" : "확인됨"], ["LiDAR", data.lidar_hold ? "승인 대기" : "확인됨"], ["배터리", data.battery_hold ? "승인 대기" : "확인됨"], ["IMU", data.imu_hold ? "승인 대기" : "확인됨"], ["SLAM", data.slam_hold ? "승인 대기" : "확인됨"], ["Fleet", data.fleet_hold ? "승인 대기" : "확인됨"], ["세부 정보", data.detail]],
    (data) => `${data.runtime_mode || "실행 모드 미확인"} · ${data.motion_reason || "동작 차단 사유 없음"}`);
  const cards = [network, release, commissioning];
  // 두 작업 묶음이 같은 에이전트 상태로 막히면 원인은 패널 위 한 줄에만 둔다.
  const groupNote = el("ui-status", "", ""); groupNote.setAttribute("state", "unavailable");
  groupNote.id = `host-agent-note-${++noteSerial}`;
  let syncGroup = () => {};

  const networkActions = el("div", "ui-readback");
  networkActions.append(el("h4", "", "네트워크 작업"));
  const modeActions = el("ui-actions", "surface-actions");
  const sta = el("ui-button", "", "사업장 Wi-Fi로 전환"); sta.setAttribute("kind", "quiet"); sta.type = "button";
  const relay = el("ui-button", "", "릴레이 AP 켜기"); relay.setAttribute("kind", "quiet"); relay.type = "button";
  modeActions.append(sta, relay); networkActions.append(modeActions);
  const applyForm = el("form", "ui-form");
  const profile = el("input", "ui-field"); profile.maxLength = 64; profile.autocomplete = "off"; profile.setAttribute("aria-label", "네트워크 프로파일 ID"); profile.placeholder = "프로파일 ID";
  const applyProfile = el("ui-button", "", "프로파일 적용"); applyProfile.setAttribute("kind", "primary"); applyProfile.type = "submit"; applyForm.append(profile, applyProfile); networkActions.append(applyForm);
  const connectForm = el("form", "ui-form");
  const ssid = el("input", "ui-field"); ssid.maxLength = 32; ssid.setAttribute("aria-label", "Wi-Fi SSID"); ssid.placeholder = "SSID";
  const field = el("input", "ui-field"); field.type = "password"; field.autocomplete = "new-password"; field.maxLength = 63; field.setAttribute("aria-label", "Wi-Fi 암호"); field.placeholder = "Wi-Fi 암호";
  const connect = el("ui-button", "", "Wi-Fi 연결"); connect.setAttribute("kind", "primary"); connect.type = "submit"; connectForm.append(ssid, field, connect); networkActions.append(connectForm);
  const networkNote = el("ui-status", "", "호스트 에이전트 상태 확인 전에는 네트워크 작업을 쓸 수 없습니다."); networkNote.setAttribute("state", "pending"); networkActions.append(networkNote);
  networkNote.id = `host-network-note-${++noteSerial}`;
  network.wrap.insertBefore(networkActions, network.readout);
  let networkHasResult = false;
  let networkPending = false;
  function networkEnabled(enabled) {
    const blocked = !enabled && !networkPending;
    for (const button of [sta, relay, applyProfile, connect]) {
      setOff(button, !enabled || networkPending, networkPending ? "" : SEE_ABOVE);
      pointAt(button, networkNote, blocked);
    }
    if (blocked) {
      networkHasResult = false;
      networkNote.textContent = agentBlock(network.wrap, "네트워크");
      networkNote.setAttribute("state", "unavailable");
    }
    networkNote.hidden = enabled && !networkHasResult && !networkPending;
    syncGroup();
  }
  network.onUpdate(() => networkEnabled(network.wrap.dataset.available === "true"));
  networkEnabled(network.wrap.dataset.available === "true");

  const releaseActions = el("ui-actions", "surface-actions");
  const rollback = el("ui-button", "", "이전 릴리스로 복귀"); rollback.setAttribute("kind", "quiet"); rollback.type = "button";
  const clearHold = el("ui-button", "", "복구 보류 해제"); clearHold.setAttribute("kind", "quiet"); clearHold.type = "button";
  rollback.disabled = clearHold.disabled = true; releaseActions.append(rollback, clearHold); release.wrap.insertBefore(releaseActions, release.readout);
  const releaseNote = el("ui-status", "", "호스트 에이전트 상태 확인 전에는 릴리스 작업을 쓸 수 없습니다."); releaseNote.setAttribute("state", "pending"); release.wrap.insertBefore(releaseNote, release.readout);
  releaseNote.id = `host-release-note-${++noteSerial}`;
  let releaseHasResult = false;
  let releasePending = false;
  function syncReleaseActions() {
    const held = release.data.state === "RECOVERY_HOLD";
    // 요청 중(releasePending)은 짧은 잠금이라 사유 없이 끈다.
    const agent = releasePending ? "" : release.wrap.dataset.available !== "true" ? SEE_ABOVE : "";
    setOff(rollback, releasePending || release.wrap.dataset.available !== "true" || !release.data.previous || held,
      agent || (releasePending ? "" : held ? "복구 보류 중" : "이전 릴리스 없음"));
    setOff(clearHold, releasePending || release.wrap.dataset.available !== "true" || !held,
      agent || (releasePending ? "" : "보류 없음"));
    for (const button of [rollback, clearHold]) pointAt(button, releaseNote, Boolean(agent));
    if (agent) {
      releaseHasResult = false;
      releaseNote.textContent = agentBlock(release.wrap, "릴리스");
      releaseNote.setAttribute("state", "unavailable");
    }
    releaseNote.hidden = release.wrap.dataset.available === "true" && !releaseHasResult && !releasePending;
    syncGroup();
  }
  syncGroup = () => {
    const blocked = (card, pending) => !pending && card.wrap.dataset.available !== "true"
      && card.wrap.dataset.forbidden !== "true"
      && ["disconnected", "unavailable", "delayed"].includes(card.wrap.dataset.evidence);
    const same = blocked(network, networkPending) && blocked(release, releasePending)
      && (network.wrap.dataset.evidence === "delayed") === (release.wrap.dataset.evidence === "delayed");
    // 묶음 상태는 있을 때만 문서에 있다 — 숨긴 채 남은 옛 문장이 첫 상태 줄로 읽히지 않게.
    if (same && !groupNote.isConnected) head.after(groupNote);
    if (!same) {
      groupNote.remove();
      // 묶음이 풀리면 각 작업 묶음이 제 사유를 되찾는다(숨김·연결을 그 묶음의 식대로).
      const netOff = network.wrap.dataset.available !== "true" && !networkPending;
      const relOff = release.wrap.dataset.available !== "true" && !releasePending;
      networkNote.hidden = !netOff && !networkHasResult && !networkPending;
      releaseNote.hidden = !relOff && !releaseHasResult && !releasePending;
      for (const button of [sta, relay, applyProfile, connect]) { pointAt(button, groupNote, false); pointAt(button, networkNote, netOff); }
      for (const button of [rollback, clearHold]) { pointAt(button, groupNote, false); pointAt(button, releaseNote, relOff); }
      return;
    }
    groupNote.textContent = agentBlock(network.wrap, "네트워크·릴리스");
    networkNote.hidden = true; releaseNote.hidden = true;
    for (const button of [sta, relay, applyProfile, connect]) { pointAt(button, networkNote, false); pointAt(button, groupNote, true); }
    for (const button of [rollback, clearHold]) { pointAt(button, releaseNote, false); pointAt(button, groupNote, true); }
  };
  release.onUpdate(syncReleaseActions);
  syncReleaseActions();

  async function postHost(button, path, body, confirmText, note, success) {
    const isNetwork = note === networkNote;
    if ((isNetwork ? networkPending : releasePending) || button.disabled || !window.confirm(confirmText)) return;
    if (isNetwork) networkPending = true;
    else releasePending = true;
    if (isNetwork) networkEnabled(network.wrap.dataset.available === "true");
    else syncReleaseActions();
    note.hidden = false;
    note.textContent = "요청 결과를 기다리는 중입니다.";
    note.setAttribute("state", "pending");
    if (note === networkNote) networkHasResult = true;
    if (note === releaseNote) releaseHasResult = true;
    try {
      const result = await ctx.api(path, {method: "POST", body: JSON.stringify({...body, confirmed: true, idempotency_key: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`})});
      note.textContent = result.available === false ? (result.detail || "호스트 에이전트에 연결할 수 없습니다.")
        : result.ok === false ? (result.detail || "요청이 거부되었습니다.") : success;
      note.setAttribute("state", result.available === false ? "unavailable" : result.ok === false ? "error" : "ready");
    } catch (error) { note.textContent = `요청 실패: ${error.message}`; note.setAttribute("state", "error"); }
    finally {
      if (isNetwork) { networkPending = false; networkEnabled(network.wrap.dataset.available === "true"); }
      else { releasePending = false; syncReleaseActions(); }
    }
  }
  sta.addEventListener("click", () => postHost(sta, "/api/v1/host/network/mode", {mode: "SITE_STA"}, "사업장 Wi-Fi로 전환할까요? 연결이 잠시 끊길 수 있습니다.", networkNote, "네트워크 모드 전환을 요청했습니다."));
  relay.addEventListener("click", () => postHost(relay, "/api/v1/host/network/mode", {mode: "RELAY_AP_STA"}, "릴레이 AP를 켤까요? 연결이 잠시 끊길 수 있습니다.", networkNote, "릴레이 AP 전환을 요청했습니다."));
  applyForm.addEventListener("submit", (event) => {
    event.preventDefault(); const id = profile.value.trim(); if (!id) { networkHasResult = true; networkNote.hidden = false; networkNote.textContent = "프로파일 ID를 입력하세요."; networkNote.setAttribute("state", "error"); return; }
    postHost(applyProfile, "/api/v1/host/network/apply", {profile_id: id}, `${id} 네트워크 프로파일을 적용할까요? 연결이 잠시 끊길 수 있습니다.`, networkNote, "프로파일 적용을 요청했습니다.");
  });
  connectForm.addEventListener("submit", (event) => {
    event.preventDefault(); const name = ssid.value.trim();
    if (!name || field.value.length < 8 || field.value.length > 63) { networkHasResult = true; networkNote.hidden = false; networkNote.textContent = "SSID와 8~63자 Wi-Fi 암호를 입력하세요."; networkNote.setAttribute("state", "error"); return; }
    postHost(connect, "/api/v1/host/network/connect", {ssid: name, psk: field.value}, `${name} Wi-Fi에 연결할까요? 연결이 잠시 끊길 수 있습니다.`, networkNote, "Wi-Fi 연결을 요청했습니다.").finally(() => { field.value = ""; });
  });
  rollback.addEventListener("click", () => postHost(rollback, "/api/v1/host/release/rollback", {}, "이전 릴리스로 복귀할까요? 현재 실행이 중단될 수 있습니다.", releaseNote, "롤백을 요청했습니다."));
  clearHold.addEventListener("click", () => postHost(clearHold, "/api/v1/host/release/clear-hold", {}, "복구 보류를 해제할까요?", releaseNote, "복구 보류 해제를 요청했습니다."));

  root.append(head, ...cards.map(({wrap}) => wrap));
  syncGroup();
  return () => cards.forEach(({stop}) => stop());
}
