// 패널이 서버 상태를 받는 유일한 창구(D-204 §4).
// D-447 (b): 상태 스트림은 이미 열린 소켓을 재사용한다. scope().state()가
// /ws/state 구독으로 답하고(토큰은 첫 메시지로만, D-193), 소켓이 죽으면 그 범위가
// REST 폴링으로 돌아간다. 나머지 경로는 여전히 poll()이다. scope 하나가 패널 하나다.
// 패널이 내려가면 셸이 scope를 닫아 남은 타이머·늦은 응답·구독을 끊는다.

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const RECONNECT_STABLE_MS = 10000;
const FALLBACK_POLL_MS = 1000;

export function createStore(api, deps = {}) {
  const session = deps.session ?? null;
  const onUnauthorized = deps.onUnauthorized ?? (() => {});
  const openSocket = deps.createSocket ?? ((url) => new WebSocket(url));
  const statePath = deps.statePath ?? "/api/v1/robot/state";
  const socketUrl = deps.socketUrl ?? (() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.host}/ws/state`;
  });
  const fallbackPollMs = deps.fallbackPollMs ?? FALLBACK_POLL_MS;
  const reconnectMinMs = deps.reconnectMinMs ?? RECONNECT_MIN_MS;
  const reconnectMaxMs = deps.reconnectMaxMs ?? RECONNECT_MAX_MS;

  const subscribers = new Set();
  let socket = null;
  let socketLive = false;
  let reconnectTimer = null;
  let fallbackTimer = null;
  let stableTimer = null;
  let reconnectDelayMs = reconnectMinMs;

  function deliver(data) { subscribers.forEach((s) => s.onData(data)); }
  function deliverError(error) { subscribers.forEach((s) => s.onError?.(error)); }

  function stopFallback() {
    clearInterval(fallbackTimer);
    fallbackTimer = null;
  }

  async function fallbackTick() {
    try {
      deliver(await api(statePath, { signal: AbortSignal.timeout(Math.max(fallbackPollMs * 2, 5_000)) }));
    } catch (error) {
      deliverError(error);
    }
  }

  function startFallback() {
    if (fallbackTimer || !subscribers.size) return;
    fallbackTimer = setInterval(fallbackTick, fallbackPollMs);
    fallbackTick();
  }

  function closeSocket() {
    const current = socket;
    socket = null;
    socketLive = false;
    clearTimeout(stableTimer);
    stableTimer = null;
    current?.close();
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    const delay = reconnectDelayMs;
    reconnectDelayMs = Math.min(delay * 2, reconnectMaxMs);
    const jitter = Math.round(delay * 0.2 * Math.random());
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (subscribers.size) connect();
    }, delay + jitter);
  }

  function stopAllStreams() {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    stopFallback();
    closeSocket();
    reconnectDelayMs = reconnectMinMs;
  }

  // 4401 은 토큰이 없거나 틀렸거나 끊겼다는 뜻이다. REST 에게 묻는다: 401 이면
  // 세션 종료, 그 외에는 뒤로 물러났다가 다시 시도한다(state-socket.js 와 같은 규칙).
  async function verifyAfterRefusal() {
    const token = session?.token;
    try {
      await api("/api/v1/auth/whoami", { signal: AbortSignal.timeout(5_000) });
    } catch (error) {
      if (error?.status === 401 && token === session?.token && subscribers.size) {
        onUnauthorized(error);
        return;
      }
    }
    if (subscribers.size && token === session?.token) scheduleReconnect();
  }

  function connect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    closeSocket();
    if (!subscribers.size || !session?.token) return;
    // D-193 10: 토큰은 첫 메시지로만 간다. URL 에는 절대 넣지 않는다.
    const live = openSocket(socketUrl());
    socket = live;
    live.addEventListener("open", () => {
      if (live !== socket || !session?.token) return;
      live.send(JSON.stringify({ type: "auth", token: session.token }));
    });
    live.addEventListener("message", (event) => {
      if (live !== socket) return;
      if (!socketLive) {
        socketLive = true;
        stableTimer = setTimeout(() => {
          if (live === socket) reconnectDelayMs = reconnectMinMs;
        }, RECONNECT_STABLE_MS);
        stopFallback();
      }
      try { deliver(JSON.parse(event.data)); }
      catch (_error) { deliverError(new Error("state frame parse failed")); }
    });
    live.addEventListener("close", (event) => {
      if (live !== socket) return;
      socket = null;
      socketLive = false;
      clearTimeout(stableTimer);
      stableTimer = null;
      if (!subscribers.size) return;
      startFallback();
      if (event.code === 4401) verifyAfterRefusal();
      else if (event.code === 4403) {
        // 인증은 됐지만 이 스트림은 아니라는 뜻: 다시 시도해도 바뀌지 않는다.
        reconnectDelayMs = reconnectMinMs;
      } else scheduleReconnect();
    });
  }

  return {
    scope() {
      const timers = new Set();
      const entries = new Set();
      let closed = false;
      return {
        poll(path, intervalMs, onData, onError = () => {}) {
          let stopped = false;
          let pending = false;
          const live = () => !stopped && !closed;
          const tick = () => {
            if (pending) return;
            pending = true;
            api(path, { signal: AbortSignal.timeout(Math.max(intervalMs * 2, 5_000)) }).then(
              (data) => { if (live()) onData(data); },
              (error) => { if (live()) onError(error); },
            ).finally(() => { pending = false; });
          };
          tick();
          const timer = setInterval(tick, intervalMs);
          timers.add(timer);
          return () => {
            stopped = true;
            clearInterval(timer);
            timers.delete(timer);
          };
        },
        state(onData, onError = () => {}) {
          const entry = { onData, onError };
          entries.add(entry);
          subscribers.add(entry);
          // 구독자가 없어 꺼져 있으면 소켓을 연다. 재접속 대기 중이었다면 즉시 잡는다.
          // 4403 으로 재시도를 포기한 뒤에는 REST 폴밍을 그대로 나눠 쓴다.
          if (!socket && !reconnectTimer) connect();
          return () => {
            entries.delete(entry);
            subscribers.delete(entry);
            if (!subscribers.size) stopAllStreams();
          };
        },
        stopAll() {
          closed = true;
          timers.forEach(clearInterval);
          timers.clear();
          entries.forEach((entry) => subscribers.delete(entry));
          entries.clear();
          if (!subscribers.size) stopAllStreams();
        },
      };
    },
  };
}
