// Read-only host-agent views. An unreachable agent remains visibly unavailable.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function unavailableLabel(code) {
  if (code === "HOST_AGENT_TIMEOUT") return "Host Agent 응답 시간이 초과되었습니다.";
  if (code === "HOST_AGENT_UNREADABLE_RESPONSE") return "Host Agent 응답을 읽지 못했습니다.";
  if (code === "HOST_AGENT_UNAVAILABLE") return "Host Agent에 연결할 수 없습니다.";
  return "Host Agent 상태를 확인할 수 없습니다.";
}

function card(title, path, interval, ctx, describe) {
  const wrap = el("section", "ui-readback");
  wrap.append(el("h3", "", title));
  const body = el("dl", "ui-readout");
  const status = el("ui-status", "", "상태를 불러오는 중입니다.");
  status.setAttribute("state", "pending");
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
  wrap.append(body, status, detail, recovery);
  let currentData = {};
  let onUpdate = () => {};
  const stop = ctx.store.poll(path, interval, (payload) => {
    body.replaceChildren();
    const commissioning = path === "/api/v1/host/commissioning";
    if (!commissioning && payload?.available !== true) {
      body.append(el("dt", "", "상태"), el("dd", "", "확인할 수 없음"));
      status.textContent = unavailableLabel(payload?.code);
      status.setAttribute("state", "unavailable");
      detailText.textContent = payload?.detail || "";
      detail.hidden = !payload?.detail;
      recoveryText.textContent = payload?.recovery || "";
      recovery.hidden = !payload?.recovery;
      wrap.dataset.available = "false";
      onUpdate();
      return;
    }
    wrap.dataset.available = "true";
    const data = commissioning ? payload : (payload.data || {});
    currentData = data;
    detailText.textContent = payload?.detail || "";
    detail.hidden = !payload?.detail;
    recoveryText.textContent = payload?.recovery || "";
    recovery.hidden = !payload?.recovery;
    for (const [label, value] of describe(data)) {
      body.append(el("dt", "", label), el("dd", "", value == null || value === "" ? "—" : String(value)));
    }
    status.textContent = payload.ok === false
      ? "Host Agent가 확인이 필요한 상태를 보고했습니다."
      : "Host Agent 상태를 확인했습니다.";
    status.setAttribute("state", payload.ok === false ? "warning" : "ready");
    onUpdate();
  }, (error) => {
    currentData = {};
    wrap.dataset.available = "false";
    status.textContent = error.status === 403 ? "이 상태를 볼 권한이 없습니다." : `상태를 가져오지 못했습니다: ${error.message}`;
    status.setAttribute("state", error.status === 403 ? "forbidden" : "error");
    onUpdate();
  });
  return {wrap, stop, get data() { return currentData; }, onUpdate(callback) { onUpdate = callback; }};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "네트워크 및 장치 운영 상태");
  const network = card("네트워크", "/api/v1/host/network", 10_000, ctx, (data) => [["모드", data.mode], ["SSID", data.ssid], ["액세스 포인트", data.ap_active == null ? null : data.ap_active ? "켜짐" : "꺼짐"], ["IPv4", data.ipv4], ["기본 경로", data.default_route], ["DNS", (data.dns || []).join(", ")], ["인터넷", data.internet == null ? null : data.internet ? "도달" : "도달 안 됨"], ["단말 접근", data.peer_reachable == null ? null : data.peer_reachable ? "가능" : "확인 필요"]]);
  const release = card("릴리스", "/api/v1/host/release", 15_000, ctx, (data) => [["상태", data.state], ["현재 버전", data.current], ["이전 버전", data.previous], ["대기 버전", data.staged], ["마지막 실패", data.last_failure], ["리비전", data.git_revision], ["설정/데이터 스키마", data.config_schema == null ? null : `${data.config_schema} / ${data.data_schema}`]]);
  const commissioning = card("커미셔닝", "/api/v1/host/commissioning", 15_000, ctx, (data) => [["실행 모드", data.runtime_mode], ["동작 차단 사유", data.motion_reason], ["모터", data.motor_hold ? "승인 대기" : "확인됨"], ["LiDAR", data.lidar_hold ? "승인 대기" : "확인됨"], ["배터리", data.battery_hold ? "승인 대기" : "확인됨"], ["IMU", data.imu_hold ? "승인 대기" : "확인됨"], ["SLAM", data.slam_hold ? "승인 대기" : "확인됨"], ["Fleet", data.fleet_hold ? "승인 대기" : "확인됨"], ["세부 정보", data.detail]]);
  const cards = [network, release, commissioning];

  const networkActions = el("div", "ui-readback");
  networkActions.append(el("h4", "", "네트워크 작업"));
  const modeActions = el("ui-actions", "surface-actions");
  const sta = el("ui-button", "", "사업장 Wi-Fi로 전환"); sta.setAttribute("kind", "quiet"); sta.type = "button";
  const relay = el("ui-button", "", "릴레이 AP 켜기"); relay.setAttribute("kind", "quiet"); relay.type = "button";
  modeActions.append(sta, relay); networkActions.append(modeActions);
  const applyForm = el("form", "ui-form");
  const profile = el("input"); profile.maxLength = 64; profile.autocomplete = "off"; profile.setAttribute("aria-label", "네트워크 프로파일 ID"); profile.placeholder = "프로파일 ID";
  const applyProfile = el("ui-button", "", "프로파일 적용"); applyProfile.setAttribute("kind", "primary"); applyProfile.type = "submit"; applyForm.append(profile, applyProfile); networkActions.append(applyForm);
  const connectForm = el("form", "ui-form");
  const ssid = el("input"); ssid.maxLength = 32; ssid.setAttribute("aria-label", "Wi-Fi SSID"); ssid.placeholder = "SSID";
  const field = el("input"); field.type = "password"; field.autocomplete = "new-password"; field.maxLength = 63; field.setAttribute("aria-label", "Wi-Fi 암호"); field.placeholder = "Wi-Fi 암호";
  const connect = el("ui-button", "", "Wi-Fi 연결"); connect.setAttribute("kind", "primary"); connect.type = "submit"; connectForm.append(ssid, field, connect); networkActions.append(connectForm);
  const networkNote = el("ui-status", "", "Host Agent 상태 확인 전에는 네트워크 작업을 사용할 수 없습니다."); networkNote.setAttribute("state", "pending"); networkActions.append(networkNote);
  network.wrap.append(networkActions);
  function networkEnabled(enabled) {
    for (const button of [sta, relay, applyProfile, connect]) button.disabled = !enabled;
    networkNote.hidden = enabled;
  }
  network.onUpdate(() => networkEnabled(network.wrap.dataset.available === "true"));
  networkEnabled(network.wrap.dataset.available === "true");

  const releaseActions = el("ui-actions", "surface-actions");
  const rollback = el("ui-button", "", "이전 릴리스로 복귀"); rollback.setAttribute("kind", "quiet"); rollback.type = "button";
  const clearHold = el("ui-button", "", "복구 보류 해제"); clearHold.setAttribute("kind", "quiet"); clearHold.type = "button";
  rollback.disabled = clearHold.disabled = true; releaseActions.append(rollback, clearHold); release.wrap.append(releaseActions);
  const releaseNote = el("ui-status", "", "Host Agent 상태 확인 전에는 릴리스 작업을 사용할 수 없습니다."); releaseNote.setAttribute("state", "pending"); release.wrap.append(releaseNote);
  function syncReleaseActions() {
    const held = release.data.state === "RECOVERY_HOLD";
    rollback.disabled = release.wrap.dataset.available !== "true" || !release.data.previous || held;
    clearHold.disabled = release.wrap.dataset.available !== "true" || !held;
    releaseNote.hidden = release.wrap.dataset.available === "true";
  }
  release.onUpdate(syncReleaseActions);
  syncReleaseActions();

  async function postHost(button, path, body, confirmText, note, success) {
    if (button.disabled || !window.confirm(confirmText)) return;
    button.disabled = true;
    try {
      const result = await ctx.api(path, {method: "POST", body: JSON.stringify({...body, confirmed: true, idempotency_key: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`})});
      note.textContent = result.available === false ? (result.detail || "Host Agent에 연결할 수 없습니다.")
        : result.ok === false ? (result.detail || "요청이 거부되었습니다.") : success;
    } catch (error) { note.textContent = `요청 실패: ${error.message}`; }
    finally {
      if ([sta, relay, applyProfile, connect].includes(button)) networkEnabled(network.wrap.dataset.available === "true");
      else syncReleaseActions();
    }
  }
  sta.addEventListener("click", () => postHost(sta, "/api/v1/host/network/mode", {mode: "SITE_STA"}, "사업장 Wi-Fi로 전환할까요? 연결이 잠시 끊길 수 있습니다.", networkNote, "네트워크 모드 전환을 요청했습니다."));
  relay.addEventListener("click", () => postHost(relay, "/api/v1/host/network/mode", {mode: "RELAY_AP_STA"}, "릴레이 AP를 켤까요? 연결이 잠시 끊길 수 있습니다.", networkNote, "릴레이 AP 전환을 요청했습니다."));
  applyForm.addEventListener("submit", (event) => {
    event.preventDefault(); const id = profile.value.trim(); if (!id) { networkNote.textContent = "프로파일 ID를 입력하세요."; return; }
    postHost(applyProfile, "/api/v1/host/network/apply", {profile_id: id}, `${id} 네트워크 프로파일을 적용할까요? 연결이 잠시 끊길 수 있습니다.`, networkNote, "프로파일 적용을 요청했습니다.");
  });
  connectForm.addEventListener("submit", (event) => {
    event.preventDefault(); const name = ssid.value.trim();
    if (!name || field.value.length < 8 || field.value.length > 63) { networkNote.textContent = "SSID와 8~63자 Wi-Fi 암호를 입력하세요."; return; }
    postHost(connect, "/api/v1/host/network/connect", {ssid: name, psk: field.value}, `${name} Wi-Fi에 연결할까요? 연결이 잠시 끊길 수 있습니다.`, networkNote, "Wi-Fi 연결을 요청했습니다.").finally(() => { field.value = ""; });
  });
  rollback.addEventListener("click", () => postHost(rollback, "/api/v1/host/release/rollback", {}, "이전 릴리스로 복귀할까요? 현재 실행이 중단될 수 있습니다.", releaseNote, "롤백을 요청했습니다."));
  clearHold.addEventListener("click", () => postHost(clearHold, "/api/v1/host/release/clear-hold", {}, "복구 보류를 해제할까요?", releaseNote, "복구 보류 해제를 요청했습니다."));

  root.append(head, ...cards.map(({wrap}) => wrap));
  return () => cards.forEach(({stop}) => stop());
}
