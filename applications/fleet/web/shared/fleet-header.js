// D-540 2 / D-741 3 — the one Rosy Fleet app bar. 관제·설치·보정·현장 지도·Cell carry the same <ui-topbar>
// markup (test_fleet_header.py pins it) and drive it only through this module: link word and clock, alerts
// count, role words on the account button, development badge, the account fold and the one E-stop rule.
import "/common/ui.js";  // wires the `[data-theme-cycle]` button
import {OPERATOR_REASON} from "/console/assets/authorization.js";

export const SESSION_REASON = "접속이 필요합니다";
const ROLE = {operator: "운영자", viewer: "보기 전용", "policy-admin": "정책 관리자"};
const $ = id => document.getElementById(id);

// D-741 3 — 브라우저와 Fleet 사이의 연결. 답이 오면 실시간, LATE_MS 넘게 새 답이 없으면 지연,
// 요청이 닿지 않았거나 서버가 5xx로 답하면 연결 끊김이다. 401·403은 서버가 답한 것이라 실시간이다.
// 로봇과의 연결은 여기 것이 아니다. 그것은 관제 화면의 연결 수와 로봇 카드가 말한다.
const LINK = {wait: ["연결 대기", "neutral"], live: ["실시간", "neutral"], late: ["지연", "warn"], down: ["연결 끊김", "crit"]};
export const LATE_MS = 12000;  // 5초 조회 두 번을 놓치고 2초
let answeredAt = null, linkFailed = false;
export function linkState(now = Date.now()) {
  if (linkFailed) return "down";
  if (answeredAt === null) return "wait";
  return now - answeredAt > LATE_MS ? "late" : "live";
}
function paintLink(now) {
  const tag = $("link-state"), state = linkState(now);
  if (tag.dataset.link === state) return;
  tag.dataset.link = state;
  tag.textContent = LINK[state][0];
  tag.setAttribute("status", LINK[state][1]);
}
export function noteLink(error = null, now = Date.now()) {
  if (error?.name === "AbortError") return;
  linkFailed = Boolean(error) && !(typeof error.status === "number" && error.status < 500);
  if (!linkFailed) answeredAt = now;
  paintLink(now);
}

// The alerts button is static markup on every Fleet document; only the console owns the unread count.
function openInbox() {
  const request = new CustomEvent("rosy:inbox", {cancelable: true});
  if (document.dispatchEvent(request)) location.assign("/console?inbox=1");
}
export function showInboxCount(count) {
  const inbox = $("fleet-inbox"), unread = $("header-unread");
  unread.textContent = count ? String(count) : "";
  unread.hidden = !count;
  inbox.setAttribute("aria-label", `알림 창 · 미확인 메시지 ${count}개`);
  inbox.setAttribute("data-ui-tooltip", `${inbox.getAttribute("aria-label")} · 읽음은 개입 해소가 아닙니다`);
  inbox.title = "읽음 표시는 개입 해소나 로봇 상태 변경이 아닙니다";
}

export const roleLabel = role => ROLE[role] || "권한 없음";

// The one E-stop rule. `session` is undefined while unknown (loading, Fleet unreachable), null after a 401,
// else the /api/fleet/session body. Only a press the server would surely refuse is locked: no session (401)
// or a role without stop rights (403). Unknown stays live — never harder to reach than a refused press.
export function estopReason(session) {
  if (session === null) return SESSION_REASON;
  if (session && session.role !== "operator") return OPERATOR_REASON;
  return "";
}

function gateEstop(session) {
  const estop = $("estop"), reason = estopReason(session);
  estop.disabled = Boolean(reason);
  if (reason) estop.setAttribute("reason", reason);
  else estop.removeAttribute("reason");
}

// The fold is on demand only: losing access rewrites the words and the E-stop, never the row's open state.
export function setTopbarOpen(open) {
  $("topbar-more").setAttribute("aria-expanded", String(open));
  $("topbar-extra").dataset.open = String(open);
}
export function bindTopbarToggle(listen = (node, type, fn) => node.addEventListener(type, fn)) {
  listen($("fleet-inbox"), "click", openInbox);
  const entry = $("topbar-more");
  function summarize() {
    const development = $("development-badge").hidden ? "" : " · 개발 연결 모드";
    const label = `계정과 접속 · ${$("user-role").textContent}${development}`;
    entry.setAttribute("aria-label", label);
    entry.setAttribute("data-ui-tooltip", `${label} · 계정·화면 표시·토큰 접속`);
  }
  new MutationObserver(summarize).observe(entry, {subtree: true, childList: true,
    attributes: true, attributeFilter: ["hidden", "status"]});
  summarize();
  listen($("topbar-extra"), "keydown", event => {
    if (event.key === "Escape") { setTopbarOpen(false); $("topbar-more").focus(); }
  });
  listen($("topbar-more"), "click", () => {
    setTopbarOpen($("topbar-more").getAttribute("aria-expanded") !== "true");
  });
}

