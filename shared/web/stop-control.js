// C9 createStopControl: the one stop button behaviour (D-280 principle 2, generalises data-always-live).
//   createStopControl({button, status, url = "/stop", send, accept = (response) => response.ok, timeoutMs = 5000})
//   - button: the stop ui-button. It is made visible and enabled once, here, and carries data-always-live.
//     Nothing watches it afterwards: no owner (busy-scope, account-gate, the screen) may hide or disable it, and the
//     tests fail if one does. Permission, busy, reload and account state never gate it.
//   - status: element for the result text (data-state pending | sent | error).
//   - send(signal): optional request; default is fetch(url, {method: "POST"}). It returns a Response-like {ok, status}.
//   - accept(response): true (or a promise of true, it is awaited) when that answer counts as accepted (default
//     response.ok). If accept throws or rejects the press is a failure. A caller that needs stricter
//     evidence (e.g. a body that says estop === true) returns false otherwise: that press shows failure text, never "sent".
//   Every press sends (a pending request never blocks the next one); only the newest answer is shown.
//   A server refusal (403/503) is shown as text with its reason. "sent" says the request was accepted,
//   never that anything stopped: that needs the evidence the screen already shows.
//   Returns {press, note(text, state)}. note() writes the status line for other owners (session change);
//   it never discards a stop answer still in flight: that answer is written when it arrives.
export const STOP_TEXT = Object.freeze({
  pending: "정지 요청 중",
  sent: "정지 요청 접수 · 실제 정지 확인 중",
  timeout: "정지 요청 시간 초과 · 다시 눌러 재시도하세요",
  forbidden: "정지 요청 거절 · 운용 권한 계정으로 로그인해야 합니다",
  unverified: "정지 요청 거절 · 계정 확인 불가, 다시 눌러 재시도하세요",
  failed: "정지 요청 실패 · 다시 눌러 재시도하세요",
});

export function stopFailureText(error) {
  if (error?.name === "AbortError") return STOP_TEXT.timeout;
  if (error?.status === 403) return STOP_TEXT.forbidden;
  if (error?.status === 503) return STOP_TEXT.unverified;
  return STOP_TEXT.failed;
}

export function createStopControl({button, status, url = "/stop", send, accept = (response) => response.ok, timeoutMs = 5000}) {
  let latest = 0;
  const write = (text, state) => {
    if (state !== undefined) status.dataset.state = state;
    if (status.textContent !== text) status.textContent = text;
  };
  {  // one-time normalisation of the markup the caller gave us
    button.setAttribute("data-always-live", "");
    if (button.hidden) button.hidden = false;
    if (button.disabled) button.disabled = false;
    if (button.hasAttribute("disabled")) button.removeAttribute("disabled");
    if (button.getAttribute("aria-disabled") !== "false") button.setAttribute("aria-disabled", "false");
  }
  async function press() {
    const mine = ++latest;
    write(STOP_TEXT.pending, "pending");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await (send ? send(controller.signal) : fetch(url, {method: "POST", signal: controller.signal}));
      if (!(await accept(response))) throw Object.assign(new Error(`stop ${response.status}`), {status: response.status});
      if (mine === latest) write(STOP_TEXT.sent, "sent");
    } catch (error) {
      if (mine === latest) write(stopFailureText(error), "error");
    } finally {
      clearTimeout(timer);
    }
  }
  button.addEventListener("click", press);
  return {press, note: (text, state) => { write(text, state); }};
}
