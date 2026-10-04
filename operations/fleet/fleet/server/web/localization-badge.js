// D-395 P2-6 — 로봇 카드의 위치 확정 배지. 서버가 준 row.localization(문구 포함)을
// 태그 어휘로 옮긴다: 확정은 중립, 미확정·미보고는 warn, 사람 확인 필요는 crit.
// DOM 없는 순수 함수만 둔다(node 시험 대상).

export function localizationTag(loc) {
  if (!loc) return null;
  const cls = loc.needs_human ? "crit" : loc.legacy || !loc.trusted ? "warn" : "";
  const title = loc.legacy ? "localization: null" : `${loc.state} · ${loc.pose_frame}`;
  return { text: loc.label, cls, title };
}

export function localizationUrgent(loc) {
  return Boolean(loc && loc.needs_human);
}

export function untrustedQueuedReason(who) {
  return `${who} 위치를 확인할 수 없어 대기 중 — 위치가 확정되거나 경로에서 멀어지면 자동 출발합니다`;
}
