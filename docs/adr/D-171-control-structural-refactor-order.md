## D-171 control 구조 개선은 host 시험 가능한 판단 비율로 재고, ROS 경계 → 노드 판단 추출 → 패키지 분리 순서로 한다

**Status:** Accepted (2026-09-22, 사용자 검토 승인). 트랙 1의 가드(`test/test_control_ros_edge.py`)는
새 누출을 막는 래칫이므로 이 ADR과 함께 들어간다.

**Context:** D-168은 줄 수 예산(P6)과 배포 단위(P1a)로 control을 판정했다. 그 결과 파일 하나씩
`split` 판정이 쌓였고, 패키지 3분할 설계가 나왔다. `web_node.py`는 그렇게 한 파일을 나눈 첫 사례였다.
그런데 무엇을 먼저 해야 하는지를 재는 척도는 없었다.

2026-09-22 구조 평가([control structural evaluation](../plans/2026-09-22-control-structural-evaluation.md))는
판단(분기·비교·임계)을 세고, 각 판단이 host pytest가 import할 수 있는 모듈 안에 있는지를 쟀다.

- control 제품 모듈 147개의 판단 8,014개 가운데 **2,845개(36%)가 ROS에 묶여** host에서 볼 수 없다.
- 그 절반인 1,388개는 노드가 아닌 라이브러리 모듈 안에 있다. 이 모듈들은 메시지 객체를 한두 곳에서
  직접 만든다는 이유만으로 ROS에 묶였다. 예를 들어 `calibration_rotation`은 판단 187개를 담고 있는데
  `Twist`를 1곳에서 쓰고, `calibration_atomic`은 판단 75개에 `String` 1곳이다.
- 나머지 1,449개는 노드 14개 안에 있다.
- 패키지 분리는 이 수치를 **하나도** 바꾸지 않는다.
- 교정 노드의 판단은 시험 50개가 AST로 메서드를 떼어 `exec`로 돌리는 우회로만 검증된다.
- 교정 노드의 IMU·카메라·스탬프 게이트, 기존 설정 모드의 준비 완료 병합 순서, `calib_node`의
  절벽 임계는 실제 값 시험이 없다.

**Decision:**

1. **척도.** control 구조 작업의 진척은 "host import 가능한 모듈 안에 있는 판단의 비율"로 잰다.
   2026-09-22 기준선은 64%다. 줄 수(D-168 P6)는 검토를 강제하는 신호로 남지만, 작업 순서를 정하지는
   않는다.
2. **순서는 세 트랙이며 1 → 2 → 3이다.**
   - **트랙 1 — ROS 타입은 노드 경계에서만.** 노드가 아닌 control 모듈은 ROS를 import하지 않는다. 값을
     돌려주고, 메시지는 노드가 만든다. 예외는 이름을 올린 경계 어댑터 셋(`tf_buffer`,
     `web_map_control`, `sensor_provider`)뿐이다. 현재 누출 16개는 `test/test_control_ros_edge.py`의
     `KNOWN_ROS_LEAKS` 래칫(집합 동일성, D-168 P5)에 올린다. 새 누출은 적색이고, 고친 누출이 목록에
     남아도 적색이다.
   - **트랙 2 — 노드 안 판단 추출.** 대상은 노드 파일이다. 첫 대상은 교정 클러스터다.
     - `startup_calibration_node`: 센서 게이트 술어와 발행 준비 완료 판정(병합 순서를 명시적 함수로)을
       뽑는다.
     - `calib_node`: 순수 함수 5개와 절벽 임계 계산을 뽑는다.
     - `safe_motion`·`pause_precision`은 상태 구조가 필요하고, 이미 AST 시험이 있으므로 뒤로 미룬다.
   - **트랙 3 — 패키지 분리.** [분리 설계](../plans/2026-09-22-control-package-split-design.md) §6의
     2~5단계를 따른다. 트랙 1·2 뒤에 하는 이유는 둘이다. 이득이 배포 이미지뿐(P1a)이고, 트랙 1이
     끝나면 옮길 모듈이 대부분 ROS 없는 모듈이 되기 때문이다.
