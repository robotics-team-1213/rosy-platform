# D-953 Pi 4·Pi 5 CPU는 이미 있는 네이티브 경로로 먼저 줄인다 — 자체 Rust 확장은 Pi 4 실측이 요구할 때만

**Status:** Accepted (2026-11-01, 사용자 지시: "확인하고 ADR로 결정해", "더 안좋은 환경(라즈베리파이 4·5)에서도 돌린다, 필요하면 도입시켜", "바로 처리해"). D-185의 항목 순서와 검증 방식을 따른다. D-185를 대체하지 않는다.

### Context

- 질문은 rustbpe처럼 무거운 파이썬 루프를 Rust(PyO3·maturin)로 옮겨 import만 바꾸면 빨라지느냐였다. 대상 기체는 Pinky(Raspberry Pi 5)이고 Raspberry Pi 4도 돌린다.
- **단일 코어 성능 차이.** 공개 Geekbench 6 단일 코어 점수로 비교했다. 시험 PC의 Core Ultra 9 275HX가 약 3,030점, Pi 5가 약 750~930점, Pi 4가 약 250~340점이다.
  - 같은 코드가 Pi 5에서 약 3~4배, Pi 4에서 약 9~12배 느리다고 본다.
  - 실측도 이 비율과 맞는다. `match_motion`은 노트북 24ms, Pi 5 73ms(D-185 R8)였다.
- **관제 PC 상주 서비스** (2026-11-01, `top`과 같은 20초 동안 `py-spy record --nonblocking --gil`).

  | 프로세스 | 프로세스 CPU | GIL 잡은 파이썬 |
  |---|---|---|
  | `rosy_vision` | 55% | 4% |
  | 지도 정합 자식 | 38% | 2% |
  | Fleet 콘솔 | 26% | 7% |
  | `workcell_observation` | 23% | 6% |

  대부분이 이미 OpenCV·numpy·SSL 안에서 쓰는 시간이다. Rust로 옮겨도 줄일 수 있는 몫이 작다.
- **기체 노드** (Gazebo 2대 주행 벤치 `fleet_trips --lap`, 모델 PC, `f2333e8aea`, 노드별 30초).
  - 기본 실행기에서 x86 CPU는 CORE 90~91%, `line_observer` 49~50%, `road_observer` 47%였다.
  - GIL 표본의 81~96%가 rclpy 파이썬 실행기(`_wait_for_ready_callbacks`, `add_to_wait_set`, `_take_subscription`)였다. 우리 인식 코드는 5~8%였다.
  - 같은 벤치에서 `ROSY_EXECUTOR=events`(C++ `rclpy.experimental.EventsExecutor`)로 바꿨다. `line_observer`는 50%에서 24%, `road_observer`는 47%에서 21%가 되었다. GIL 표본은 노드당 약 868개에서 230~250개로 줄었고, 실행기 파이썬 프레임은 0개가 되었다. D-185 R3 rig A/B(440%→176%)와 같은 방향이다.
  - CORE는 `MultiThreadedExecutor`를 직접 쓰므로 `ROSY_EXECUTOR`의 영향을 받지 않는다(`middleware/core/gateway/core/node.py`).
  - 시뮬의 절대값은 실기보다 크다. `/clock`(D-185 R6)과 시뮬 전용 노드 때문이다. Pi 5에서 CORE만 돌 때는 한 코어의 약 22%였다(D-185 R8). 그래서 여기서는 비율만 근거로 쓴다.
- **계산 자체가 주기를 넘는 곳.** 교정 회전 단계의 `match_motion`이다(`middleware/perception/sensors/sensing/scan_motion.py`).
  - Pi 5 실측 73ms로 50ms tick보다 길다. Pi 4는 160~200ms로 추정한다.
  - 시간은 `correspondence`의 (점, 선분, 2) 브로드캐스트 임시 배열과 `_segments`의 창별 파이썬 루프에서 쓴다.
  - 행렬곱 전개(|d|²−2t(d·e)+t²|e|²) 시제품은 합성 상자 방 41건에서 판정이 같았다. 그러나 2026-09-09 실제 기록 프레임 6건에서 원본이 수락한 것을 거절했다.
    - 원인은 두 선분이 공유하는 끝점에 있다. 전개식의 상쇄 오차(약 1e-16 m²)가 실제 거리 차이(약 1e-20 m²)보다 커서, 점이 바깥에 놓인 선분을 고른다.
    - 그래서 기각했다.
  - 채택한 구현은 같은 연산을 x·y 성분별 (점×선분) 배열로 계산하고, `_segments`는 묶음 SVD로 바꿨다.
    - 55건(합성·잡음·실제 기록·거절 경우)에서 원본과 결과가 `==`로 같다.
    - 노트북 중앙값은 31~32ms에서 10.6~11.7ms로 약 2.8배 빨라졌다.
  - 환산하면 Pi 5는 약 24ms로 tick 안에 든다. Pi 4는 약 55~70ms로 50ms tick을 넘을 가능성이 크다.
