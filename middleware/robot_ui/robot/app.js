import { restoreAccount, canOperate, PAIRED_SOURCES, api, apiMaybe, authHeaders, connectionOffer, developmentSession, expiryLabel, forgetToken, isAdmin, logout, normalizeLoginCode, pairWithCode, rememberToken, session, setConnection, sourceLabel } from "./client.js";
import { createReceiverApprovals } from "./peer-approval.js";
import { createFieldMap } from "./map.js";
import { createHostCards } from "./host-cards.js";
import { createVisionPreview } from "./vision.js";
import { createStatusSummary } from "./status-summary.js";
import { completeDashboardAuthentication, dashboardSurfaceBridge } from "./surface-navigation.js";
import { HeadlessState, MODE_LABEL, NAVIGATION_LABEL, NETWORK_MODE_LABEL, enumLabel, operatorModeLabel } from "/common/core_ui_logic.js";
import { bindFormSave, elements, markRequested, metricNumber, number, percent, setEnabled, setFieldMessage, setText } from "./dom.js";
import { fillSafetyForm, initSettings, refreshDocks, refreshTokens, refreshWaypoints, renderDockingStatus, renderDocks, renderTokens, renderWaypoints } from "./settings.js";
import { TELEMETRY_CHANNELS, lineFollow, lineFollowStartReady, renderCapabilityPanels, renderEvents, renderFormationHero, renderInventory, renderLineFollow, renderRobotInfo, renderRuntime, initTelemetry, renderSafetyHero, renderTrafficPolicy, renderTrafficStatus, renderTriage, showView, updateLineFollowButtons } from "./telemetry.js";
import { startTeleop, stopTeleop, teleopActive, teleopEligible, updateTeleopControls } from "./teleop.js";
import { createStateSocket } from "./state-socket.js";
import { confirmIrreversible } from "/common/ui.js";
import { createPageScope } from "/common/scope.js";
export { TELEMETRY_CHANNELS } from "./telemetry.js";

const pageScope = createPageScope();
let authLifetime = new AbortController(), commandOwner = null;
function authTicket() {
  const held = authLifetime, identity = session.authKey, page = pageScope.capture();
  return {signal: AbortSignal.any([held.signal, page.signal]), current: () => !held.signal.aborted && held === authLifetime && identity === session.authKey && page.current()};
}
function updateLegacyLineControls() {
  updateLineFollowButtons();
  const off = document.querySelector('[data-line-mode="OFF"]');
  if (off) { off.disabled = !session.authenticated || !canOperate(); if (off.disabled) off.setAttribute("reason", "운용자 권한 필요"); else off.removeAttribute("reason"); }
}
function invalidateAuth() {
  receiverApprovals.clear();
  authLifetime.abort(); authLifetime = new AbortController(); commandOwner = null;
  stateSocket.stop(); clearInterval(session.refreshTimer); session.refreshTimer = null;
  clearTimeout(codeRetryTimer); clearTimeout(actionMessageTimer); elements["code-submit"].disabled = false;
  session.modeChangePending = lineFollow.pending = false; updateModeButtons(); updateLegacyLineControls();
}
async function runConfirmed(message, opener, eligible, run, fail, pending = () => {}, kind = "", action = "요청 전송") {
  if (commandOwner || !session.authenticated || !eligible()) return;
  const owner = authTicket(), role = session.role, active = () => commandOwner === owner && owner.current() && role === session.role;
  owner.kind = kind; commandOwner = owner;
  let started = false;
  const clearPending = () => { if (started && commandOwner === owner) { started = false; pending(false); } };
  owner.signal.addEventListener("abort", clearPending, {once: true});
  try {
    if (!await confirmIrreversible({message, action, opener, signal: owner.signal}) || !active() || !eligible()) return;
    started = true; pending(true); await run(active, {...owner, current: active});
  } catch (error) { if (active()) fail(error); }
  finally { clearPending(); owner.signal.removeEventListener("abort", clearPending); if (commandOwner === owner) commandOwner = null; }
}
const goalPoseReady = () => session.robotState && new HeadlessState(session.robotState).isFresh("pose")
  && (session.robotState.localization == null || (session.robotState.localization.state === "LOCALIZED" && session.robotState.localization.pose_frame === "map"));
