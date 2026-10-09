# control P1a 단계: sensing/perception 크기 단위 분리 계획

**날짜:** 2026-10-08
**상태:** 2026-10-09에 1단계 크기 단위 계상을 `refactor/control-perception-size-unit`에서 검증했다. 실제 패키지 이동인 2단계는 아직 하지 않았다. 이 계획 문서는 원래 `fix/keep-flip-latch-after-pivot`(D-507 keep 제자리 회전 reset)에서 작성됐다.
**이유:** `control` 크기 판정(45104, 2026-10-07)에는 조건이 붙어 있다. 다음 재판정에는 날짜가 붙은 P1a 단계(sensing/perception 이동)가 `docs/plans/`에 있어야 한다. 이 문서가 그 단계다. 2026-10-08 기준 `control`은 45251줄이다. 한도 45254(45104+150)까지 3줄 남았다. `line_observer_node.py`는 608줄이다. 1차 판정은 604줄이었고 D-507 keep 제자리 회전 reset 때문에 재판정했다. 옮길 자리가 없어 남은 부담은 이 단계로 넘긴다.

## 무엇을 옮기나

`middleware/perception/control/sensing/perception/`(ROS 없는 카메라·차선 근거, D-209/D-228)을 `control` 패키지 합계에서 뺀다. 이 폴더는 52개 모듈, 10841줄이다. `learned/`를 포함하고 시험은 제외한 수다.

1단계에서는 디렉터리를 옮기지 않는다. `test/architecture/test_module_structure.py`의 `SIZE_UNITS`에 `perception/control/sensing/perception`을 더해 별도 크기 단위로 센다. 2026-10-07 `line_follow/recovery`도 같은 방식으로 했다. 파이썬 import 경로(`control.sensing.perception.*`)와 colcon 패키지는 그대로다. 이 디렉터리에는 이미 `__init__.py`가 있다. 따라서 `test_size_units_are_real_subpackages_with_a_split_plan` 조건을 만족한다.

배포 이미지를 실제로 줄이는 이동(P1a 본래 목적)은 2단계로 둔다. 새 colcon 패키지 `rosy_perception_core`(가칭, `middleware/perception/perception_core/`)로 옮기고 `control`이 그것에 `exec_depend`한다. 2단계는 1단계를 착지한 뒤 따로 독립 검토를 받는다. 이 문서는 2단계의 순서만 적는다.

다음은 그대로 둔다.

- ROS 노드: `line_observer_node.py`, `camera_detect_node.py`, `road_state_node.py` 등은 `control/`에 남는다. 이 노드들은 ROS 어댑터이고 판정은 노드별로 받는다.
- `sensing/` 상위 모듈: 라이다, 몸체, 도크 태그는 그대로 둔다(`sensing/perception/AGENTS.md`의 Purpose).

## 지키는 것

- **외부 계약.** 토픽, 메시지, 파라미터, `line/keep_debug` 필드를 바꾸지 않는다.
- **ROS 없음.** `sensing/perception`은 계속 ROS, `core`, twist를 import하지 않는다. 최종 `cmd_vel` 발행자는 CORE다(D-143).
- **2단계 import.** 옛 경로 `control.sensing.perception`를 쓰는 곳은 같은 변경에서 새 경로로 고친다. 노드, `middleware/perception/test/`, `learning/` 도구가 그 대상이다. 재수출 shim은 두지 않는다. 2단계가 이번 문서에서 가장 큰 변경이다.

## 크기 판정

- `SIZE_UNITS`에 `perception/control/sensing/perception`을 더한다. 그 단위에 판정 `accept`를 주고, 이 문서를 인용한다. 기준선은 그 시점의 줄 수다. 오늘 기준 10841이고 허용은 +150이다.
- `control` 판정은 옮긴 줄 수만큼 낮춘다. 오늘 기준 45251−10841 = 34410이다. 착지 시점에 다시 센다.
- 단위로 세면 `lane_keep.py`(600)와 `lane_bev.py`(653)의 파일 판정은 바뀌지 않는다. 파일 판정은 파일 단위로 계속 받는다.
- `line_observer_node.py` 판정 608은 이 단계가 착지할 때까지 늘지 않는다.

## 순서와 검증

1. **1단계.** `SIZE_UNITS`에 한 줄, 새 단위 판정 한 개를 더하고 `control` 판정 수치를 낮춘다. 이 작업은 `refactor/control-perception-size-unit` 단독 브랜치에서 한다. 동작 변경은 없다. 같은 브랜치에서 `middleware/perception/control/sensing/perception/AGENTS.md`와 `middleware/perception/AGENTS.md`에 이 크기 단위를 한 줄씩 적는다.
2. **검증.** `test/architecture/test_module_structure.py`를 단독으로 돌린다. 줄 수를 다시 세서 판정과 맞춘다. 그 다음 perception 시험을 gateway 시험과 따로 돌린다. 파일 이름이 겹치기 때문이다. 대상은 `test_lane_keep.py`, `test_line_observer_wiring.py`, `test_lane_paint_source.py`, `test_keep_pivot.py`다. `python test/known_failures.py`가 0 new여야 하고, `python tools/harness/rosy_harness.py lint`가 0 error여야 한다.
3. **독립 검토.** 크기 판정을 두 단위로 나눈 것을 독립 검토한다(critic 또는 code-reviewer). 검토가 끝난 뒤에 착지한다.
4. **2단계(별도 계획 검토 후).** `git mv`로 옮기고 `package.xml`/`setup.py`를 고친다. import를 고친다. 그 다음 ARM64 이미지를 빌드해 확인한다. 호스트 pytest 통과는 이미지 확인을 대신하지 않는다.

## 착지 순서

`lane_keep*.py`를 고치는 `fix/keep-bend-not-fork`(D-507 B9)는 `control`에 약 220줄을 더한다. 1단계는 그 브랜치보다 먼저 들어가야 한다. 1단계가 먼저 착지하면 B9 브랜치는 새 단위의 +150 안에서 다시 판정을 받는다. 1단계 브랜치는 이 문서를 담은 `fix/keep-flip-latch-after-pivot` 다음에 짧게 연다.
