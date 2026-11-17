// 개요 목록 정렬(R-b): 종류 묶음 안에서 문제 로봇이 먼저, 같은 등급 안에서는 API 순서(안정 정렬).
// 문제 기준은 옛 #roster 정렬(roster.needsAttention)을 그대로 쓰고, 팔(robot 없음)은 연결 상태·경보로 본다.
export function overviewProblem(entry, needsAttention) {
  if (entry.robot) return Boolean(needsAttention(entry.robot));
  const link = entry.profile?.link?.state;
  return Boolean(entry.profile?.alarm) || link === "disconnected" || link === "unavailable" || link === "delayed";
}

export function sortProblemsFirst(entries, needsAttention) {
  return entries
    .map((entry, i) => [entry, i, overviewProblem(entry, needsAttention) ? 0 : 1])
    .sort((a, b) => a[2] - b[2] || a[1] - b[1])
    .map(([entry]) => entry);
}
