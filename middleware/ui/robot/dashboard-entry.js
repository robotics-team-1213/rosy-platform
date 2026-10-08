// Authentication entry: credentials stay in client.js; CORE owns permissions.
import { api, session, rememberToken, forgetToken, normalizeLoginCode, pairWithCode,
  logout, connectionOffer, developmentSession, PAIRED_SOURCES, sourceLabel, expiryLabel } from "./client.js";
import { dashboardReturnTarget, completeDashboardAuthentication, dashboardSurfaceBridge } from "./surface-navigation.js";
import { ROLE_LABEL, enumLabel } from "/common/core_ui_logic.js";

const el = id => document.getElementById(id);
const status = el("entry-status");
const nav = el("entry-navigation");
const stop = el("entry-stop");
let busy = false;
let retryUntil = 0;
let retryTimer = null;
let expiryTimer = null;
let generation = 0;
const REQUEST_MS = 10_000;

function setStatus(message, state = "ready") {
  status.removeAttribute("title");
  status.textContent = message;
  status.hidden = !message;
  status.setAttribute("state", state);
}

function controls() {
  el("code-submit").disabled = busy || retryUntil > Date.now();
  el("auth-form").querySelector('ui-button[type="submit"]').disabled = busy;
  el("entry-retry").disabled = busy;
  el("entry-logout").disabled = busy;
  stop.disabled = !session.identity;
  if (session.identity) stop.removeAttribute("reason");
  else stop.setAttribute("reason", "로그인 후 사용할 수 있습니다.");
}

function clearDestinations() {
  dashboardSurfaceBridge(nav, []);
  el("entry-destinations").hidden = true;
}

function renderIdentity() {
  clearTimeout(expiryTimer);
  const identity = session.identity;
  el("entry-role").hidden = !identity;
  el("entry-logout").hidden = !identity;
  el("auth-drawer").hidden = Boolean(identity);
  el("dev-connect-row").hidden = true;
  document.querySelector(".entry-heading h1").textContent = identity ? "작업을 선택하세요" : "로봇에 연결";
  document.querySelector(".entry-heading p").textContent = identity ? "로그인이 확인되었습니다. 필요한 작업 화면을 열 수 있습니다." : "로그인한 뒤 수행할 작업을 선택하세요.";
  if (!identity) {
    el("entry-stop-notice").hidden = true;
    el("entry-stop-notice").textContent = "";
  }
  if (identity) {
    const role = enumLabel(ROLE_LABEL, identity.role, "역할 정보 없음");
    el("entry-role").textContent = role;
    el("entry-role").title = identity.role || "";
    el("entry-identity").textContent = [role, identity.label || identity.id,
      sourceLabel(identity.source), expiryLabel(identity.expires_at)].filter(Boolean).join(" · ");
    el("entry-logout").textContent = PAIRED_SOURCES.has(identity.source) ? "로그아웃" : "이 브라우저에서 잊기";
    const remaining = Date.parse(identity.expires_at || "") - Date.now();
    if (Number.isFinite(remaining) && remaining > 0) {
      expiryTimer = setTimeout(() => {
        if (Date.parse(session.identity?.expires_at || "") > Date.now()) { renderIdentity(); return; }
        generation++;
        forgetToken();
        clearDestinations();
        el("entry-retry").hidden = true;
        setStatus("로그인이 만료되었습니다. 다시 로그인하세요.", "warning");
        renderIdentity();
      }, Math.min(remaining, 2_147_483_647));
    }
  }
  controls();
}

