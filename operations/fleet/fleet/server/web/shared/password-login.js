// D-519 — paired consoles sign people in with 아이디·비밀번호. The HttpOnly session cookie then
// rides every same-origin request, so pages only stop sending Authorization when no token is stored.
import {createFleetClient} from "/common/fleet-client.js";

const request = createFleetClient();

const TEMPLATE = `
  <div class="password-login-form" data-login="form" role="group" aria-label="관제 로그인">
    <input class="ui-field password-login-field" data-login="login" autocomplete="username"
           autocapitalize="none" spellcheck="false" placeholder="아이디" aria-label="아이디">
    <input class="ui-field password-login-field" data-login="password" type="password"
           autocomplete="current-password" placeholder="비밀번호" aria-label="비밀번호">
    <label class="password-login-remember"><input type="checkbox" data-login="remember"> 이 브라우저 기억(30일)</label>
    <ui-button kind="primary" type="button" data-login="submit">로그인</ui-button>
    <span class="password-login-error" data-login="error" role="alert" hidden></span>
  </div>
  <div class="password-login-who" data-login="who" hidden>
    <span data-login="principal"></span>
    <ui-button kind="quiet" type="button" data-login="logout">로그아웃</ui-button>
  </div>`;

function failureText(error) {
  if (error.status === 401) return "아이디 또는 비밀번호가 맞지 않습니다.";
  if (error.status === 429) return "실패가 많아 잠시 막혔습니다. 1분 뒤 다시 시도하세요.";
  return "로그인할 수 없습니다. 관제 PC 연결을 확인하세요.";
}

// `refresh(locked)`: the form shows only on a login site (`password_login`) while the page is locked
// and no cookie session exists; a cookie session shows its principal and 로그아웃.
export function createPasswordLogin(host, {onChange = () => {}} = {}) {
  host.innerHTML = TEMPLATE;
  const part = name => host.querySelector(`[data-login="${name}"]`);
  let locked = true, firstRefresh = true;

  async function refresh(nowLocked = locked) {
    locked = nowLocked;
    let connection = null, session = null;
    try { connection = await request("/api/fleet/auth/connection"); } catch (_err) { /* older Fleet */ }
    try { session = await request("/api/fleet/auth/session"); } catch (_err) { /* 401: no cookie session */ }
    const cookie = session?.via === "cookie";
    const offered = connection?.mode !== "development" && connection?.password_login === true;
    // Keep the token input out of the map after connection; its summary remains available for reconnect.
    if ((firstRefresh && offered) || !locked) document.getElementById("token-access")?.removeAttribute("open");
    firstRefresh = false;
    host.hidden = !cookie && (!offered || !locked);
    part("form").hidden = cookie;
    part("who").hidden = !cookie;
    part("principal").textContent = cookie ? session.principal_id : "";
    return cookie;
  }

  async function submit() {
    const error = part("error");
    error.hidden = true;
    try {
      await request("/api/fleet/auth/login", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({login: part("login").value.trim(), password: part("password").value,
          remember: part("remember").checked}),
      });
    } catch (err) {
      error.textContent = failureText(err);
      error.hidden = false;
      return;
    }
    part("password").value = "";
    // A stale stored token would win over the cookie (Bearer first), so the login replaces it.
    sessionStorage.removeItem("rosy-console-token");
    await refresh(false);
    onChange(true);
  }

  part("submit").addEventListener("click", submit);
  for (const name of ["login", "password"]) {
    part(name).addEventListener("keydown", event => { if (event.key === "Enter") submit(); });
  }
  part("logout").addEventListener("click", async () => {
    try { await request("/api/fleet/auth/logout", {method: "POST"}); } catch (_err) { /* cookie may be gone */ }
    await refresh(true);
    onChange(false);
  });
  return {refresh};
}
