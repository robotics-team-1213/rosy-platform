# CORE swarm 크기 단위 분리

**날짜:** 2026-10-09
**범위:** D-168 구조 판정만. 런타임 코드 이동이나 동작 변경 없음. D-559(feat/swarm-trail-follow)와 같은 변경이다.

`core_features`의 이전 판정은 12,270줄에 +150 허용이다. D-559 리더 자취 따라가기가
`swarm/trail.py`(153줄)와 `swarm/manager.py` trail 모드(+128줄), 차선 추종 관리자의
`obstacle_gap`(+24줄) 등을 더해 합친 트리가 12,585줄로 한도를 15줄 넘는다.

이미 독립 Python 하위 패키지인 `core_features/swarm/`을 크기 단위로 등록한다.
`manager.py`(564), `trail.py`(153), `poses.py`(42), `__init__.py`(12), 합계 771줄이다.
SWM-001~007 팔로워 상태머신, 추종 목표, D-559 자취와 조향은 한 도메인이고,
ROS I/O, 최종 `cmd_vel` 발행, 안전 판정(SAF-004 클리핑, D-400, D-422 몸체 정지)은
여기서 소유하지 않는다. swarm 은 CommandManager 슬롯과 차선 추종 관리자의 판정을
주입받아 쓴다. 코드를 옮기지 않는다.

`SIZE_UNITS`에 해당 패키지를 추가하고 독립 판정 기준선 771줄을 둔다.
부모 `core_features`의 측정값은 12,585 − 771 = 11,814줄로 다시 적는다.
각 단위의 다음 증가 한도는 기존 +150 규칙을 따른다. 기존 recovery, junction, arc,
localization 단위와 파일별 600/1000줄 판정은 그대로 검사한다.

검증: `test/architecture/test_module_structure.py`의 실제 측정, swarm 관련 host 시험,
`rosy_harness.py lint`. 크기 단위 재분류는 SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.
