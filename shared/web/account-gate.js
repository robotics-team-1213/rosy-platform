// C3 createAccountGate: one account state for a screen, on top of account-session.js (D-757).
//   createAccountGate({stop, onState, poll = 10000, reload, base})
//   state: "operate" (can_operate), "signed-in" (signed in, cannot operate), "view" (read fine, no session),
//          "unavailable" (the read failed or has not finished). A failed read is never "no permission".
//   onState({state, account}) runs on every change; account is the last good read (null before the first).
//   The gate never hides the page or the stop. When another identity takes the origin it says so through
//   stop.note() and reloads; if the reload stalls, the stop stays pressable.
//   Returns {restore, dispose(), logout(), get state(), get account(), canOperate}. logout() resolves to an error text or "".
import {createAccountSession} from "./account-session.js";

export const RELOAD_NOTE = "계정이 바뀌어 다시 불러오는 중 · 정지는 계속 누를 수 있습니다";
export const LOGOUT_DELAYED = "중앙 로그아웃 처리가 지연 중입니다.";

/** Pure: the gate state of one /session body. */
export function gateState(account) {
  if (!account) return "unavailable";  // no read yet or a failed read
  if (account.can_operate === true) return "operate";
  return account.authenticated ? "signed-in" : "view";
}

export function createAccountGate({stop, onState = () => {}, poll = 10000, reload = () => window.location.reload(), base} = {}) {
  let account = null, state = "unavailable", loggingOut = false;
  const set = next => { state = next; onState({state, account}); };
  const session = createAccountSession({
    current: () => account,
    apply: value => { account = value; set(gateState(value)); },
    changed: () => { set("unavailable"); stop?.note(RELOAD_NOTE, ""); reload(); },
    failed: () => set("unavailable"),
    poll: 0, base,
  });
  // Unlike a poll that waits for an enabled session, this keeps probing after a failed first read.
  const timer = poll ? setInterval(() => { if (!loggingOut) session.restore(); }, poll) : 0;
  async function logout() {
    loggingOut = true;
    session.invalidate();
    set("unavailable");
    let failure = "";
    try {
      await session.logout(() => { account = null; }, {signal: AbortSignal.timeout(5000)});
    } catch { failure = LOGOUT_DELAYED; stop?.note(failure, "error"); }
    loggingOut = false;
    await session.restore();
    return failure;
  }
  return {restore: session.restore, logout, dispose() { clearInterval(timer); }, get state() { return state; }, get account() { return account; }, get canOperate() { return state === "operate"; }};
}
