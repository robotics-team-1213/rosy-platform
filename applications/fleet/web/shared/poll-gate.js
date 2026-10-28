// 폴링 문 — 꺼진 기능의 라우트를 매 초 404 로 두드리지 않게 한다 (2026-09-30 태블릿 점검).
// DOM 없는 순수 모듈이라 node 로 시험한다.
//
// - 라우트 없음(404 + detail.code 없음 = FastAPI 기본 "Not Found"): 이 Fleet 에 그 기능이
//   설정되지 않았다. 다음 reset()(로그인·토큰 저장) 전까지 닫는다.
// - slowCodes 에 있는 404 코드(예: NO_MAP): 기능은 있는데 아직 줄 것이 없다. 그 간격만큼 쉰다.
// - 그 밖의 실패(5xx, 네트워크, 다른 404 코드)는 일시 실패로 보고 다음 주기에 다시 묻는다.

export const NO_MAP_RETRY_MS = 30000;

export function isRouteAbsent(status, code) {
  return status === 404 && !code;
}

export function createPollGate({ slowCodes = {} } = {}) {
  let closedUntil = 0; // Infinity = 기능 미설정
  return {
    due(now = Date.now()) {
      return now >= closedUntil;
    },
    // 실패를 분류해 돌려준다: "absent" | "slow" | "retry".
    fail(status, code, now = Date.now()) {
      if (isRouteAbsent(status, code)) {
        closedUntil = Infinity;
        return "absent";
      }
      if (status === 404 && code && slowCodes[code]) {
        closedUntil = now + slowCodes[code];
        return "slow";
      }
      closedUntil = 0;
      return "retry";
    },
    ok() {
      closedUntil = 0;
    },
    reset() {
      closedUntil = 0;
    },
    get absent() {
      return closedUntil === Infinity;
    },
  };
}
