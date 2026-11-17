import { restoreAccount } from "./client.js";
// Authentication entry: credentials stay in client.js; CORE owns permissions.
import { api, session, rememberToken, forgetToken, normalizeLoginCode, pairWithCode,
  logout, connectionOffer, developmentSession, PAIRED_SOURCES, sourceLabel, expiryLabel } from "./client.js";
import { dashboardReturnTarget, completeDashboardAuthentication, dashboardSurfaceBridge } from "./surface-navigation.js";
import { ROLE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { actionIcon } from "/common/ui.js";
import { statusTag } from "/common/status-tag.js";
import { createBusyScope } from "/common/busy-scope.js";
import { createStopControl } from "/common/stop-control.js";

const el = id => document.getElementById(id);
const status = el("entry-status");
const nav = el("entry-navigation");
const stop = el("entry-stop");
// Every locked control comes back as it was; the stop is [data-always-live] and is never locked.
const scope = createBusyScope(document.body);
actionIcon(el("code-submit"), "login");
// An error line is a caution tag (the warn glyph belongs to status tags only); the wording stays the same and is never only an icon.
function codeError(text) {
  const message = el("code-message");
  message.replaceChildren();
  if (!text) return;
  message.append(statusTag("caution", text));
}
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
  // The scope owns `disabled` while it runs (setDisabled records the wanted state), so nothing opens mid-run.
  scope.setDisabled(el("code-submit"), scope.busy || retryUntil > Date.now());
  scope.setDisabled(el("auth-form").querySelector('ui-button[type="submit"]'), scope.busy);
  scope.setDisabled(el("entry-retry"), scope.busy);
  scope.setDisabled(el("entry-logout"), scope.busy);
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
  // 로그인 전 설명은 로그인 창의 한 문단(8자·10분·한 번)뿐이다. 머리 문단은 로그인 뒤에만 쓴다.
  const lead = document.querySelector(".entry-heading p");
  lead.hidden = !identity;
  lead.textContent = identity ? "로그인이 확인되었습니다. 필요한 작업 화면을 열 수 있습니다." : "";
  if (identity) {
    const role = enumLabel(ROLE_LABEL, identity.role, "역할 정보 없음");
    el("entry-role").textContent = role;
    el("entry-role").title = identity.role || "";
    el("entry-identity").textContent = [role, identity.label || identity.id,
      sourceLabel(identity.source), expiryLabel(identity.expires_at)].filter(Boolean).join(" · ");
    el("entry-logout").textContent = identity.source === 'account' || PAIRED_SOURCES.has(identity.source) ? "로그아웃" : "이 브라우저에서 잊기";
    const remaining = Date.parse(identity.expires_at || "") - Date.now();
    if (identity.source !== 'account' && Number.isFinite(remaining) && remaining > 0) {
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
  if (scope.busy || !session.authenticated) return;
  await scope.run(loadAll);
  controls();
}

async function loadAll() {
  const attempt = ++generation;
  let identityConfirmed = false;
  clearDestinations();
  setStatus("로그인과 작업 화면을 확인하고 있습니다.", "pending");
  el("entry-retry").hidden = true;
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
    // ui.js는 부팅 때만 아이콘을 붙인다 — 동적으로 그린 레일 항목은 여기서 다시 칠한다.
    for (const link of nav.querySelectorAll("a[data-action-icon]")) {
      if (!link.querySelector(":scope > .ui-icon")) actionIcon(link, link.dataset.actionIcon);
    }
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
  }
}

el("auth-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (scope.busy) return;
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
  if (scope.busy || retryUntil > Date.now()) return;
  const code = normalizeLoginCode(el("code-input").value);
  if (code.error) { codeError(code.error); return; }
  el("code-message").textContent = "코드를 확인하고 있습니다.";
  const ok = await scope.run(async () => {
    try {
      await pairWithCode(code.value, {label: el("code-label").value.trim(), persist: el("code-remember").checked,
        signal: AbortSignal.timeout(REQUEST_MS)});
      el("code-input").value = "";
      el("code-message").textContent = "";
      return true;
    } catch (error) {
      codeError(["TimeoutError", "AbortError"].includes(error.name)
        ? "코드 확인 시간이 지났습니다. 연결을 확인하고 다시 시도하세요." : error.message);
      retryUntil = Date.now() + (error.retryAfter || 0) * 1000;
      clearTimeout(retryTimer);
      retryTimer = setTimeout(controls, Math.max(0, retryUntil - Date.now()));
      return false;
    }
  });
  controls();
  if (ok) await loadDestinations();
});

