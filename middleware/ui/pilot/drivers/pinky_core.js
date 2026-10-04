// Pinky CORE 드라이버(D-323 T5). 계약: /api/v1/auth/whoami(D-193),
// /api/v1/system/capabilities(v1.21 runtime.truth), /api/v1/mode,
// /api/v1/safety/stop. 순수 판정 함수 assessGate 과 경로 액션만 둔다.

export const KIND = "pinky_core";

const OPERATOR_RANK = {viewer: 0, operator: 1, administrator: 2};

// whoami + capabilities → 조속 진입 허락 판정. 이유는 운용자 문구로 바꾸기 전의
// 원시 코드(role:·teleop_withheld:·drive_disabled)로만 낸다.
export function assessGate({role = "viewer", capabilities = {}} = {}) {
  const reasons = [];
  const rank = OPERATOR_RANK[role] ?? -1;
  if (rank < OPERATOR_RANK.operator) {
    reasons.push(`role:${role}`);
  }
  if (capabilities.teleop !== true) {
    const why = capabilities?.withheld?.reasons?.teleop;
    reasons.push(why ? `teleop_withheld:${why}` : "teleop_withheld");
  } else if (capabilities?.runtime?.drive === false) {
    // teleop 플래그가 참인데 실측 구동 증거가 거짓일 때만 별도 사유.
    // runtime 키가 아예 없는 구 서버(v1.21 이전)는 판정 불가 — 명령 시점의
    // 409(CAPABILITY_WITHHELD)가 안전벨트다.
    reasons.push("drive_disabled");
  }
  return {allowed: reasons.length === 0, reasons};
}

// 게이트 사유 원시 코드 → 운용자 문구. CORE 의 정지이듯 보류도 사실만 말한다.
export function describeReason(code) {
  if (code.startsWith("role:")) {
    return `운전 권한이 없습니다 (현재 역할: ${code.slice(5)})`;
  }
  if (code.startsWith("teleop_withheld:")) {
    return `수동 운전이 보류되었습니다 — ${code.slice("teleop_withheld:".length)}`;
  }
  if (code === "teleop_withheld") {
    return "수동 운전이 보류되었습니다";
  }
  if (code === "drive_disabled") {
    return "구동이 꺼져 있습니다 (무동작)";
  }
  return `진입할 수 없습니다 — ${code}`;
}

// 조작 프로필: 화면이 어떤 조작부를 그릴지 정한다. 주행 기기(base)는 2 축 속도
// 명령(REST teleop, hold-to-drive)이고 제자리 회전·정밀 배율을 지원한다.
// 팔(arm) 프로필의 모양은 설계 문서 §10 — 그 기기의 조그 계약이 열릴 때 등록한다.
export const PROFILE = Object.freeze({
  kind: "base",
  command: "velocity",
  pivot: true,
  fine: true,
  autonomy: ["line"],          // D-344: 누르는 동안만 가는 카메라 차선 추종
});

export const pinkyCore = {
  kind: KIND,
  profile: PROFILE,
  assessGate,
  describeReason,
  // engage/disengage: 조속 화면 진입·이탈의 모드 전환. 실패(409 MODE_CONFLICT 등)는
  // 호출자(link/app)가 이유를 표시한다.
  engage: (post) => post("/api/v1/mode", {mode: "MANUAL"}),
  disengage: (post) => post("/api/v1/mode", {mode: "IDLE"}),
  // e-stop: 소프트웨어 정지(triage 규칙 — 전원 차단으로 말하지 않는다).
  stop: (post) => post("/api/v1/safety/stop", {}),
};
