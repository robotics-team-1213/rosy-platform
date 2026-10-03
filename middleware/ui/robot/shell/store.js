// 패널이 서버 상태를 받는 유일한 창구(D-204 §4).
// S1은 폴링만 싣는다. 공유 WebSocket 구독(select)은 운용 화면을 옮길 때 이 파일에 더한다.
// scope 하나가 패널 하나다. 패널이 내려가면 셸이 scope를 닫아 남은 타이머와 늦은 응답을 끊는다.

export function createStore(api) {
  return {
    scope() {
      const timers = new Set();
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
        stopAll() {
          closed = true;
          timers.forEach(clearInterval);
          timers.clear();
        },
      };
    },
  };
}
