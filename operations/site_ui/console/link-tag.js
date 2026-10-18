// D-499. The caller passes the server `link` word. Unknown words render nothing.

const TAGS = {
  unreachable: { word: "닿지 않음", kind: "crit", text: null, next: "다음: 주소 확인", focus: null },
  moved: { word: "주소 이동", kind: "warn", text: null, next: null, focus: null },
  degraded: { word: "응답 지연", kind: "warn", text: "로봇이 잠시 답하지 않습니다. 10초 넘게 이어지면 닿지 않음으로 바뀝니다.", next: null, focus: null },
  "tls-refused": {
    word: "인증 거부", kind: "warn",
    text: "포트는 응답하고 토큰이 거절됐습니다. 망 수리가 아닙니다.",
    next: "다음: 관제 토큰", focus: "console-token",
  },
  protocol: {
    word: "프로토콜", kind: "warn",
    text: "등록된 base URL의 스킴으로 로봇 HTTP가 끝나지 않습니다.",
    next: "다음: 등록된 Fleet base URL", focus: null,
  },
};

export function linkTag(link) {
  return Object.prototype.hasOwnProperty.call(TAGS, link) ? TAGS[link] : null;
}

// D-550 8 / D-760 3: why Fleet's verdict (`rule_m`) calls a motion unbounded. Warn only.
const RULE_M_REASON = {
  hold_back: "차로 통행권·운행 임대 없음",
  no_goal_lease: "목표 임대 없음",
  leg_unknown: "운행 구간 모름",
};

// The mark beside the card's link tag, or null when the motion is bounded or nothing moves.
export function ruleMTag(rule) {
  if (rule?.state !== "unbounded") return null;
  const reason = Object.prototype.hasOwnProperty.call(RULE_M_REASON, rule.reason) ? RULE_M_REASON[rule.reason] : "이유 모름";
  return { word: "정지 한도 없음", kind: "warn", text: `관제가 끊겨도 로봇이 계속 갑니다 (${reason})` };
}