// English role names and principal ids stay in title (D-540 2); a development session says so with its badge.
export function showSession(identity) {
  const tag = $("user-role"), title = `${identity.principal_id} · ${identity.role}`;
  const changed = tag.title !== title;
  $('fleet-login').hidden = true;
  $('fleet-account').hidden = false;
  $('fleet-account-identity').textContent = `${identity.principal_id} · ${roleLabel(identity.role)}`;
  const token = $('token-access');
  if (token) { token.open = false; token.hidden = true; }
  // A session is stated in words, so the row it was entered through folds again (D-741 3):
  // one header line is what the operator reads after connecting.
  if (changed) setTopbarOpen(false);
  const development = identity.principal_id.startsWith("development-");
  tag.textContent = roleLabel(identity.role);
  tag.title = title;
  tag.setAttribute("status", identity.role === "operator" ? "active" : "neutral");
  if (development) $("development-badge").hidden = false;
  gateEstop(identity);
}

// `refused` is false when the session probe failed for another reason (Fleet down): the words change,
// the E-stop stays live. A lock never opens the account row (D-741 3): the guide strip's 관제 접속 does.
export function showSignedOut({refused = true} = {}) {
  const token = $('token-access');
  if (token) token.hidden = false;
  $('fleet-account').hidden = true;
  $('fleet-login').hidden = false;
  const tag = $("user-role");
  tag.textContent = "인증 필요";
  tag.removeAttribute("title");
  tag.setAttribute("status", "crit");
  gateEstop(refused ? null : undefined);
}

export function showFleet(fleet, robots = null) {
  $("fleet-name").textContent = fleet.name || "사이트";
  const pill = $("online-pill");
  if (!pill) return;  // 연결 수는 관제 문서에만 있다(D-741 3)
  delete pill.dataset.locked;
  // A robot answering late (link "degraded") still counts as connected on the pill.
  const linked = robots ? robots.filter(robot => robot.online || robot.link === "degraded").length : fleet.online;
  pill.textContent = `${linked}/${fleet.total}`;
  pill.setAttribute("status", fleet.online === fleet.total ? "neutral" : linked === fleet.total ? "warn" : "crit");
}

// Pages without their own state poll (설치·보정, 현장 지도, Cell) read Fleet every 5 s for the site name
// and the link word. They show no robot count.
export function watchFleet(request, {every = 5000, interval = setInterval} = {}) {
  async function read() {
    let state;
    try { state = await request("/api/fleet/state"); } catch (error) { return noteLink(error); }
    noteLink();
    try { showFleet(state.fleet, state.robots); } catch { /* a paint error after an answer is not a lost link */ }
  }
  read();
  return interval(read, every);
}

export function tickClock() {
  const now = Date.now();
  $("clock").textContent = new Date(now).toTimeString().slice(0, 8);
  paintLink(now);  // 답이 끊긴 채 시간이 가면 이 틱이 지연으로 바꾼다
}

export function stopNotice(message = "", state = "warning") {
  const notice = $("estop-feedback");
  notice.textContent = message;
  notice.hidden = !message;
  notice.setAttribute("state", state);
}

// D-413/D-414 — one press, no confirmation, the same words on every document. `life` lets a page drop a
// result that arrives after its scope changed; `log` and `after` are the console's extra bookkeeping.
export function bindEstop(request, {listen = (node, type, fn) => node.addEventListener(type, fn),
  life = () => ({check() {}}), log = () => {}, after = async () => {}} = {}) {
  listen($("estop"), "click", async () => {
    const task = life();
    task.check();
    stopNotice("비상 정지 요청 중…", "pending");
    try {
      const result = await request("/api/fleet/estop", {method: "POST"});
      task.check();
      const summary = result.total > 0
        ? `정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`
        : "정지 요청 대상 로봇 없음 — 등록 목록과 현장 상태를 확인하세요.";
      stopNotice(summary, result.total > 0 && result.stopped === result.total ? "warning" : "error");
      log(summary, "bad");
      (result.robots || []).filter(robot => !robot.stopped)
        .forEach(robot => log(`  ${robot.robot_id} 정지 요청 응답 없음 — ${robot.error?.code}`, "bad"));
      await after();
    } catch (error) {
      if (error.name === "AbortError") return;
      stopNotice(error.status >= 500 || !error.status
        ? "비상 정지 결과 확인 불가 — Fleet 연결과 로봇 상태를 즉시 확인하세요."
        : `비상 정지 요청 거절 — ${error.message}`, "error");
      log(`전체 정지 실패 — ${error.message}`, "bad");
    }
  });
}
