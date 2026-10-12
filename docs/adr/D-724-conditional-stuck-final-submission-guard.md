# D-724 조건부 막힘 답의 지원 확인 후 최종 제출 검증

**Status:** Accepted (2026-10-12, source contract; no operational activation)

## Context

D-718의 조건부 HttpRobotClient는 CORE 지원을 GET으로 확인한 뒤 POST한다. D-716 소비자가 메서드 호출 전에 운영 수용·사람 점유를 확인해도 이 GET을 기다리는 동안 상태가 바뀔 수 있다. 최종 검증과 사건당 단일 claim은 지원 확인 이후 제출 입구에 위치해야 한다.

## Decision

기존 RobotClient/HttpRobotClient의 line_stuck_decision에 선택적인 async before_submit 포트를 둔다. expected_stuck가 있는 BACK_AND_RETRY에만 허용하고 callable을 명시적으로 요구한다. CORE의 conditional_back가 정확히 true임을 확인한 이후, 기존 POST 입구 전에 정확히 한 번 호출한다. 반환값이 정확히 True인 경우만 POST한다. 다른 값·오류·취소에서는 POST하지 않고 기존 호출자 오류/UNKNOWN 처리에 전달한다. 지원되지 않는 CORE에는 포트도 호출하지 않는다.

이 포트는 검증·claim 구현이 아니다. signed 운영 수용·현재 사건·사람 점유·클라이언트·예산을 최종 확인하고 동일 Fleet DB의 durable claim을 결속하는 책임은 기존 단일 Fleet 소비자에게 있다. 그 claim이 제출 시작의 선형화 지점이며 이전 폐기는 거절하고 이후 폐기는 UNKNOWN/no replay로 처리한다. 포트 없이 기존 호출은 호환되고 새 HTTP 경로·wire field·writer·모델 호출은 추가하지 않는다. 운영 모델 후보 소비는 아직 비활성이다.

## Verification

실제 MockTransport GET의 await 이후 최종 포트 실행, strict True/false/null/int/string·오류·취소의 POST 차단, 미지원 CORE의 0 claim, 잘못된 포트의 0 request, 기존 조건부·수동 요청의 호환성을 원격 검증한다. 실제 수용 receipt·physical claim·Fleet loop 연결·모델/현장 검증은 D-716의 후속이다.

## 소비자 수용 전제

독립 SOURCE 검토에서 후속 소비자는 포트를 무시하는 임의 RobotClient를 수용하지 않기로 확인했다. runtime Protocol·메서드 signature·자기 보고 지원 bool만으로 구현을 수용하지 않는다. 등록된 설치 artifact와 실제 검증된 HttpRobotClient 구현·구체 메서드, 최종 client object identity를 결속한다. `**extra`로 포트를 무시하는 fake/override는 모델 소비 회귀에서 0 claim/0 POST로 거절한다. 실제 승인 폐기 epoch·물리 claim의 취소 후 DB 완료 대기·남은 deadline은 이 포트의 존재로 대체하지 않는다.