async function loadDestinations() {
  if (busy || !session.token) return;
  const attempt = ++generation;
  let identityConfirmed = false;
  busy = true;
  clearDestinations();
  setStatus("로그인과 작업 화면을 확인하고 있습니다.", "pending");
  el("entry-retry").hidden = true;
  controls();
  try {
    const identity = await api("/api/v1/auth/whoami", {signal: AbortSignal.timeout(REQUEST_MS)});
    if (attempt !== generation) return;
    if (!identity || typeof identity !== "object" || Array.isArray(identity)
        || typeof identity.role !== "string" || !identity.role.trim()) throw new Error("로그인 정보 응답을 읽지 못했습니다.");
    if (Date.parse(identity.expires_at || "") <= Date.now()) {
      const error = new Error("로그인이 만료되었습니다."); error.status = 401; throw error;
    }
    session.identity = identity;
    session.role = identity?.role || "";
    identityConfirmed = true;
    renderIdentity();
    const manifest = await api("/api/v1/ui/surfaces/console", {signal: AbortSignal.timeout(REQUEST_MS)});
    if (attempt !== generation) return;
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest) || !Array.isArray(manifest.surfaces)) {
      throw new Error("작업 화면 목록 응답을 읽지 못했습니다.");
    }
    dashboardSurfaceBridge(nav, manifest?.surfaces);
    el("entry-destinations").hidden = false;
    const target = dashboardReturnTarget(window.location.search);
    const allowed = [...nav.querySelectorAll("a")].some(link => link.getAttribute("href") === target);
    if (target && allowed && completeDashboardAuthentication()) return;
    setStatus(nav.hidden ? "이 로그인에 허용된 작업 화면이 없습니다. 관리자에게 권한을 확인하거나 목록을 다시 불러오세요."
      : target && !allowed ? "요청한 작업 화면에 접근할 수 없습니다. 허용된 화면을 선택하세요." : "");
    el("entry-retry").hidden = !nav.hidden;
  } catch (error) {
    if (attempt !== generation) return;
    clearDestinations();
    if (!identityConfirmed) { session.identity = null; session.role = ""; }
    if (error.status === 401) {
      forgetToken();
      setStatus("로그인이 만료되었거나 접속 키가 맞지 않습니다. 다시 로그인하세요.", "warning");
      el("entry-retry").hidden = true;
    } else if (error.status === 403) {
      setStatus("이 로그인으로 요청한 정보를 열 수 없습니다. 관리자에게 접속 권한을 확인하세요.", "forbidden");
      el("entry-retry").hidden = false;
    } else {
      setStatus(session.identity ? "로그인을 확인했지만 화면 목록을 받지 못했습니다. 연결을 확인하고 다시 불러오세요."
        : "로그인을 확인하지 못했습니다. 로봇과 같은 네트워크인지 확인하고 다시 시도하세요.", "error");
      status.title = error.message || "";
      el("entry-retry").hidden = false;
    }
    renderIdentity();
  } finally {
    busy = false;
    controls();
  }
}

function showAuthTab(which) {
  const code = which === "code";
  for (const [id, selected] of [["auth-tab-code", code], ["auth-tab-token", !code]]) {
    el(id).setAttribute("aria-selected", String(selected));
    el(id).tabIndex = selected ? 0 : -1;
  }
  el("code-form").hidden = !code;
  el("auth-form").hidden = code;
  el(code ? "code-input" : "token-input").focus();
}

for (const [id, which] of [["auth-tab-code", "code"], ["auth-tab-token", "token"]]) {
  el(id).addEventListener("click", () => showAuthTab(which));
  el(id).addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    showAuthTab(event.key === "Home" ? "code" : event.key === "End" ? "token" : which === "code" ? "token" : "code");
  });
}
el("auth-tab-token").tabIndex = -1;

el("auth-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  const token = el("token-input").value.trim();
  if (!token) return;
  rememberToken(token);
  el("token-input").value = "";
  session.identity = null;
  renderIdentity();
  await loadDestinations();
});

el("code-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy || retryUntil > Date.now()) return;
  const code = normalizeLoginCode(el("code-input").value);
  if (code.error) { el("code-message").textContent = code.error; return; }
  busy = true;
  controls();
  el("code-message").textContent = "코드를 확인하고 있습니다.";
  try {
    await pairWithCode(code.value, {label: el("code-label").value.trim(), persist: el("code-remember").checked,
      signal: AbortSignal.timeout(REQUEST_MS)});
    el("code-input").value = "";
    el("code-message").textContent = "";
  } catch (error) {
    el("code-message").textContent = ["TimeoutError", "AbortError"].includes(error.name)
      ? "코드 확인 시간이 지났습니다. 연결을 확인하고 다시 시도하세요." : error.message;
    retryUntil = Date.now() + (error.retryAfter || 0) * 1000;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(controls, Math.max(0, retryUntil - Date.now()));
    return;
  } finally { busy = false; controls(); }
  await loadDestinations();
});

