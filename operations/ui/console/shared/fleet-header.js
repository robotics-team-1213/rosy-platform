// D-540 2 — the one Rosy Fleet header. 관제·설치·보정·현장 지도·Cell carry the same <ui-topbar> markup
// (test_fleet_header.py pins it) and drive it only through this module: role words, development badge,
// connection count, clock, the settings fold and the one E-stop rule. Each page keeps its own session probe.
import {OPERATOR_REASON} from "/console/assets/authorization.js";

export const SESSION_REASON = "접속이 필요합니다";
const ROLE = {operator: "운영자", viewer: "보기 전용", "policy-admin": "정책 관리자"};
const $ = id => document.getElementById(id);

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

// The fold opens itself when access is lost (the token field is inside) and closes again only if it did so.
let openedForLock = false;
export function setTopbarOpen(open) {
  $("topbar-more").setAttribute("aria-expanded", String(open));
  $("topbar-extra").dataset.open = String(open);
}
export function bindTopbarToggle(listen = (node, type, fn) => node.addEventListener(type, fn)) {
  listen($("topbar-more"), "click", () => {
    openedForLock = false;
    setTopbarOpen($("topbar-more").getAttribute("aria-expanded") !== "true");
  });
}

// English role names and principal ids stay in title (D-540 2); a development session says so with its badge.
export function showSession(identity) {
  const tag = $("user-role"), development = identity.principal_id.startsWith("development-");
  tag.textContent = development ? roleLabel(identity.role) : `${identity.principal_id} · ${roleLabel(identity.role)}`;
  tag.title = `${identity.principal_id} · ${identity.role}`;
  tag.setAttribute("status", identity.role === "operator" ? "good" : "neutral");
  if (development) $("development-badge").hidden = false;
  gateEstop(identity);
  if (openedForLock) setTopbarOpen(false);
  openedForLock = false;
}

// `refused` is false when the session probe failed for another reason (Fleet down): the words change,
// the E-stop stays live. `fold` is false on 관제, whose connection view owns the fold.
export function showSignedOut({fold = true, refused = true} = {}) {
  const tag = $("user-role");
  tag.textContent = "인증 필요";
  tag.removeAttribute("title");
  tag.setAttribute("status", "crit");
  gateEstop(refused ? null : undefined);
  if (fold && $("topbar-more").getAttribute("aria-expanded") !== "true") {
    setTopbarOpen(true);
    openedForLock = true;
  }
}

export function showFleet(fleet, robots = null) {
  $("fleet-name").textContent = fleet.name || "사이트";
  const pill = $("online-pill");
  delete pill.dataset.locked;
  // A robot answering late (link "degraded") still counts as connected on the pill.
  const linked = robots ? robots.filter(robot => robot.online || robot.link === "degraded").length : fleet.online;
  pill.textContent = `${linked}/${fleet.total} 연결`;
  pill.setAttribute("status", fleet.online === fleet.total ? "neutral" : linked === fleet.total ? "warn" : "crit");
}

// Pages without their own state poll (설치·보정, 현장 지도, Cell) read the count every 5 s. A 401/403 leaves
// the pill to the page's lock words; anything else says the server is missing.
export function watchFleet(request, {every = 5000, interval = setInterval} = {}) {
  async function read() {
    try {
      const state = await request("/api/fleet/state");
      showFleet(state.fleet, state.robots);
    } catch (error) {
      if (error.name === "AbortError" || error.status === 401 || error.status === 403) return;
      const pill = $("online-pill");
      pill.textContent = "Fleet 서버 없음";
      pill.setAttribute("status", "crit");
    }
  }
  read();
  return interval(read, every);
}

export function tickClock() {
  $("clock").textContent = new Date().toTimeString().slice(0, 8);
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