- 노트북·시험 PC·기체 이미지 어디에도 Rust 도구 사슬과 numba가 없다.
- 측정 때 함정이 하나 있었다. `py-spy --nonblocking`을 `--gil` 없이 쓰면 큐·파이프에서 기다리는 스레드가 활성 표본으로 잡힌다. Fleet 콘솔이 "코어 14개분"으로 보였다.

### Decision

1. **자체 Rust 확장은 지금 넣지 않는다.** 기체에서 가장 큰 파이썬 비용은 rclpy 실행기다. 이것은 Jazzy에 이미 있는 C++ 실행기로 import만 바꿔서 줄인다. 우리 코드에서 남는 계산 병목은 `match_motion` 하나이고, numpy로 Pi 5 예산 안에 든다.
2. **실행기: Pi 4·5의 기본값을 `events`로 옮긴다.** 순서는 D-185 R3 그대로다.
   - control 노드는 기체 A/B 한 번(`hotpath_measure.py watch`, `single`↔`events`, 사람이 로봇 옆에 있을 때)으로 노드별 CPU와 주행·정지 동작이 같음을 확인한다. 그 뒤 기체 이미지의 `ROSY_EXECUTOR` 기본값을 `events`로 바꾼다.
   - Pi 4 지원은 이 전환을 전제로 한다.
   - CORE 실행기는 safety 경로(D-430)다. `ROSY_EXECUTOR` 범위 밖에서 별도 B 항목으로 다룬다. 독립 검토 없이 바꾸지 않는다.
3. **`match_motion`은 numpy로 먼저 줄인다.** 이 변경과 함께 넣는다.
   - 결과가 비트 단위로 같으므로 D-185 2의 결과 동일 변경(E)이다.
   - 원본 사본과의 차등 시험(`middleware/perception/test/test_scan_motion_equivalence.py`)이 실제 기록 프레임을 포함해 `==`를 요구한다.
   - 임계값·가드·신선도 창은 바꾸지 않는다(D-185 4).
   - 거리 계산식을 바꾸는 최적화는 합성 사례만으로 판단하지 않는다. 실제 기록 프레임을 차등 시험에 넣는다.
4. **자체 네이티브 커널을 들이는 조건.** Pi 4 실기 bench(`hotpath_measure.py bench`)에서 numpy 버전 `match_motion` median이 50ms tick을 넘으면 `correspondence` 하나를 PyO3 확장으로 옮긴다. 그때 다음을 같이 지킨다.
   - 서명 이미지 빌드(D-868)에서 aarch64 wheel을 만든다. 실패하면 파이썬 구현으로 돌아간다.
   - numpy 구현을 기준으로 남기고 3과 같은 차등 시험을 통과한다.
   - 계산 동안 GIL을 놓는다.
   다른 경로도 같은 순서를 따른다. 먼저 `top -H`와 `py-spy --gil`로 잰다. 그다음 실행기·대기·I/O인지 가르고, numpy나 이미 설치된 네이티브 라이브러리로 줄이고, 마지막으로 PyO3를 쓴다.

### Consequences

- 빌드·이미지·시험 PC에 Rust 도구 사슬을 늘리지 않는다. Pi 4 실측이 나오면 4의 조건으로 다시 본다.
- 실행기 전환 전까지 Pi 4에서 control 노드를 모두 띄우면 CPU가 부족할 수 있다. 이 위험은 Pi 4 첫 실기 시험의 확인 항목이다.
- 남은 측정은 다음과 같다. 모두 실기와 사람이 필요하다.
  - Pi 4·Pi 5에서 `hotpath_measure.py bench`와 `watch`
  - 실행기 A/B
  - 기체 카메라(`rosy-camera`, 8 fps)와 `rosy-media`처럼 시뮬에 없는 서비스의 CPU
- 관제 PC 서비스는 이 결정의 대상이 아니다. 줄일 여지는 OpenCV·numpy 호출 횟수와 해상도 쪽이다.

### Alternatives

- **무거워 보이는 경로를 미리 Rust로 옮기기:** 기체 노드의 파이썬 시간 대부분은 rclpy 실행기다. 우리 Rust 코드로는 그 시간을 없앨 수 없다. 기각.
- **numba 일괄 도입:** 기체 이미지에 LLVM 의존성이 늘고 첫 실행 JIT 비용이 생긴다. 상위 함수 대부분은 numba가 가속할 형태가 아니다. 기각.
- **`match_motion`을 바로 Rust로:** Pi 5는 numpy로 예산 안에 든다. Pi 4는 환산상 넘을 가능성이 크지만 실측 전이다. 4의 조건으로 미룬다. Pi 4 실측이 50ms를 넘으면 이 항목이 첫 PyO3 대상이다.
- **행렬곱 전개 거리식:** 더 빠르지만 실제 기록 프레임에서 판정이 달라졌다(Context). 기각.
