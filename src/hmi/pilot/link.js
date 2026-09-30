// Rosy Pilot DeviceSession(D-323 T4). 상태 WS(/ws/state, 첫 메시지 auth)와
// REST teleop(hold-to-drive)를 하나의 세션 상태머신으로 묶는다.
// DOM·fetch·WebSocket 을 모른다 — 전부 주입받아 Node 순수 시험이 가능하다.
//
// 상태: CONNECTING → OPEN → (close) RETRYING|FORBIDDEN|OFFLINE|BLOCKED
//  - 4403: 재시도 없음(권한 없음)  4401: whoami 재확인 후 재접속(거부면 OFFLINE)
//  - 그 외 close: 백오프 1s→30s. 연결 성공(첫 스냅샷)마다 백오프 리셋.
//  - close() 뒤에는 어떤 재접속도 하지 않는다.
//
// 조종 차단은 두 가지이며 서로를 풀지 않는다.
//  - 가림(hidden): 탭 이탈. visible() 로만 풀린다.
//  - 충돌(409): CORE 가 거절했다. 수동 모드를 다시 잡은 뒤 resume() 로만 풀린다.

export const SEND_INTERVAL_MS = 100;   // hold-to-drive 명령 주기(하한)
export const IDLE_ZERO_REPEATS = 3;    // 놓은 뒤 0 을 몇 번 보내고 조용해지나(늦게 도착한 움직임을 덮는다)
// teleop 한 건의 시한. CORE 워치독(500ms)보다 짧아야 한 요청이 멈춰도 다음 명령이
// 워치독 전에 나간다. 끊긴 요청은 다음 틱이 최신 명령으로 대신한다. 시한 + 왕복이
// 500ms 를 넘으면 로봇이 잠깐 서는 쪽으로 실패한다(의도된 안전 방향).
export const POST_TIMEOUT_MS = 400;
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
  onLatency = () => {},
} = {}) {
  let state = "IDLE";
  let failures = 0;
  let closed = false;          // close() 뒤 — 재접속·상태 알림을 모두 멈춘다
  let hiddenBlock = false;     // 탭 이탈로 조종 차단
  let conflictBlock = false;   // 409 로 조종 차단
  let lastSentAt = -Infinity;  // 발행 **시작** 시각. 응답 시각으로 재면 지연만큼 주기가 늘어난다.
  let lastWasMotion = false;   // 마지막 발행이 0 이 아닌 명령인가
  let zeroStreak = 0;          // 연속으로 보낸 0 의 수(유휴 중 감사 로그·manual_active 도배 방지)
  let flights = 0;             // 날아가는 요청 수. 평소엔 0/1, zero() 가 끼어들 때만 2
  let motionFlights = 0;       // 그중 움직임 명령의 수
  let zeroAfterFlight = false; // 움직임이 날아가는 중에 0 이 요청됐다 — 그 움직임이 끝나면 0 을 다시 덮는다
  let pending = null;          // 스로틀·비행 중 때문에 늦춰진 최신 명령(가장 최신 것만 남긴다)
  let pendingTimer = null;
  let socket = null;

  const blocked = () => hiddenBlock || conflictBlock;

  function setState(next) {
    if (closed) return;
    state = next;
    onState(next);
  }

  function connect() {
    if (closed) return;
    setState("CONNECTING");
    socket = openSocket(url);
    socket.onopen = () => {
      socket?.send(JSON.stringify({type: "auth", token}));
    };
    socket.onmessage = (event) => {
      let frame = null;
      try {
        frame = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (state === "CONNECTING" || state === "RETRYING") {
        failures = 0;          // 인증이 통과하고 첫 스냅샷이 왔다 = 연결 성공
        setState(conflictBlock ? "BLOCKED" : "OPEN");
      }
      onSnapshot(frame);
    };
    socket.onclose = (event) => {
      if (closed) return;
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
    if (closed) return;
    if (lastWasMotion) post({linear: 0, angular: 0});   // 소켓 상실 시 벨트 0 발행
    setState("RETRYING");
    const delay = Math.min(MIN_BACKOFF_MS * 2 ** failures, MAX_BACKOFF_MS);
    failures += 1;
    schedule(connect, delay);
  }

  function isZero(command) {
    return command.linear === 0 && command.angular === 0;
  }

  async function post(command) {
    const startedAt = now();
    const motion = !isZero(command);
    lastSentAt = startedAt;
    lastWasMotion = motion;
    zeroStreak = motion ? 0 : zeroStreak + 1;
    flights += 1;
    if (motion) motionFlights += 1;
    let response = null;
    let failed = false;
    try {
      response = await postJson("/api/v1/teleop", command, {timeoutMs: POST_TIMEOUT_MS});
    } catch (error) {
      failed = true;             // 시한 초과·네트워크 오류 — 다음 틱이 다시 보낸다
    } finally {
      flights -= 1;
      if (motion) motionFlights -= 1;
    }
    onLatency(now() - startedAt, failed);
    if (failed && !motion) zeroStreak = Math.max(0, zeroStreak - 1);  // 못 간 0 은 세지 않는다
    if (response && response.status === 409) {
      const detail = response.body?.detail ?? response.body ?? {};
      conflictBlock = true;
      zeroAfterFlight = false;
      clearPending();
      setState("BLOCKED");
      onConflict(detail);
      return response;
    }
    if (motion && zeroAfterFlight && motionFlights === 0) {
      // 먼저 떠난 움직임이 방금 끝났다 — 서버에 0 보다 늦게 닿았을 수 있으니 0 으로 덮는다.
      zeroAfterFlight = false;
      clearPending();
      return post({linear: 0, angular: 0});
    }
    if (pending && flights === 0) armPending();
    return response;
  }

  function armPending() {
    if (pendingTimer) return;
    const wait = Math.max(0, SEND_INTERVAL_MS - (now() - lastSentAt));
    pendingTimer = schedule(flushPending, wait) ?? true;
  }

  function flushPending() {
    pendingTimer = null;
    if (blocked()) {
      pending = null;
      return;
    }
    if (!pending || flights > 0) return;   // 비행이 끝나면 post() 가 다시 건다
    const command = pending;
    pending = null;
    post(command);
  }

  function clearPending() {
    pending = null;
    if (typeof pendingTimer === "function") pendingTimer();
    pendingTimer = null;
  }

  return {
    open() {
      closed = false;
      connect();
    },
    async command({linear = 0, angular = 0} = {}) {
      if (blocked() || state === "FORBIDDEN" || closed) return null;
      const next = {linear, angular};
      if (isZero(next) && !lastWasMotion && zeroStreak >= IDLE_ZERO_REPEATS && flights === 0) {
        return null;           // 놓은 상태가 이미 전달됐다 — 유휴 중엔 보내지 않는다
      }
      if (flights > 0 || now() - lastSentAt < SEND_INTERVAL_MS) {
        pending = next;
        if (flights === 0) armPending();
        return null;
      }
      return post(next);
    },
    zero() {
      // 정지는 스로틀·비행 중을 기다리지 않는다.
      clearPending();
      if (motionFlights > 0) zeroAfterFlight = true;
      return post({linear: 0, angular: 0});
    },
    close() {
      closed = true;
      clearPending();
      if (socket) {
        socket.onopen = socket.onmessage = socket.onclose = null;
        try { socket.close(); } catch (error) { /* 이미 닫혔다 */ }
      }
      socket = null;
      state = "IDLE";
    },
    hidden() {
      // 탭 이탈: 즉시 0 발행 + 조종 차단. 재개는 visible() 로만.
      hiddenBlock = true;
      return this.zero();
    },
    visible() {
      hiddenBlock = false;     // 409 충돌 차단은 여기서 풀지 않는다
    },
    // 409 로 막힌 뒤 운용자가 수동 모드를 다시 잡았을 때만 부른다. 탭 가림은 풀지 않는다.
    resume() {
      conflictBlock = false;
      zeroStreak = 0;
      if (state === "BLOCKED") setState(socket ? "OPEN" : "IDLE");
    },
    blocked,
    state: () => state,
  };
}
