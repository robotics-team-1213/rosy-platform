# CORE line_follow 크기 단위 분리

**날짜:** 2026-10-10
**범위:** D-168 구조 판정만. 런타임 코드 이동이나 동작 변경 없음. D-573 6항 보고 개정(`feat/crosswalk-null-outside-zone`)과 같은 변경이다.

`core_features`의 이전 판정은 12,392줄에 +150 허용이고, 그 판정은 "다음 증가는 line_follow를 자기 크기 단위로 만든다"를 조건으로 달았다.
D-573 6항 보고 개정이 `line_follow/crosswalk_report.py`(121줄)와 관리자·구역·설정 연결을 더해 합친 트리가 12,601줄로 한도(12,542)를 넘는다.

이미 독립 Python 하위 패키지인 `core_features/line_follow/`를 크기 단위로 등록한다.
안쪽 단위 `line_follow/recovery`, `line_follow/recovery/junction`, `line_follow/arc`는 그대로 각자 단위이고, 가장 안쪽 단위가 줄을 가져간다(`_over_budget`).
새 단위가 세는 것은 나머지 line_follow 파일이다: `manager.py`(754), `model.py`(577), `crosswalk_gate.py`(517), `clearance.py`(445), `body_stop.py`(294), `crosswalk_report.py`(121), `crosswalk_zone.py`(91), `authority.py`(89), `route_context.py`(50), `__init__.py`(19), 합계 2,957줄이다.

한 도메인인 이유: 모두 `LineFollowManager` 하나의 잠금·세대 아래에서 도는 차선 추종 정책과 그 mixin(D-422 몸 정지, D-517 통행권, D-573 횡단보도 게이트와 보고)이다.
자기 잠금, 스레드, 저장소, 발행자가 없다. CORE `CommandManager`가 최종 `cmd_vel` 발행자로 남는다. 코드를 옮기지 않는다.

`SIZE_UNITS`에 `core/services/core_features/line_follow`를 더하고 기준선 2,957줄을 둔다.
부모 `core_features`의 측정값은 12,601 − 2,957 = 9,644줄이다. 10k 패키지 한도 아래라 P6 판정이 필요 없고, `SIZE_VERDICTS`의 `core_features` 항목(12,392 판정과 그 이력)은 지운다(남겨 두면 시험이 stale로 거부한다). 이력은 git의 그 항목에 남는다. 부모가 다시 10k를 넘으면 새 판정을 단다.
각 단위의 다음 증가 한도는 기존 +150 규칙을 따른다. 파일별 600/1000줄 판정(`manager.py` 등)은 그대로 검사한다.

판정 상태: 2026-10-10 읽기 전용 critic 에이전트가 2,957줄로 독립 재판정했다(accept).

검증: `test/architecture/test_module_structure.py`의 실제 측정, `rosy_harness.py lint`. 크기 단위 재분류는 SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.