el("entry-retry").addEventListener("click", loadDestinations);

// D-432/D-471: 개발 연결 모드 로봇은 로그인 서랍에 코드 없는 입장을 보여준다.
let devEntryProbed = false;
async function revealDevEntry() {
  if (devEntryProbed || session.authenticated) return;
  devEntryProbed = true;
  const offer = await connectionOffer();
  if (!offer || session.authenticated) return;
  el("dev-connect-row").hidden = false;
}
el("dev-connect").addEventListener("click", async () => {
  if (scope.busy || retryUntil > Date.now()) return;
  el("dev-message").textContent = "개발 연결을 확인하고 있습니다.";
  const ok = await scope.run(async () => {
    try {
      const identity = await developmentSession({signal: AbortSignal.timeout(REQUEST_MS)});
      el("dev-message").textContent = "";
      if (identity?.role) el("code-message").textContent = "";
      return true;
    } catch (error) {
      el("dev-message").textContent = ["TimeoutError", "AbortError"].includes(error.name)
        ? "개발 연결 확인 시간이 지났습니다. 연결을 확인하고 다시 시도하세요." : error.message;
      retryUntil = Date.now() + (error.retryAfter || 0) * 1000;
      clearTimeout(retryTimer);
      retryTimer = setTimeout(controls, Math.max(0, retryUntil - Date.now()));
      return false;
    }
  });
  controls();
  if (ok) await loadDestinations();
});

el("entry-logout").addEventListener("click", async () => {
  if (scope.busy) return;
  await scope.run(async () => {
    try {
      const deleted = await logout({signal: AbortSignal.timeout(REQUEST_MS)});
      generation++;
      clearDestinations();
      el("entry-retry").hidden = true;
      setStatus(deleted ? "로그아웃했습니다. 다시 로그인할 수 있습니다." : "이 브라우저에서 접속 키를 지웠습니다. 로봇의 키는 유지됩니다.");
      el("code-message").textContent = "";
      el("entry-stop-notice").hidden = true; stopControl.note("", "");  // a stale stop answer does not outlive the login
      renderIdentity();
      devEntryProbed = false;
      revealDevEntry();
    } catch (error) {
      setStatus(`로그아웃하지 못했습니다. 연결을 확인하고 다시 시도하세요: ${error.message}`, "error");
    }
  });
  controls();
});

// D-270/C9: stop is for every role, also before login (a viewer's stop is accepted); a refusal is shown as text.
let stopAttempt = 0;
const stopControl = createStopControl({button: stop, status: el("entry-stop-notice"), timeoutMs: REQUEST_MS, send: async signal => {
  const attempt = ++stopAttempt;
  el("entry-stop-notice").hidden = false;
  try { await api("/api/v1/safety/stop", {method: "POST", signal}); }
  catch (error) {
    if (error.name === "AbortError" || error.name === "TimeoutError") throw error;
    return {ok: false, status: error.status ?? (session.authenticated ? 0 : 403)};  // no credentials yet: the text says to log in
  }
  // The request was accepted; whether the robot stopped is the readback, shown only for the newest press.
  api("/api/v1/robot/state", {signal: AbortSignal.timeout(REQUEST_MS)}).catch(() => null).then(readback => {
    if (attempt !== stopAttempt) return;
    stopControl.note(readback?.safety?.estop === true || readback?.mode === "SAFE_STOP"
      ? "비상 정지 요청 접수 · 로봇 정지 상태 확인. 물리 정지는 별도로 확인하세요."
      : "비상 정지 요청 접수 · 상태 확인 불가. 실제 정지를 확인하세요.", "warning");
  });
  return {ok: true, status: 200};
}});

window.addEventListener("pagehide", () => { generation++; clearTimeout(retryTimer); clearTimeout(expiryTimer); });
await restoreAccount();
if (session.account?.enabled && !session.account.authenticated) window.location.replace('/api/account/login?return=' + encodeURIComponent(dashboardReturnTarget(window.location.search) ?? '/dashboard'));
renderIdentity();
if (session.authenticated) loadDestinations();
else { setStatus(""); revealDevEntry(); }
