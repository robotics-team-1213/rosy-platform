# CORE localization 크기 단위 분리

**날짜:** 2026-10-09
**범위:** D-168 구조 판정만. 런타임 코드 이동이나 동작 변경 없음.

`core_features`의 이전 판정은 12,947줄에 +150 허용을 두고 다음 증가 전에
코드를 별도 크기 단위로 분리하도록 요구했다. 현재 합친 트리는 13,192줄로
그 한도를 8줄 넘는다. 이번 D-531 경로 문맥 계산은 line-follow 소유이며
작은 새 파일만 분리해 예산을 맞추면 실제 소유 경계가 흐려진다.

이미 독립 Python 하위 패키지인 `core_features/localization/`을 크기 단위로
등록한다. `assist.py`(326), `halt.py`(75), `mission.py`(439),
`pose_request.py`(73), `__init__.py`(9), 합계 922줄이다. 지역화 후보·미션·정지 판정은 한 도메인이고
ROS I/O와 최종 `cmd_vel`은 여기서 소유하지 않는다. 코드를 옮기지 않는다.

`SIZE_UNITS`에 해당 패키지를 추가하고 독립 판정 기준선 922줄을 둔다.
부모 `core_features`의 측정값은 13,192 − 922 = 12,270줄로 다시 적는다.
각 단위의 다음 증가 한도는 기존 +150 규칙을 따른다. 기존 recovery,
junction, arc 단위와 파일별 600/1000줄 판정은 그대로 검사한다.

검증: `test/architecture/test_module_structure.py`의 실제 측정,
`core/services` 관련 host 시험, `rosy_harness.py lint`. 크기 단위 재분류는
SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.