const fieldMap = createFieldMap({
  canvas: elements["map-canvas"], empty: elements["map-empty"], status: elements["map-status"],
  layerRoot: document.getElementById("field-map-panel"), api, apiMaybe, captureLifetime: authTicket, onlyActivePath: true,
  getPose: () => session.robotState?.pose,
  getDisplayPose: () => new HeadlessState(session.robotState).isFresh("pose") && session.robotState?.localization?.state === "LOCALIZED" && session.robotState.localization.pose_frame === "map" ? session.robotState.pose : null,
  getCurrentMapId: () => session.robotState?.map_id,
  getNavigation: () => session.robotState?.mode !== "SAFE_STOP" && new HeadlessState(session.robotState).isFresh("navigation") && goalPoseReady() ? session.robotState.navigation : null,
  getMapSources: () => session.capabilities?.runtime?.maps,
  canGoal: (mode) => session.capabilities?.navigation?.goal_navigation === true && (mode !== "goal" || (session.robotState?.mode !== "SAFE_STOP" && goalPoseReady())),
  goalReason: (mode) => session.capabilities?.navigation?.goal_navigation !== true ? "내비게이션을 쓸 수 없음"
    : mode === "goal" && session.robotState?.mode === "SAFE_STOP" ? "안전 정지 중 주행 목표 불가" : mode === "goal" && !goalPoseReady() ? "위치 추정 확인 후 가능" : "",
  setAction: (text) => announceAction(text),
});
const visionPreview = createVisionPreview({ elements, setText, api, authHeaders, hasToken: () => !!session.authenticated, isHidden: () => document.hidden, lastGoal: null });
const stopVisionPreview = (message) => visionPreview.stop(message);
const startVisionPreview = () => visionPreview.start();
const streamLabel = (state) => ["pose", "velocity"].map((name) => state?.evidence?.[name]?.evidence).some((value) => value && value !== "fresh") ? "통로만 연결" : "값 수신 중";
function renderRobotState(state) {
  session.robotState = state; elements["hitl-escalation"].hidden = state.hitl_requested !== true;
  setText("robot-mode", operatorModeLabel(state.mode)); renderCalibrationChip(state.activity);
  renderFormationHero(state.swarm);
  setText("state-sequence", `SEQ ${state.seq ?? "—"}`);
  setText("pose-x", number(state.pose?.x, 3), "—", state.evidence?.pose);
  setText("pose-y", number(state.pose?.y, 3), "—", state.evidence?.pose);
  setText("pose-yaw", number(state.pose?.yaw, 3), "—", state.evidence?.pose);
  setText("velocity-linear", number(state.velocity?.linear, 3), "—", state.evidence?.velocity);
  setText("velocity-angular", number(state.velocity?.angular, 3), "—", state.evidence?.velocity);
  setText("battery-value", percent(state.battery?.percent), "—", state.evidence?.battery);
  document.querySelectorAll(".telemetry-grid strong").forEach((el) => { if (el.textContent === "—") el.setAttribute("data-pending", ""); else el.removeAttribute("data-pending"); });
  setText("battery-voltage", metricNumber(state.battery?.voltage) === null ? "voltage —" : `${number(state.battery.voltage, 2)} V`, "—", state.evidence?.battery);
  setText("navigation-state", enumLabel(NAVIGATION_LABEL, state.navigation), "—", state.evidence?.navigation);
  const navGoal = elements["navigation-goal"];
  if (navGoal) {
    const active = ["PLANNING", "NAVIGATING"].includes(state.navigation) && new HeadlessState(state).isFresh("navigation") && goalPoseReady() && state.mode !== "SAFE_STOP";
    if (active && session.lastGoal) navGoal.textContent = `목표 (${session.lastGoal.x.toFixed(1)}, ${session.lastGoal.y.toFixed(1)})`;
    else { navGoal.textContent = ""; if (!active && session.lastGoal) { session.lastGoal = null; window.dispatchEvent(new CustomEvent("rosy:goal-clear")); } }
  }
  setText("map-id", `map ${state.map_id || "—"}`);
  setText("state-age", state.timestamp ? new Date(state.timestamp).toLocaleTimeString("ko-KR") : "—");
  setText("hero-message", state.online === false ? "로봇이 오프라인 상태를 보고했습니다." : "로봇 런타임과 상태 스트림이 연결되었습니다.");
  document.querySelectorAll("ui-button[data-mode]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode)));
  renderLineFollow(state.line_follow); updateLegacyLineControls(); renderTrafficStatus(state.traffic_policy); renderSafetyHero();
  setConnection("online", streamLabel(state)); setText("last-sync", `마지막 동기화 ${new Date().toLocaleTimeString("ko-KR")}`);
  renderTriage();
  if (teleopActive() && !teleopEligible()) stopTeleop("운전 조건이 변경되어 정지했습니다.");
  updateTeleopControls(); fieldMap.setPose();
}
function renderCalibrationChip(activity) {
  const chip = elements["calibration-chip"];
  if (!chip) return;
  const active = activity?.kind === "CALIBRATING", owner = activity?.owner;
  chip.hidden = !active; chip.textContent = active ? `보정 중 — ${activity.label || "보정"}` : "";
  chip.title = active ? `보정 주체: ${owner?.label || owner?.role || owner?.id || "알 수 없음"}` : "";
}
function renderSafety(safety) {
  session.robotState = { ...(session.robotState || {}), safety: { ...(session.robotState?.safety || {}), estop: Boolean(safety.estop) } };
  session.safetySource = safety.source || null;
  renderSafetyHero(); renderTriage(); fillSafetyForm(safety); updateTeleopControls(); updateLegacyLineControls();
}
function renderCapabilities(capabilities) {
  renderCapabilityPanels(capabilities); fieldMap.setPose(); updateModeButtons(); updateTeleopControls(); updateLegacyLineControls();
}
function updateModeButtons() {
  const navigationAvailable = session.capabilities?.navigation?.goal_navigation === true;
  document.querySelectorAll("ui-button[data-mode]").forEach((button) => {
    const unsupported = button.dataset.mode === "NAVIGATION" && !navigationAvailable;
    button.disabled = session.modeChangePending || unsupported;
    const reason = unsupported ? "이 로봇에서는 내비게이션을 쓸 수 없습니다" : session.modeChangePending ? "모드 변경을 처리하는 중입니다" : "";
    if (reason) button.setAttribute("reason", reason); else button.removeAttribute("reason");
  });
}
const hostCards = createHostCards({ elements, setText, setEnabled, isAdmin, onCommissioningRendered: (reason) => { session.motionReason = reason; updateTeleopControls(); } });
const { renderHostNetwork, renderHostRelease, renderCommissioning, renderHardware } = hostCards;
const statusSummary = createStatusSummary({
  elements,
  onOpenDevice: (deviceId) => {
    showView("inspect");
    const target = (deviceId ? elements["hardware-list"]?.querySelector(`[data-device="${CSS.escape(deviceId)}"]`) : null) || elements["hardware-card"];
    target?.scrollIntoView({ block: "center" }); if (target) { target.tabIndex = -1; target.focus({ preventScroll: true }); }
  },
});
function updateAdminControls() {
  for (const id of ["limits-save", "dock-register", "identity-save", "token-add"]) setEnabled(id, isAdmin(), "관리자 권한 필요");
  setEnabled("hardware-refresh", isAdmin(), "관리자 권한 필요");
  const networkOn = isAdmin() && document.getElementById("network-card")?.dataset.available === "true", networkReason = !isAdmin() ? "관리자 권한 필요" : "호스트 에이전트 없음";
  for (const id of ["network-apply", "network-ap-off", "network-ap-on", "network-connect"]) setEnabled(id, networkOn, networkReason);
}
async function detectRole(owner = authTicket()) {
  if (!owner.current()) return;
  session.role = ""; session.identity = null;
  try {
    const me = await api("/api/v1/auth/whoami", {signal: owner.signal});
    if (!owner.current()) return;
    session.identity = me || null; session.role = me?.role || "";
  } catch (_error) { if (!owner.current()) return; session.role = ""; }
  renderIdentity(); updateAdminControls();
  await refreshSurfaceBridge(owner);
}
async function refreshSurfaceBridge(owner = authTicket()) {
  if (!owner.current()) return;
  const nav = elements["surface-bridge"];
  if (!nav) return;
  if (!session.identity) { dashboardSurfaceBridge(nav, []); return; }
  try {
    const manifest = await api("/api/v1/ui/surfaces/console", {signal: owner.signal});
    if (!owner.current()) return;
    dashboardSurfaceBridge(nav, manifest?.surfaces);
  } catch (_error) { if (owner.current()) dashboardSurfaceBridge(nav, []); }
}
function renderIdentity() {
  const me = session.identity, badge = elements["whoami-badge"], button = elements["logout"];
  if (!me) {
    if (badge) badge.hidden = true;
    if (button) button.hidden = true;
    dashboardSurfaceBridge(elements["surface-bridge"], []);
    return;
  }
  setText("whoami-role", me.role || "—");
  const who = me.label || me.id || "";
  setText("whoami-detail", [who, sourceLabel(me.source), expiryLabel(me.expires_at)].filter(Boolean).join(" · "));
  if (badge) { badge.hidden = false; badge.title = `${me.role} · ${who} · ${sourceLabel(me.source)} · ${expiryLabel(me.expires_at)}`; }
  if (button) { button.hidden = false; button.textContent = PAIRED_SOURCES.has(me.source) ? "로그아웃" : "이 브라우저에서 잊기"; }
}
const receiverApprovals = createReceiverApprovals({root: document.getElementById("peer-approval-panel"), api, isAdmin, captureLifetime: authTicket, runConfirmed});
async function refreshSlowData(owner = authTicket()) {
  receiverApprovals.refresh(owner);
  if (!owner.current()) return;
  const required = [[api("/api/v1/system/runtime"), renderRuntime], [api("/api/v1/system/info"), renderRobotInfo], [api("/api/v1/system/capabilities"), renderCapabilities], [api("/api/v1/system/inventory"), renderInventory], [api("/api/v1/safety/state"), renderSafety], [api("/api/v1/events?limit=10"), renderEvents], [api("/api/v1/traffic"), renderTrafficPolicy], [api("/api/v1/host/network"), renderHostNetwork], [api("/api/v1/host/release"), renderHostRelease], [api("/api/v1/host/commissioning"), renderCommissioning]];
  const optional = [[api("/api/v1/waypoints"), renderWaypoints], [api("/api/v1/docking/status"), renderDockingStatus], [api("/api/v1/host/hardware"), renderHardware], [api("/api/v1/host/status-summary"), statusSummary.render], [api("/api/v1/docking/docks"), renderDocks], [isAdmin() ? api("/api/v1/system/tokens") : Promise.resolve({tokens: []}), renderTokens]];
  const read = entries => Promise.allSettled(entries.map(async ([promise, render]) => { const value = await promise; if (owner.current()) render(value); }));
  const [requiredResults] = await Promise.all([read(required), read(optional)]);
  if (!owner.current()) return;
  await fieldMap.refresh(owner.current).catch(() => {});
  if (!owner.current()) return;
  const failed = requiredResults.find((result) => result.status === "rejected");
  if (failed) throw failed.reason;
}
async function refreshRobotState(owner = authTicket()) {
  if (!owner.current()) return;
  const state = await api("/api/v1/robot/state", {signal: owner.signal});
  if (!owner.current()) return;
  markRequested();
  renderRobotState(state);
}
const stateSocket = createStateSocket({
  onState: state => { if (pageScope.capture().current()) renderRobotState(state); },
  poll: () => { const owner = authTicket(); return refreshRobotState(owner).catch(error => { if (owner.current()) showConnectionError(error); }); },
  onUnauthorized: () => signOut("세션이 만료되었거나 회수되었습니다. 다시 로그인하세요."),
});
pageScope.onDispose(invalidateAuth); pageScope.onResume(restoreConnection);
function signOut(message) {
  invalidateAuth(); stopTeleop("로그아웃으로 정지했습니다."); stopVisionPreview("카메라 인증 대기"); forgetToken();
  session.reconnectDelayMs = 1000; renderIdentity(); updateAdminControls();
  setConnection("unknown", "인증 대기"); setText("auth-notice", message);
  elements["auth-drawer"].classList.add("open"); devEntryChecked = false;
  elements["dev-connect-row"].hidden = true; revealDevelopmentEntry();
}
function showConnectionError(error) {
  if (error?.status === 401 && session.authenticated) { signOut("세션이 만료되었거나 회수되었습니다. 다시 로그인하세요."); return; }
  stopTeleop("연결 오류로 정지했습니다."); setConnection("error", "연결 확인 필요");
  setText("hero-message", error.message || "Rosy API에 연결할 수 없습니다.");
}
async function connect(owner = authTicket()) {
  if (!owner.current()) return false;
  session.reconnectDelayMs = 1000; setText("auth-notice", ""); setConnection("unknown", "연결 중");
  await detectRole(owner);
  if (!owner.current()) return false;
  await Promise.all([refreshRobotState(owner), refreshSlowData(owner)]);
  if (!owner.current()) return false;
  stateSocket.connect(); clearInterval(session.refreshTimer);
  session.refreshTimer = setInterval(() => refreshSlowData(owner).catch(error => { if (owner.current()) showConnectionError(error); }), 5000);
  startVisionPreview(); elements["auth-drawer"].classList.remove("open"); completeDashboardAuthentication();
  return true;
}
function restoreConnection() {
  if (!session.authenticated) return;
  const owner = authTicket();
  connect(owner).catch(error => { if (owner.current()) { showConnectionError(error); elements["auth-drawer"].classList.add("open"); } });
}
pageScope.listen(elements["auth-form"], "submit", async (event) => {
  event.preventDefault(); invalidateAuth(); stopVisionPreview("카메라 재인증 중");
  rememberToken(elements["token-input"].value.trim());
  const owner = authTicket();
  elements["token-input"].value = ""; setText("auth-message", "연결 확인 중…");
  try { if (await connect(owner)) setText("auth-message", "연결되었습니다."); }
  catch (error) {
    if (!owner.current()) return;
    forgetToken(); stateSocket.stop(); renderIdentity(); stopVisionPreview("카메라 인증 실패");
    setText("auth-message", error.message); showConnectionError(error);
  }
});
let codeRetryTimer = null, devEntryChecked = false, devRetryTimer = null;
async function revealDevelopmentEntry() {
  if (devEntryChecked || session.authenticated) return;
  devEntryChecked = true;
  if (await connectionOffer() && !session.authenticated && pageScope.capture().current()) elements["dev-connect-row"].hidden = false;
}
pageScope.listen(elements["dev-connect"], "click", async () => {
  if (elements["dev-connect"].disabled) return;
  invalidateAuth();
  const lifetime = authLifetime;
  setText("dev-message", "개발 연결 확인 중…"); setEnabled("dev-connect", false, "개발 연결 확인 중");
  let identity = null;
  try { identity = await developmentSession({signal: AbortSignal.any([lifetime.signal, pageScope.signal])}); }
  catch (error) {
    if (lifetime !== authLifetime || lifetime.signal.aborted || !pageScope.capture().current()) return;
    setText("dev-message", error.message || "로봇에 닿지 못했습니다.");
    setEnabled("dev-connect", false, error.message || "잠시 후 다시 시도할 수 있습니다.");
    clearTimeout(devRetryTimer);
    devRetryTimer = setTimeout(() => { if (lifetime === authLifetime && !lifetime.signal.aborted && pageScope.capture().current()) setEnabled("dev-connect", true); }, (error.retryAfter || 0) * 1000);
    return;
  }
  if (lifetime !== authLifetime || lifetime.signal.aborted || !pageScope.capture().current()) return;
  const owner = authTicket();
  setEnabled("dev-connect", true); stopVisionPreview("카메라 재인증 중");
  try { if (await connect(owner)) setText("dev-message", `${identity.role} 로 로그인했습니다 · ${expiryLabel(identity.expires_at)}`); }
  catch (error) { if (owner.current()) { setText("dev-message", `로그인은 되었지만 연결하지 못했습니다: ${error.message}`); showConnectionError(error); } }
});
pageScope.listen(elements["code-form"], "submit", async (event) => {
  event.preventDefault();
  if (elements["code-submit"].disabled) return;
  const code = normalizeLoginCode(elements["code-input"].value);
  if (code.error) { setText("code-message", code.error); return; }
  invalidateAuth();
  const lifetime = authLifetime;
  setText("code-message", "코드 확인 중…");
  elements["code-submit"].disabled = true;
  let identity = null;
  try { identity = await pairWithCode(code.value, { label: elements["code-label"].value.trim(), persist: elements["code-remember"].checked, signal: AbortSignal.any([lifetime.signal, pageScope.signal]) }); }
  catch (error) {
    if (lifetime !== authLifetime || lifetime.signal.aborted || !pageScope.capture().current()) return;
    setText("code-message", error.message || "로봇에 닿지 못했습니다.");
    clearTimeout(codeRetryTimer);
    codeRetryTimer = setTimeout(() => {
      if (lifetime === authLifetime && !lifetime.signal.aborted && pageScope.capture().current()) elements["code-submit"].disabled = false;
    }, (error.retryAfter || 0) * 1000);
    return;
  }
  if (lifetime !== authLifetime || lifetime.signal.aborted || !pageScope.capture().current()) return;
  const owner = authTicket();
  elements["code-submit"].disabled = false;
  elements["code-input"].value = ""; stopVisionPreview("카메라 재인증 중");
  try { if (await connect(owner)) setText("code-message", `${identity.role} 로 로그인했습니다 · ${expiryLabel(identity.expires_at)}`); }
  catch (error) { if (owner.current()) { setText("code-message", `로그인은 되었지만 연결하지 못했습니다: ${error.message}`); showConnectionError(error); } }
});
function showAuthTab(which) {
  const code = which === "code";
  elements["auth-tab-code"].setAttribute("aria-selected", String(code)); elements["auth-tab-token"].setAttribute("aria-selected", String(!code));
  elements["code-form"].hidden = !code; elements["auth-form"].hidden = code; elements[code ? "code-input" : "token-input"].focus();
}
elements["auth-tab-code"].addEventListener("click", () => showAuthTab("code"));
elements["auth-tab-token"].addEventListener("click", () => showAuthTab("token"));
pageScope.listen(elements["logout"], "click", async () => {
  invalidateAuth();
  const lifetime = authLifetime, owner = authTicket();
  try {
    const deleted = await logout({signal: owner.signal});
    if (lifetime !== authLifetime || lifetime.signal.aborted || !pageScope.capture().current()) return;
    signOut(deleted ? "로그아웃했습니다. 이 브라우저의 키는 로봇에서 지워졌습니다." : "이 브라우저에서 키를 지웠습니다. 토큰 자체는 로봇에 남아 있습니다 — 회수는 설정의 API 토큰에서 합니다.");
  } catch (error) { if (owner.current()) setText("hero-message", `로그아웃 실패: ${error.message}`); }
});
elements["open-auth"].addEventListener("click", () => elements["auth-drawer"].classList.add("open"));
elements["close-auth"].addEventListener("click", () => elements["auth-drawer"].classList.remove("open"));
elements["refresh-events"].addEventListener("click", () => api("/api/v1/events?limit=10").then(renderEvents).catch(showConnectionError));
document.querySelectorAll("ui-button[data-mode]").forEach((button) => {
  pageScope.listen(button, "click", async () => {
    if (commandOwner || button.disabled || session.modeChangePending) return;
    const requestedMode = button.dataset.mode, previous = session.robotState?.mode;
    stopTeleop("모드 변경 전에 정지했습니다.");
    await runConfirmed(`${enumLabel(MODE_LABEL, requestedMode)} 모드로 변경할까요? 주변 안전을 확인하세요.`, button,
      () => !session.modeChangePending && previous === session.robotState?.mode && (requestedMode !== "NAVIGATION" || session.capabilities?.navigation?.goal_navigation === true), async (active, owner) => {
      await api("/api/v1/mode", { method: "POST", body: JSON.stringify({ mode: requestedMode }) });
      if (active()) { announceAction(`${enumLabel(MODE_LABEL, requestedMode)} 모드 요청을 전송했습니다.`); await refreshRobotState(owner); }
    }, error => announceAction(`모드 변경 실패: ${error.message}`), pending => { session.modeChangePending = pending; updateModeButtons(); });
  });
});
document.querySelectorAll("[data-line-mode]").forEach((button) => {
  if (button.dataset.lineMode === "OFF") button.dataset.alwaysLive = "";
  pageScope.listen(button, "click", async () => {
    const mode = button.dataset.lineMode;
    if (button.disabled || (lineFollow.pending && mode !== "OFF") || (mode !== "OFF" && commandOwner)) return;
    stopTeleop("차선 추종 모드 변경 전에 정지했습니다.");
    const pending = value => { lineFollow.pending = value; updateLegacyLineControls(); };
    const run = async (active, owner) => {
      const status = await api("/api/v1/line-follow/mode", { method: "PUT", body: JSON.stringify({ mode }) });
      if (!active()) return;
      renderLineFollow(status); updateLegacyLineControls();
      announceAction(mode === "OFF" ? "차선 추종을 해제했습니다." : `${button.textContent.trim()} 차선 추종을 선택했습니다.`);
      await refreshRobotState(owner);
    };
    const fail = error => announceAction(`차선 추종 변경 실패: ${error.message}`);
    if (mode !== "OFF") await runConfirmed(`${button.textContent.trim()} 차선 추종을 시작할까요? 주변 안전을 확인하세요.`, button, () => !lineFollow.pending && lineFollowStartReady(), run, fail, pending, "line");
    else {
      if (commandOwner?.kind === "line") commandOwner = null;
      const owner = authTicket(), role = session.role, active = () => owner.current() && role === session.role; pending(true);
      try { await run(active, {...owner, current: active}); } catch (error) { if (active()) fail(error); }
      finally { if (active()) pending(false); }
    }
  });
});
document.querySelectorAll("[data-teleop]").forEach((button) => {
  button.addEventListener("pointerdown", (event) => startTeleop(button, event));
  button.addEventListener("pointerup", () => stopTeleop());
  button.addEventListener("pointercancel", () => stopTeleop("포인터 취소로 정지했습니다."));
  button.addEventListener("pointerleave", () => stopTeleop("버튼 이탈로 정지했습니다."));
  button.addEventListener("contextmenu", (event) => event.preventDefault());
});
elements["teleop-override"].addEventListener("click", () => elements["teleop-heading"].scrollIntoView({ behavior: "smooth", block: "center" }));
window.addEventListener("pointerup", () => stopTeleop());
window.addEventListener("blur", () => stopTeleop("화면 포커스가 해제되어 정지했습니다."));
window.addEventListener("pagehide", () => stopTeleop("페이지를 벗어나 정지했습니다.", true));
window.addEventListener("pagehide", () => stopVisionPreview("카메라 연결 종료"));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { stopTeleop("화면이 숨겨져 정지했습니다."); stopVisionPreview("숨겨진 탭 · 카메라 일시 중지"); }
  else if (session.authenticated) startVisionPreview();
});
elements["view-operate"].addEventListener("click", () => showView("operate"));
elements["view-inspect"].addEventListener("click", () => showView("inspect"));
showView("operate");
async function requestStop(message) {
  const owner = authTicket(); stopTeleop("비상정지를 요청했습니다.");
  try {
    await api("/api/v1/safety/stop", { method: "POST" });
    if (owner.current()) { announceAction(message); await refreshRobotState(owner); }
  } catch (error) { if (owner.current()) announceAction(`정지 명령 실패: ${error.message}`); }
}
elements["emergency-stop"].addEventListener("click", () => requestStop("비상정지가 활성화되었습니다."));
window.addEventListener("rosy:goal", (event) => { session.lastGoal = event.detail; });
let actionMessageTimer = null;
function announceAction(text) {
  const el = elements["action-message"];
  if (!el) return;
  el.textContent = text; el.removeAttribute("data-faded"); clearTimeout(actionMessageTimer);
  actionMessageTimer = setTimeout(() => el.setAttribute("data-faded", ""), 5000);
}
window.addEventListener("rosy:announce", (event) => announceAction(event.detail));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const tag = event.target?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (event.target?.isContentEditable || event.repeat || session.robotState?.safety?.estop === true || !session.authenticated) return;
  requestStop("비상정지가 활성화되었습니다 (Escape).");
});
pageScope.listen(elements["release-stop"], "click", async () => {
  await runConfirmed("주변 안전을 확인했고 정지를 해제할까요?", elements["release-stop"],
    () => isAdmin() && session.robotState?.safety?.estop === true && new HeadlessState(session.robotState).isFresh("safety"), async (active, owner) => {
    await api("/api/v1/safety/release", { method: "POST" });
    if (active()) { announceAction("비상정지가 해제되었습니다."); await refreshRobotState(owner); }
  }, error => announceAction(`정지 해제 실패: ${error.message}`));
});
pageScope.listen(elements["dds-cyclone-apply"], "click", async () => {
  await runConfirmed("CycloneDDS를 저장하고 로봇을 재부팅할까요? 모터와 화면이 잠시 내려갑니다.", elements["dds-cyclone-apply"],
    () => isAdmin() && session.identity !== null && session.robotState?.online === true, async active => {
    const payload = await api("/api/v1/system/dds/cyclone", { method: "POST", body: JSON.stringify({ confirmed: true, idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) }) });
    if (!active()) return;
    const reboot = payload.reboot || {};
    if (reboot.available === false) { announceAction(reboot.detail || "저장했습니다. 런타임을 다시 띄우세요."); return; }
    announceAction(reboot.ok ? "재부팅을 요청했습니다." : (reboot.detail || "재부팅이 거부되었습니다."));
  }, error => announceAction(`Cyclone 적용 실패: ${error.message}`));
});
elements["hardware-refresh"]?.addEventListener("click", async () => {
  setEnabled("hardware-refresh", false);
  try {
    const reply = await api("/api/v1/host/hardware/refresh", {method: "POST"});
    setText("hardware-note", reply.detail || "장치 점검을 요청했습니다.");
    if (reply.accepted) { await new Promise((resolve) => setTimeout(resolve, 5000)); renderHardware(await api("/api/v1/host/hardware")); }
  } catch (error) { setText("hardware-note", `장치 점검 요청 실패: ${error.message}`); }
  finally { setEnabled("hardware-refresh", isAdmin(), "관리자 권한 필요"); }
});
const HW_TEST_WAIT_MS = 12000, HW_TEST_POLL_MS = 1000;
async function waitForHardwareTest(requestId) {
  const deadline = Date.now() + HW_TEST_WAIT_MS;
  let payload = await api("/api/v1/host/hardware");
  while (payload?.test?.request_id !== requestId && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, HW_TEST_POLL_MS));
    payload = await api("/api/v1/host/hardware");
  }
  return payload;
}
elements["hardware-list"]?.addEventListener("click", async (event) => {
  const button = event.target.closest?.("[data-hw-action]");
  if (!button || button.disabled || !isAdmin()) return;
  const device = button.dataset.device, action = button.dataset.hwAction;
  button.disabled = true;
  try {
    if (action === "test") {
      const reply = await api("/api/v1/host/hardware/test", {method: "POST", body: JSON.stringify({device})});
      setText("hardware-note", reply.detail || "시험을 요청했습니다.");
      const payload = await waitForHardwareTest(reply.request_id);
      renderHardware(payload);
      if (payload?.test?.request_id !== reply.request_id) setText("hardware-note", "시험 결과가 12초 안에 오지 않았습니다. 잠시 뒤 다시 시험하세요.");
      return;
    }
    const observed = action === "observed";
    await api("/api/v1/host/hardware/confirm", {method: "POST", body: JSON.stringify({device, observed})});
    renderHardware(await api("/api/v1/host/hardware")); setText("hardware-note", "확인 결과를 기록했습니다.");
  } catch (error) {
    setText("hardware-note", `장치 시험 실패: ${error.message}`);
    button.disabled = false;
  }
});
async function runNetwork(button, path, body, prompt, success, failure, eligible = () => true) {
  const networkMode = elements["network-mode"]?.textContent;
  const clearSecret = () => { if (body.psk !== undefined && elements["network-psk-input"].value === body.psk) elements["network-psk-input"].value = ""; };
  await runConfirmed(prompt, button, () => isAdmin() && document.getElementById("network-card")?.dataset.available === "true" && networkMode === elements["network-mode"]?.textContent && eligible(), async (active, owner) => {
    try {
      const payload = await api(path, {method: "POST", body: JSON.stringify({...body, confirmed: true, idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now())})});
      if (!active()) return;
      clearSecret();
      setText("network-note", payload.available === false ? (payload.detail || "호스트 에이전트가 없어 적용하지 못했습니다.") : payload.ok ? success : (payload.detail || "적용이 거부되었습니다."));
      if (payload.available === false || !active()) return;
      const status = await api("/api/v1/host/network", {signal: owner.signal});
      if (active()) renderHostNetwork(status);
    } catch (error) { if (active()) { clearSecret(); throw error; } }
  }, error => setText("network-note", `${failure}: ${error.message}`));
}
for (const [id, mode, prompt] of [
  ["network-ap-off", "SITE_STA", "AP를 끌까요? 로봇은 사업장 Wi-Fi(SITE_STA)만 씁니다. 연결이 잠깐 끊길 수 있습니다."],
  ["network-ap-on", "RELAY_AP_STA", "AP를 켤까요? 로봇이 릴레이(AP+STA)를 엽니다. 연결이 잠깐 끊길 수 있습니다."],
]) pageScope.listen(elements[id], "click", () => runNetwork(elements[id], "/api/v1/host/network/mode", {mode}, prompt, `${enumLabel(NETWORK_MODE_LABEL, mode)} 모드를 적용했습니다.`, "네트워크 모드 변경 실패"));
pageScope.listen(elements["network-connect"], "click", () => {
  const ssid = elements["network-ssid-input"]?.value.trim(), joinCredential = {value: elements["network-psk-input"]?.value || ""};
  if (!ssid || joinCredential.value.length < 8) { setText("network-note", !ssid ? "SSID를 입력하세요." : "암호는 8자 이상이어야 합니다."); return; }
  runNetwork(elements["network-connect"], "/api/v1/host/network/connect", {ssid, psk: joinCredential.value}, `${ssid} 에 연결할까요? 연결이 잠깐 끊길 수 있습니다.`, `${ssid} 에 연결했습니다.`, "Wi-Fi 연결 실패",
    () => ssid === elements["network-ssid-input"].value.trim() && joinCredential.value === elements["network-psk-input"].value);
});
pageScope.listen(elements["network-apply"], "click", () => {
  const profileId = elements["network-profile-id"]?.value.trim();
  if (!profileId) { setText("network-note", "프로파일 id를 입력하세요."); return; }
  runNetwork(elements["network-apply"], "/api/v1/host/network/apply", {profile_id: profileId}, `${profileId} 네트워크 프로파일을 적용할까요? 연결이 잠깐 끊길 수 있습니다.`, `${profileId} 를 적용했습니다.`, "프로파일 적용 실패",
    () => profileId === elements["network-profile-id"].value.trim());
});
bindFormSave("network-connect-form", "network-connect");
bindFormSave("network-apply-form", "network-apply");
initSettings({ onIdentityChanged: renderRobotInfo, refreshRobotState, runConfirmed, captureLifetime: authTicket });
initTelemetry({runConfirmed, captureLifetime: authTicket});
pageScope.interval(() => setText("clock", new Date().toLocaleTimeString("ko-KR", { hour12: false })), 1000);
setText("clock", new Date().toLocaleTimeString("ko-KR", { hour12: false }));
await restoreAccount();
if (session.authenticated) restoreConnection();
else { elements["auth-drawer"].classList.add("open"); revealDevelopmentEntry(); }