el("entry-retry").addEventListener("click", loadDestinations);

// D-432/D-471: 개발 연결 모드 로봇은 로그인 서랍에 코드 없는 입장을 보여준다.
let devEntryProbed = false;
async function revealDevEntry() {
  if (devEntryProbed || session.token) return;
  devEntryProbed = true;
  const offer = await connectionOffer();
  if (!offer || session.token) return;
  el("dev-connect-row").hidden = false;
}
el("dev-connect").addEventListener("click", async () => {
  if (busy || retryUntil > Date.now()) return;
  busy = true;
  controls();
  el("dev-message").textContent = "개발 연결을 확인하고 있습니다.";
  try {
    const identity = await developmentSession({signal: AbortSignal.timeout(REQUEST_MS)});
    el("dev-message").textContent = "";
    if (identity?.role) el("code-message").textContent = "";
  } catch (error) {
    el("dev-message").textContent = ["TimeoutError", "AbortError"].includes(error.name)
      ? "개발 연결 확인 시간이 지났습니다. 연결을 확인하고 다시 시도하세요." : error.message;
    retryUntil = Date.now() + (error.retryAfter || 0) * 1000;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(controls, Math.max(0, retryUntil - Date.now()));
    return;
  } finally { busy = false; controls(); }
  await loadDestinations();
});

el("entry-logout").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  controls();
  try {
    const deleted = await logout({signal: AbortSignal.timeout(REQUEST_MS)});
    generation++;
    clearDestinations();
    el("entry-retry").hidden = true;
    setStatus(deleted ? "로그아웃했습니다. 다시 로그인할 수 있습니다." : "이 브라우저에서 접속 키를 지웠습니다. 로봇의 키는 유지됩니다.");
    el("code-message").textContent = "";
    renderIdentity();
    devEntryProbed = false;
    revealDevEntry();
  } catch (error) {
    setStatus(`로그아웃하지 못했습니다. 연결을 확인하고 다시 시도하세요: ${error.message}`, "error");
  } finally { busy = false; controls(); }
});

stop.addEventListener("click", async () => {
  if (!session.identity) return;
  const attempt = generation;
  const notice = el("entry-stop-notice");
  notice.hidden = false;
  notice.setAttribute("state", "pending");
  notice.textContent = "비상 정지를 요청하고 있습니다.";
  try {
    await api("/api/v1/safety/stop", {method: "POST", signal: AbortSignal.timeout(REQUEST_MS)});
    if (attempt !== generation) return;
    let readback = null;
    try { readback = await api("/api/v1/robot/state", {signal: AbortSignal.timeout(REQUEST_MS)}); } catch (_error) { /* Acknowledgement is distinct from state readback. */ }
    if (attempt !== generation) return;
    notice.setAttribute("state", "warning");
    notice.textContent = readback?.safety?.estop === true || readback?.mode === "SAFE_STOP"
      ? "비상 정지 요청 접수 · CORE 정지 상태 확인. 물리 정지는 별도로 확인하세요."
      : "비상 정지 요청 접수 · 상태 확인 불가. 실제 정지를 확인하세요.";
  } catch (error) {
    if (attempt !== generation) return;
    notice.setAttribute("state", "error");
    notice.textContent = `비상 정지 실패: ${error.message}. 실제 정지를 확인하세요.`;
  }
});

window.addEventListener("pagehide", () => { generation++; clearTimeout(retryTimer); clearTimeout(expiryTimer); });
renderIdentity();
if (session.token) loadDestinations();
else { setStatus(""); revealDevEntry(); }
