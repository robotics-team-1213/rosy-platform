# line_follow 호 주행 하위 패키지 분리 계획

**날짜:** 2026-10-08
**상태:** 진행 중 (브랜치 `feat/d520-core-arc-feedforward`, D-520 단계 1). 새 크기 단위의 판정은 독립 재판정을 기다린다.
**이유:** D-520 2항 「코드 위치와 크기」. `line_follow/recovery` 크기 단위는 2026-10-08 판정 2713줄이고 다음 재판정은 +150(2863)이다. 이 분리 계획을 쓸 때 그 디렉터리는 2803줄이라 약 60줄이 남는다. 호 상태 기계와 IR 한 번 보정(단계 1), 카메라 호 맞춤(단계 2)은 합쳐 300줄이 넘을 것으로 본다. `core_features` 판정(12772, 기준 +150)도 이 계획을 쓸 때 12827줄이라 약 95줄이 남는다.

## 무엇을 두나

새 하위 패키지 `core_features/line_follow/arc/`를 만든다. 옮기는 모듈은 없다. 새 코드만 둔다.

| 파일 | 단계 | 내용 |
|------|------|------|
| `arc/__init__.py` | 1 | 패키지 표시 |
| `arc/lane_arc.py` | 1 | `exit_segment` 검증, `line_follow.arc` 기록, 호 틱(ω = g·v·κ, odom 길이, 시간 한도, 끝 처리), IR 한 번 보정, 멈춤 사유 |
| `arc/lane_arc_fit.py` | 2 | 반지름을 고정한 바깥선 원 맞춤(ROS 없는 함수). P1a 착지 뒤 |

다음은 그대로 둔다.

- `recovery/junction.py`: 교차로 지시와 회전. 호를 여는 자리(회전 끝), 호 중 지시를 `armed`로 받는 것, `segment_end` 축만 몇 줄 더한다.
- `recovery/motion_admit.py`: `IR_ALLOWED`의 kind `arc`·`arc_edge`와 `ir_side` 인자(D-520 2항이 recovery 안에 두라고 정했다).
- `manager.py`, `model.py`: 틱의 호 갈림(몇 줄)과 설정 키(`arc_enabled`, `arc_curvature_gain`, `arc_blind_max_m`)와 그 검증.

## 지키는 것

- **매니저 잠금 하나와 generation 하나.** `arc`는 `LineFollowManager`의 믹스인으로만 쓰인다. 자기 잠금, 스레드, 저장소, 발행자를 두지 않는다. 호의 twist는 매니저 틱의 결정으로 같은 generation·evidence revision을 달고 CommandManager에 간다(D-18).
- **최종 발행자.** 최종 `cmd_vel` 발행자는 그대로 CORE CommandManager다(D-2, D-18).
- **안전 경로.** D-422 몸 sweep(`body_stop.py`, `clearance.py`, `concern: safety`)은 부르기만 하고 고치지 않는다.
- **의존 방향.** `arc`는 `recovery`(교차로 상수, 운동 허가)를 부를 수 있다. `recovery`는 `arc`를 import하지 않고, 매니저의 믹스인 메서드로만 부른다.
- **ROS·OpenCV 없음.** `control.sensing`을 import하지 않는다.

## 크기 판정

- `test/architecture/test_module_structure.py`의 `SIZE_UNITS`에 `core/services/core_features/line_follow/arc`를 더하고 `SIZE_VERDICTS`에 자기 판정을 준다. 판정 기준선은 단계 1 착지 시점의 줄 수이고, 다음 재판정은 +150이다.
- 단계 2(`lane_arc_fit.py`)가 +150을 넘기면 그 브랜치에서 재판정한다.
- `recovery`와 `core_features`의 판정은 바꾸지 않는다. 두 단위에 더하는 줄이 각자의 +150 안에 들어가야 한다. 넘으면 이 계획의 단계를 다시 쓴다.
- 새 단위의 판정은 독립 재판정을 거쳐야 한다(`SIZE_UNITS` 주석). 이 브랜치의 판정 문구는 재판정 대기로 표시한다.

## 순서와 검증

1. 이 계획과 크기 단위 등록. `test/architecture/test_module_structure.py`.
2. 계약: `exit_segment`, 능력 `lane_arc`, `pivot_basis` 값 `segment_end`, `line_follow.arc` 상태, 사유·이벤트, API Reference 판 올림.
3. CORE 호 주행(`arc/lane_arc.py`), 4. IR 한 번 보정, 5. SOURCE 시험.
6. CORE 시험 묶음(services, gateway, api_web), 판 고정 시험, `test_module_structure`, `test/known_failures.py`.

## 착지 순서

Fleet 쪽(`feat/d520-fleet-exit-segment`)과 따로 착지할 수 있다. 기본 꺼짐(`arc_enabled: false`)이고 능력 `lane_arc`가 없으면 Fleet이 `exit_segment`를 보내지 않는다. 단계 2는 P1a(`docs/plans/2026-10-08-control-p1a-sensing-perception-split.md`) 착지 뒤다.
