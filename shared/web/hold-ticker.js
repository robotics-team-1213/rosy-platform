// 홀드-티커 headless (D-250). 누르고 있는 동안 intervalMs마다 onTick 을
// 부르고, 놓으면 interval 을 걷은 뒤 onZero 를 한 번 부른다. 자격 판단·
// 전송·속도 매핑·UI를 모른다 — 그것은 표면의 계약이다. 시각 0, DOM 0.

export function createHoldTicker({ intervalMs, onTick, onZero }) {
  if (!Number.isFinite(intervalMs) || intervalMs <= 0) {
    throw new Error("hold ticker needs a positive intervalMs");
  }
  if (typeof onTick !== "function" || typeof onZero !== "function") {
    throw new Error("hold ticker needs onTick and onZero");
  }
  let timer = null;
  return {
    get active() {
      return timer !== null;
    },
    start() {
      if (timer !== null) return false;
      // 즉시 tick 은 interval 등록 뒤에 돈다 — 그래야 tick 안에서
      // active 를 읽는 전송 가드(대시보드 transmitTeleop)가 통과한다.
      // tick 이 던지면 고아 interval 을 남기지 않는다.
      timer = setInterval(onTick, intervalMs);
      try {
        onTick();
      } catch (error) {
        clearInterval(timer);
        timer = null;
        throw error;
      }
      return true;
    },
    stop(flag) {
      if (timer === null) return false;
      clearInterval(timer);
      timer = null;
      onZero(flag);
      return true;
    },
  };
}
