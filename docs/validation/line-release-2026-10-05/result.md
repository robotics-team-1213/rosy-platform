# 차선 화면 배포 전 기존 Fleet 검사 차단 해소

main `258d30ed1`에서 소스 규모 판정과 robot literal 검사 두 실패를 재현했다.
이 실패는 차선 화면 변경으로 생긴 것이 아니며 baseline 보고서는
`X:/DevTemp/line-remote-20261005/release-baseline.txt`에 보존한다.

Fleet의 학습 증거 수신기가 직접 알던 세 profile 이름과 validator 함수의 매핑을
이미 profile schema를 소유하는 canonical `contracts/learning/.../artifacts.py`로 옮겼다.
lazy local import로 validator→artifact 순환을 피하고 Fleet은 그 매핑만 가져온다.
profile 이름·검증 함수·실제 파일 byte 검증·원본 출처·UNKNOWN의 의미는 바꾸지 않았다.
로봇 이름 예외를 추가하거나 literal 검사를 완화하지 않았다. wire와 장치 주행 권한도 바꾸지 않았다.

독립 검토 `keep_review`는 기존 판정 source `4079bde41`의 Fleet 35,878줄과 현재 36,234줄을
검사 코드의 `_files`/`_lines`/`_over_budget` 규칙으로 각각 다시 셌다.
증가 356줄은 evidence bundle +106, receiver +97, discovery transport +88,
traffic reservations +33, segment store +23, styles +16, roster −8, setup +1이다.
receiver·transport·reservation·UI의 기존 소유자와 B2 server/UI 분리 후속 의무를 유지한다.
600 production/800 web, 1000줄 zero-growth, package +150 한도는 바꾸지 않고
명시적 판단의 기준 수치만 승인된 36,234로 갱신한다.

검증: 실제 프로파일·원본 변조·원장 readback을 포함한 Fleet receiver/literal 검사 24 PASS, 1 SKIP;
canonical learning artifact 계약 19 PASS. 독립 검토는 `X:/DevTemp/line-release-review-20261005/`에 보존한다.
SKIP은 통과 증거가 아니다. 원격 로봇의 자동 차선 주행과 FIELD 수용은 이 변경으로 승인하지 않는다.