3. **추출 규칙 (트랙 1·2 공통).**
   - (a) 동작 보존 리팩터링이다. 옮긴 코드는 원본과 diff로 대조하고, 달라진 줄은 커밋 메시지와
     `logs.md`에 적는다.
   - (b) 시간은 인자로 받는다(`now`). 뽑은 모듈이 `time.monotonic()`을 직접 부르지 않는다. 시뮬 rig가
     교체하는 모듈 10개(`calibration_mapping_rig.py:195-199`)는 `import time`과
     `time.monotonic()` 형태를 유지한다.
   - (c) 뽑은 판단마다 실제 값 host 시험을 붙인다. 그 판단을 AST로 떼어 돌리던 시험은 새 모듈을 직접
     import하도록 바꾼다. 판단을 다른 함수로 바꿔 넣는 스텁(예: `ir_valid` 항등 함수)은 실제 함수로
     되돌린다.
   - (d) `calibration/ready`, `cmd_vel_raw` 후보, 비상정지에 닿는 변경은 병합 전에 ROS-SIM을 통과해야
     한다. rig 기본 시나리오를 `RIG_COMPONENT=all`과 분리 모드로 돌리고, 비상정지 음성 사례를 돌린다.
     `calib_node`의 절벽 로직은 rig가 IR을 상수로 발행하므로 DEVICE/벤치 증거가 필요하다.
   - (e) 한 커밋은 한 모듈(트랙 1) 또는 한 노드 파일(트랙 2)이다. D-168 `SIZE_VERDICTS`와
     `KNOWN_ROS_LEAKS`는 같은 커밋에서 갱신한다.

**Alternatives:**
- **파일 크기 순으로 노드를 하나씩 나누기** (D-168 P6만 따르는 안): 비용이 가장 큰 작업부터 하게 된다.
  1,388개를 싸게 넘길 수 있는 트랙 1을 뒤로 미룬다.
- **패키지 분리 먼저:** 척도를 움직이지 않는다. 또 누출 모듈을 ROS에 묶인 채로 옮기게 되어 import
  재작성 약 200줄을 두 번 하게 된다.
- **메시지 어댑터 계층을 새로 만들어 모든 발행을 감싸기:** 트랙 1과 효과는 같다. 하지만 노드마다 이미
  있는 발행 코드 옆에 두 번째 경로를 만든다. D-168 P1의 인정 조건도 충족하지 못한다.

셋 다 채택하지 않는다.

**Consequences:**
- 트랙 1이 끝나면 `KNOWN_ROS_LEAKS`는 빈 집합이 된다. 그러면 가드는 "노드와 경계 어댑터만 ROS"라는
  불변식이 된다.
- 교정·안전·주행 판단이 host 시험으로 들어오면서, 지금의 AST 추출 시험은 줄어든다.
- 트랙 1은 `wander.*`·`safety.*`·교정 믹스인의 반환형을 바꾼다. 그래서 이 모듈들을 쓰는 노드도 같은
  커밋에서 메시지 생성을 맡는다.
- 이 ADR은 D-168 `SIZE_VERDICTS`의 `split` 판정을 무효로 하지 않는다. 그 판정들의 **이행 순서**를
  정한다.

**Validation / Transition:**
- `python -m pytest test/test_control_ros_edge.py -q`. 변이 증명 2건을 거쳤다: 새 누출 모듈 추가 →
  적색, 고친 누출을 목록에 남김 → 적색, 복구 → 초록.
- 척도 재측정은 평가 문서 §2의 정의로 한다.
- 2026-09-22 사용자 검토에서 순서와 규칙 3(a)–(e)가 승인되어 Accepted로 올렸다.

**References:** D-168, D-126, D-149, D-38, D-150, [module split criteria](../plans/2026-09-06-module-split-criteria.md) C1/C2/X1–X6,
[control structural evaluation](../plans/2026-09-22-control-structural-evaluation.md),
[control package split design](../plans/2026-09-22-control-package-split-design.md).

---
