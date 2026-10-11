// D-493 — 예외 큐 신선도. 서버가 준 state_age_s(수집 시점까지의 나이)에 브라우저가 받은 뒤
// 흐른 시간을 더한다. 서버와 브라우저 시계 차는 쓰지 않는다(gathered_at 은 표시용).
export const STALE_STATE_S = 5;

// 오래됐으면 나이(초), 아니면 null. 오프라인·옛 Fleet(필드 없음)은 null.
export function staleAgeS(robot, receivedAtMs, nowMs) {
  if (!robot.online || typeof robot.state_age_s !== "number") return null;
  const age = robot.state_age_s + Math.max(0, nowMs - (receivedAtMs ?? nowMs)) / 1000;
  return age > STALE_STATE_S ? Math.round(age) : null;
}
