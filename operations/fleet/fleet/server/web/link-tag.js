// D-499. The caller passes the server `link` word. Unknown words render nothing.

const TAGS = {
  unreachable: { word: "닿지 않음", kind: "crit", text: null, next: "다음: 주소 확인", focus: null },
  moved: { word: "주소 이동", kind: "warn", text: null, next: null, focus: null },
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
