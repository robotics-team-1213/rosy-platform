// D-493 — 예외 큐 신선도. 서버가 준 state_age_s(수집 시점까지의 나이)에 브라우저가 받은 뒤
// 흐른 시간을 더한다. 서버와 브라우저 시계 차는 쓰지 않는다(gathered_at 은 표시용).
export const STALE_STATE_S = 5;

// 오래됐으면 나이(초), 아니면 null. 오프라인·옛 Fleet(필드 없음)은 null.
export function staleAgeS(robot, receivedAtMs, nowMs) {
  if (!robot.online || typeof robot.state_age_s !== "number") return null;
  const age = robot.state_age_s + Math.max(0, nowMs - (receivedAtMs ?? nowMs)) / 1000;
  return age > STALE_STATE_S ? Math.round(age) : null;
}

// 지금 나이(초). stale 판정과 관계없이 값이 필요한 표시(카드·요약 상태 나이)가 쓴다. 모르면 null.
export function stateAgeS(robot, receivedAtMs, nowMs) {
  if (typeof robot.state_age_s !== "number") return null;
  return Math.round(robot.state_age_s + Math.max(0, nowMs - (receivedAtMs ?? nowMs)) / 1000);
}

// 오프라인 로봇의 「마지막 응답」 문구. 마지막 상태 ts(state.ts, 초)가 없으면 '응답 없음'.
export function lastSeenText(robot, nowMs) {
  const ts = robot.state?.ts;
  if (typeof ts !== "number" || ts <= 0) return "응답 없음";
  const age = Math.max(0, Math.floor(nowMs / 1000 - ts));
  return age < 60 ? `마지막 응답: ${age}초 전`
    : age < 3600 ? `마지막 응답: ${Math.floor(age / 60)}분 전`
    : `마지막 응답: ${Math.floor(age / 3600)}시간 전`;
}
