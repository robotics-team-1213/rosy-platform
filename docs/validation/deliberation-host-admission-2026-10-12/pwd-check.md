# AI PC 실제 환경 검사 보정

- Source: `b904142a17`.
- 사용자 관리자 적용 출력: INSTALLED. 실제 HOST probe는 environment_empty만 false, 나머지 12개 검사 true. 결과 HOLD.
- 같은 sandbox launcher로 실행한 Python 진단: exit 0, 환경 이름 HOME·LC_CTYPE·PATH·PWD, HOME/PATH 고정값 일치.
- 원격 RED: 정상 PWD 오거절과 변경 PATH 오수용, 2 failed.
- 수정: 허용 변수에 PWD를 추가하되 값은 /tmp만 인정. PATH=/usr/bin:/bin도 명시적으로 검증. 다른 변수·HOME/PATH/PWD 변경을 거절한다.
- 원격 회귀: 30 passed, exit 0, NEW 0. Log: `X:/DevTemp/projects/rosy-platform/2026-10-12--023355--deliberation-host-admission--4a3286/logs/pwd-green/run-1.txt`.
- 실제 수정 파일로 전용 계정의 preflight를 재실행하기 전까지 HOST PASS는 미확인이다. 운영 모델 호출과 FIELD 수용은 별도다.
