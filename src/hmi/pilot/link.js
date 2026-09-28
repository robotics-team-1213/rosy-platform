// Rosy Pilot DeviceSession(D-323 T4). 상태 WS(/ws/state, 첫 메시지 auth)와
// REST teleop(hold-to-drive)를 하나의 세션 상태머신으로 묶는다.
// DOM·fetch·WebSocket 을 모른다 — 전부 주입받아 Node 순수 시험이 가능하다.
//
// 상태: CONNECTING → OPEN → (close) RETRYING|FORBIDDEN|OFFLINE|BLOCKED
//  - 4403: 재시도 없음(권한 없음)  4401: whoami 재확인 후 재접속(거부면 OFFLINE)
//  - 그 외 close: 백오프 1s→30s. 연결 성공(첫 스냅샷)마다 백오프 리셋.

export const SEND_INTERVAL_MS = 100;   // hold-to-drive 명령 주기(하한)
export const MIN_BACKOFF_MS = 1000;
export const MAX_BACKOFF_MS = 30000;

export function createDeviceSession({
  token,
  url = "/ws/state",
  openSocket,
  schedule,
  postJson,
  whoami,
  now = () => Date.now(),
  onState = () => {},
  onSnapshot = () => {},
  onConflict = () => {},
} = {}) {
  let state = "IDLE";
  let failures = 0;
  let blocked = false;         // hidden() 또는 409 로 조종 차단
  let lastSentAt = -Infinity;
  let lastWasMotion = false;   // 마지막 발행이 0 이 아닌 명령인가
  let pending = null;          // 스로틀 때문에 늦춰진 명령
  let pendingTimer = null;

  function setState(next) {
    state = next;
    onState(next);
  }

  function connect() {
    setState("CONNECTING");
    const socket = openSocket(url);
    socket.onopen = () => {
      socket.send(JSON.stringify({type: "auth", token}));
    };
    socket.onmessage = (event) => {
      let frame = null;
      try {
        frame = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (state !== "OPEN") {
        failures = 0;          // 인증이 통과하고 첫 스냅샷이 왔다 = 연결 성공
        setState("OPEN");
      }
      onSnapshot(frame);
    };
    socket.onclose = (event) => {
      const code = event?.code ?? 0;
      if (code === 4403) {
        setState("FORBIDDEN");
        return;
      }
      if (code === 4401) {
        // 토큰이 회수·만료됐다. 재확인 없이 재접속하면 4401 이 반복된다.
        Promise.resolve()
          .then(() => whoami())
          .then(() => retry())
          .catch(() => setState("OFFLINE"));
        return;
      }
      retry();
    };
  }

  function retry() {
    if (lastWasMotion) post({linear: 0, angular: 0});   // 소켓 상실 시 벨트 0 발행
    setState("RETRYING");
    const delay = Math.min(MIN_BACKOFF_MS * 2 ** failures, MAX_BACKOFF_MS);
    failures += 1;
    schedule(connect, delay);
  }

  async function post(command) {
    const response = await postJson("/api/v1/teleop", command);
    lastSentAt = now();
    lastWasMotion = command.linear !== 0 || command.angular !== 0;
    if (response && response.status === 409) {
      const detail = response.body?.detail ?? response.body ?? {};
      blocked = true;
      setState("BLOCKED");
      onConflict(detail);
    }
    return response;
  }

  function flushPending() {
    if (!pending || blocked) {
      pending = null;
      return;
    }
    const command = pending;
    pending = null;
    post(command);
  }

  return {
    open() {
      connect();
    },
    async command({linear = 0, angular = 0} = {}) {
      if (blocked || state === "FORBIDDEN") return null;
      if (now() - lastSentAt < SEND_INTERVAL_MS) {
        pending = {linear, angular};
        pendingTimer = schedule(flushPending, SEND_INTERVAL_MS);
        return null;
      }
      return post({linear, angular});
    },
    zero() {
      pending = null;
      return post({linear: 0, angular: 0});
    },
    hidden() {
      // 탭 이탈: 즉시 0 발행 + 조종 차단. 재개는 visible() 로만.
      blocked = true;
      this.zero();
    },
    visible() {
      blocked = false;
    },
    state: () => state,
  };
}
