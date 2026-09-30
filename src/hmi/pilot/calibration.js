// 보정 세션 표시(D-321 부록). 상태 스냅샷의 `activity` 와 이 기기의 토큰 id(/auth/whoami)만으로
// 무엇을 보여 주고 무엇을 잠글지 정한다. 화면 배선은 screens/drive.js.
// 잠금은 표시일 뿐이다 — 최종 판정은 CORE 의 409 CALIBRATION_ACTIVE 이고, 비상 정지는 잠그지 않는다.

const IDLE = Object.freeze({active: false, locked: false, text: "", reason: "", remaining: null});

// identityPending: /auth/whoami 가 아직 답하지 않았다. 주인일 수도 있으니 "남의 보정"이라고 단정하지
// 않고 "보정 확인 중"으로 잠근다 — 잠금은 그대로(닫힌 실패), 사유만 다르다.
export function calibrationView(activity, myId, identityPending = false) {
  if (!activity || activity.kind !== "CALIBRATING") return IDLE;
  const label = String(activity.label ?? "").trim() || "보정";
  const owner = activity.owner ?? {};
  const mine = Boolean(myId) && owner.id === myId;
  const who = String(owner.label ?? "").trim() || String(owner.role ?? "").trim() || "다른 조종자";
  const remaining = Number(activity.remaining_s);
  return {
    active: true,
    locked: !mine,
    text: `보정 중 — ${label}`,
    reason: mine
      ? "이 기기가 보정 세션을 쥐고 있습니다"
      : identityPending && !myId
        ? "보정 확인 중 — 이 기기가 보정 주인인지 확인하고 있습니다 · 비상 정지는 그대로 됩니다"
        : `${who} 쪽에서 보정 중이라 주행 조작을 잠갔습니다 · 비상 정지는 그대로 됩니다`,
    remaining: Number.isFinite(remaining) ? Math.max(0, Math.round(remaining)) : null,
  };
}
