# D-657 progress projection 후속 구현 계획

사용자 승인: 책임 분리 세션의 `project_progress` 전체 계산 추출과 D-657 단독 import 조건을 함께 처리한다. branch `refactor/pure-progress-projection`.

1. 협업 검토본 `d942b265bf`에서 workflow 계산, Fleet progress adapter, execution의 기존 foundation dependency만 가져온다. D-660~D-662 제품 구현과 공유 schema의 미커밋 변경은 별도 소유자가 유지한다.
2. 기존 격리 시험으로 schema의 eager import 문제를 원격 재현한다. `mission_step_state`, timestamp/freshness와 progress 결과는 보존하고 wire schema import만 실제 projection 호출 시점으로 옮긴다.
3. wheel/sdist 설치에서도 계산 모듈을 Fleet 없이 먼저 import하고 실제 projection을 호출한다. CI의 기존 wheel 설치 목록에 foundation을 포함해 dependency와 pip check를 닫는다. GoalEvidence identity, 독립 execution wheel, source image closure와 기존 Mission progress/provenance/fence 회귀를 원격 검증한다.
4. 책임표·모듈 안내·D-657 후속 기록을 실제 코드에 맞추고 독립 소스 검토 후 최신 main에 `tools/land.py --tests auto`로 착지한다. push·배포·provider 호출·로봇 명령은 수행하지 않는다.

Fleet는 하나의 transaction으로 읽은 snapshot과 clock을 공급한다. 인증·원장·claim·stop/fence·transport와 물리 상태 확인 책임은 유지한다. execution은 상태 전이를 쓰거나 허가를 내리지 않는다. ACTION_SUCCEEDED와 GOAL_CONFIRMED를 구별하고 `stop.physical_state=UNKNOWN`을 보존한다.

원격 로그와 최종 착지 receipt는 X 관리 세션 `2026-10-11--223323--pure-progress-import--c132e2`에 보존한다. FULL CI·실제 이미지 빌드·현장 수용은 별도 gate다.

소스 구현 `4ed2975f3`: 원격 RED 1 NEW → GREEN 97 passed / NEW 0, 독립 소스 리뷰 승인. [검증 기록](../validation/pure-progress-projection-2026-10-11/result.md)에 초기 결과와 후속 착지 증거를 구별한다.
