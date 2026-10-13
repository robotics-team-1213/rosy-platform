# OpenCode 무료 모델의 제한 합성 시험

목적은 AI PC의 실제 OpenCode 연결을 확인하는 것이다. Fleet 활성화·로봇 명령·정답 평가·무료 청구 수용은 범위에 없다.

- 첫 대상은 `opencode/mimo-v2.6-flash-free`이며 `/inference/v1/chat/completions`만 허용한다. Muse의 Responses 경로는 이번 시험에 추가하지 않는다.
- 고정 합성 사건과 v2 JSON 계약만 받는다. 실제 현장 기록·이미지·사람 정보를 보내지 않는다.
- 기존 namespace, Unix peer 검사, 고정 relay, root readonly executable을 사용한다. CLI에는 host key를 제공하지 않는다.
- 기존 `glm-first-review.spent` 전역 marker를 동일하게 사용한다. 온라인 1회, 출력 1,024 tokens(추론 포함), 30초, 재시도 없음이다. 실패·불명확 결과도 marker를 삭제하지 않는다.
- 실제 CLI가 만든 허용 metadata만 그대로 전달한다. OpenCode 정체성을 생성하거나 제공자 제한을 우회하지 않는다. 거절은 HOLD이다.
- 유료 모델·다른 endpoint·redirect·fallback·tools는 거부한다. Catalog의 무료 요금과 실제 청구 관측을 구분하며 비용은 미확인으로 남긴다.
- 기본 관리자 명령은 준비와 offline selfcheck만 수행한다. 명시 `--online`만 실제 1회 시험이며, 동일 원본 marker가 이미 있거나 확인 불가하면 거부한다.
- 실제 설치·SDK 시험·온라인 결과는 별도 기록한다. SOURCE/mock 통과 또는 provider-only 결과로 runtime/cost/action admission을 올리지 않는다.

공식 기준: [OpenCode 모델표](https://dev.opencode.ai/v2/docs/console/models/). 무료 모델 제공과 데이터 정책은 변경될 수 있으므로 합성 정보만 사용한다.
