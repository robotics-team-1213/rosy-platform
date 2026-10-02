// 상태 스트림 소켓과 재접속 후퇴(backoff). app.js에서 분리된 모듈(D-362 P1).
// 팩토리가 셸 콜백만 받는다: onState(상태 렌더), poll(REST 폴링, 오류 처리 포함),
// onUnauthorized(401 세션 종료). 토큰은 첫 메시지로만 간다(D-193 10).
import { api, session, setConnection } from "./client.js";

export function createStateSocket({ onState, poll, onUnauthorized }) {
  // Reconnect backoff. It grows on every close and resets only once a socket has
  // stayed live for RECONNECT_STABLE_MS, so a server that accepts, sends one frame
  // and closes (4401, 1013, a restart loop) never gets a hot loop.
  const RECONNECT_MIN_MS = 1000;
  const RECONNECT_MAX_MS = 30000;
  const RECONNECT_STABLE_MS = 10000;

  function closeStateSocket() {
    const socket = session.socket;
    session.socket = null;
    session.socketLive = false;
    clearTimeout(session.stableTimer);
    session.stableTimer = null;
    socket?.close();
  }

  function stop() {
    clearTimeout(session.reconnectTimer);
    session.reconnectTimer = null;
    clearInterval(session.fallbackTimer);
    session.fallbackTimer = null;
    closeStateSocket();
  }

  function startRestFallback() {
    if (session.fallbackTimer) return;
    setConnection("error", "REST 폴링 전환");
    session.fallbackTimer = setInterval(poll, 2000);
  }

  function scheduleReconnect() {
    clearTimeout(session.reconnectTimer);
    const delay = session.reconnectDelayMs;
    session.reconnectDelayMs = Math.min(delay * 2, RECONNECT_MAX_MS);
    const jitter = Math.round(delay * 0.2 * Math.random());
    session.reconnectTimer = setTimeout(() => {
      session.reconnectTimer = null;
      if (session.token && !session.socket) connect();
    }, delay + jitter);
  }

  // 4401 means the token is missing, wrong, revoked, logged out or expired, or the
  // first message came too late. Ask REST which: 401 there ends the session,
  // anything else is retried with backoff.
  async function verifyAfterSocketRefusal() {
    try {
      await api("/api/v1/auth/whoami");
    } catch (error) {
      if (error.status === 401) {
        onUnauthorized();
        return;
      }
    }
    if (session.token) scheduleReconnect();
  }

  function connect() {
    // REST polling, if running, keeps going until the new socket delivers state.
    clearTimeout(session.reconnectTimer);
    session.reconnectTimer = null;
    closeStateSocket();
    if (!session.token) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    // D-193 10: the token goes in the first message, never in the URL.
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/state`);
    session.socket = socket;
    socket.addEventListener("open", () => {
      if (socket !== session.socket || !session.token) return;
      socket.send(JSON.stringify({ type: "auth", token: session.token }));
    });
    socket.addEventListener("message", (event) => {
      if (socket !== session.socket) return;
      if (!session.socketLive) {
        session.socketLive = true;
        session.stableTimer = setTimeout(() => {
          if (socket === session.socket) session.reconnectDelayMs = RECONNECT_MIN_MS;
        }, RECONNECT_STABLE_MS);
        clearInterval(session.fallbackTimer);
        session.fallbackTimer = null;
        setConnection("online", "값 수신 중");
      }
      try { onState(JSON.parse(event.data)); } catch (_error) { setConnection("error", "상태 해석 실패"); }
    });
    socket.addEventListener("close", (event) => {
      if (socket !== session.socket) return;
      session.socket = null;
      session.socketLive = false;
      clearTimeout(session.stableTimer);
      session.stableTimer = null;
      if (!session.token) return;
      startRestFallback();
      if (event.code === 4401) {
        verifyAfterSocketRefusal();
      } else if (event.code === 4403) {
        // Authenticated but not allowed: retrying cannot change that.
        setConnection("error", "상태 스트림 권한 없음 · REST 폴링");
      } else {
        // 1013 (first-message slots full) arrives as 1006 before accept; both wait.
        scheduleReconnect();
      }
    });
  }

  return { connect, stop, startRestFallback };
}
