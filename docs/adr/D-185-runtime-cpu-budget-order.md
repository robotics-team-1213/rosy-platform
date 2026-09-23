## D-185 control 런타임 CPU는 측정한 비용 순으로 줄이고, 항목마다 검증 방식을 미리 정한다

**Status:** Accepted (2026-09-24, 사용자 승인). 사용자 요청으로 조사 결과를 항목별 과제로 기록한다. 항목은 하나씩
처리하고, 동작이 바뀌는 항목은 착수 전에 따로 승인받는다.

**Context:** 2026-09-23 rig 간헐 실패를 추적하면서(평가 문서 §8.3–§8.4) 프로세스별 CPU를 계측했다. 계측은
모든 콜백을 메모리 계수기로 감싸고 stall 중 스택을 샘플링하는 방식이며, ext4 rig 사본에만 넣었다. 이미
두 결함을 고쳤다.
- 회전 검증의 자체 stall(`c67437d1`)
- `wall_tracker`의 scan당 27 ms를 비트 단위 동일하게 7 ms로 줄인 것(`76181f00`)

남은 비용은 이렇다.

- **노드가 깨어 있는 비용.** 606 s 통과 실행에서 Python 노드 6개가 합계 2.16코어를 썼다. web·goal·wander는
  CPU의 68–84%를 콜백 **밖**에서 쓴다. 초당 90–210회 깨어나며, 대부분 `/tf`(노드당 약 25/s)와 `/clock`(노드당
  50–110/s)이다.
  - 격리 실험(domain 228)을 했다. 콜백이 빈 구독 15개짜리 노드가 1코어의 몇 %를 쓰는지 쟀다.

    | executor | `/clock` 빈도 | 노드 CPU |
    |---|---|---|
    | `SingleThreadedExecutor` | 300 Hz | 50–58% |
    | `rclpy.experimental.EventsExecutor` | 300 Hz | 15% |
    | `SingleThreadedExecutor` | 30 Hz | 18% |
  - 설치된 Jazzy rclpy 7.1.11에 `EventsExecutor`가 있다(import 확인).
- **계산 핫스팟.** x86 host 측정이다. Pi는 미측정이다.
  - `OccupancyMap.inflate`: 200×200에서 51 ms, 400×400에서 128 ms가 걸린다. goal이 2 s마다 계획할 때
    후보별로 지도 전체를 다시 부풀린다. goal tick 평균은 177 ms였다. 실기 경로다.
  - `footprint_sweep_clearance`: 720점에서 12 ms, 1440점에서 31 ms가 걸린다. safety 20 Hz tick마다 불리고,
    tick당 `_clearance`가 수십 번 돈다. 이 경로(`bounded_motion`)는 domain 227·sim 파라미터에서만
    켜지므로 **실기 경로가 아니다**.
- **큐 적체.** 신선도가 중요한 구독이 depth 10 FIFO다. 처리가 밀린 뒤에는 오래된 메시지부터 처리하다가
  거부한다. calibration의 `safety/decision`이 그 예다(체류 18 → 324 ms).
- **환경.** 부하 25–30 이상에서는 노드가 한가해도 OS 스케줄링 공백이 약 340 ms 생긴다. 원인은 피어 세션의
  Gazebo 하네스다. 이 영역의 rig 실패는 코드 판정 근거가 아니다(§8.4).

근거 자료:
- [rclpy #1391 EventsExecutor](https://github.com/ros2/rclpy/pull/1391)
- [rclpy #1389 Python executor 오버헤드](https://github.com/ros2/rclpy/issues/1389)
- [gazebo_ros_pkgs #1211 /clock 빈도와 노드 비용](https://github.com/ros-simulation/gazebo_ros_pkgs/issues/1211)

**Decision:**

1. **순서.** 항목은 실기 이득과 확실성이 큰 순서로 하나씩 처리한다. 한 항목은 브랜치 하나, 기록 하나다.
2. **검증 방식은 항목의 성격으로 정한다.**
   - **결과 동일 변경(E).** 원본을 그대로 복사한 기준 구현과 `repr` 수준으로 비교하는 차등 시험, 뮤테이션
     검출, 비용 측정을 요구한다. 동작 승인은 필요 없다.
   - **동작 변경(B).** 실패하는 시험을 먼저 쓴다. 착수 전 사용자 승인과 독립 리뷰를 요구한다.
   - **rig 주장.** 같은 시간대 교차 반복 실행으로만 판단하고, 부하가 16 미만이거나 R4 가드를 통과한 실행만
     센다. 실패는 단계별로 센다.
3. **항목.**

   | # | 항목 | 성격 | 실기 | 완료 조건 |
   |---|---|---|---|---|
   | R1 | `inflate` 결과를 지도 revision·반경으로 캐시 | E | 예 | 계획 결과 동일, goal tick 비용 측정 감소 |
   | R2 | 최신 값만 의미 있는 구독을 KEEP_LAST depth 1로 | B | 예 | 대상 목록과 근거, 적체 재현 시험, rig 교차 A/B |
   | R3 | `EventsExecutor` 도입 | B | 예 | rig A/B(executor만 교체) 뒤, 제품 진입점은 파라미터로 선택. sim-time 타이머·종료·콜백 순서 검증 |
   | R4 | rig 환경 가드와 세션 간 Gazebo 배타 잠금 | 도구 | 아니오 | 과부하 실행을 '환경 무효'로 표시, 판정 스크립트가 무효 실행을 세지 않음 |
   | R5 | `footprint_sweep` 정확 최적화 | E | 아니오 | 먼 점의 증명적 제외 또는 시간 샘플 벡터화, hull 캐시. 결과 동일 |
   | R6 | rig `/clock` 빈도 조정 | 도구 | 아니오 | gz 설정 방법 확인, 타이머 해상도 영향 검증 |
   | R7 | 단일 프로세스 모드 결함 원인 규명 | 조사 | 선택 | 원인 기록. 수정 여부는 별도 결정 |
   | R8 | Pi 계측 | 측정 | 예 | 같은 계측을 실기용으로 바꿔 R1–R3 전후 수치 확보(DEVICE gate) |

   R2의 대상 후보는 calibration의 `safety/decision`과 safety의 명령 입력이다. 이 둘은 착수 때 확정한다.

   **R1 구현 메모 (2026-09-24).**
   - 캐시 대신 `inflate` 자체를 결과가 동일한 numpy 구현으로 바꿨다. 호출당 비용은 200×200에서 48→6 ms,
     400×400에서 128→22 ms로 줄었고, 희소 지도에서도 원본보다 빠르다.
   - SLAM 지도는 1 s마다 바뀌므로 캐시만으로는 매 계획의 첫 호출 비용이 남는다.
   - 캐시는 필요해지면 따로 결정한다.
   - 측정은 호출 단위이고 goal tick 단위가 아니다.

   **R4 구현 메모 (2026-09-24).**
   - `tools/gz/rig_environment.py`가 실행 중 2 s마다 부하, CPU 압력(PSI), Gazebo 세션을 기록한다. 기록기는
     잠금 fd를 닫고 실행되며, rig 스크립트가 끝나면 함께 끝난다.
   - 실행이 무효인 조건은 다음과 같다. 모든 조건은 첫 60 s를 제외하고 판단한다.
     - 평균 부하 16 이상
     - 요청한 속도 대비 0.1 미만의 시뮬 속도
     - 같은 파티션에 Gazebo 세션이 둘 이상
   - 무효면 `RIG ENVIRONMENT: INVALID`를 내고 종료 코드 3으로 끝난다. 통과·실패는
     `RIG VERDICT (environment-invalid, not counted)`로만 표시한다. 판정기가 비정상 종료하면 종료 코드 3과
     구분된다.
   - 속도 판정에는 증거가 필요하다. 모니터가 잰 sim 10 s 이상과 그 구간의 벽시계 시간이다. 증거가 없으면
     통과·실패 판정을 그대로 둔다. 실제 실패를 "환경"으로 덮지 않으려는 규칙이다.
   - CPU 압력(PSI `some avg10`)과 부하 16 이상 표본 비율은 기록만 하고 판정에는 쓰지 않는다. 다른 세션의
     Gazebo가 없는 단독 실행에서도 부하 16 이상 표본이 29%였다. PSI 기준은 기록된 실행으로 보정한 뒤
     판정에 넣는다(사용자 승인 2026-09-24).
   - 매트릭스 러너(`run_calibration_spaces.py`)는 3을 `environment_invalid`, 4를 `lock_busy`로 두고
     통과·실패 집계에서 뺀다.
   - 세션 간 Gazebo 잠금(`/tmp/rosy-gazebo.lock`)은 이 rig만 잡는다. 다른 Gazebo 실행기(`gz_sim` launch,
     `run_fleet_sim.sh`, localization rig)의 채택은 단계적이다. 그전까지 피어 부하는 가드가 측정만 한다.
   - control 패키지 크기(D-168 P6)는 split 판정을 유지한 채 기준만 28,476줄로 재판정했다.

   **R8 구현 메모 (2026-09-24).**
   - `src/apps/control/tools/device/hotpath_measure.py`를 만들었다. ROS 없이 돌고, 하위 명령마다 JSON 보고서
     하나(`rosy.control.hotpath_measure/1`)를 쓴다.
   - `bench`는 `wall_tracker._segments`(720-ray), `match_motion`(180점, 10° 회전), `inflate`(200×200, 반경
     5셀)의 median·p90·max를 잰다. 입력은 동등성 테스트 생성기와 같은 형태다.
   - `watch`는 control 노드 프로세스별 CPU%(`/proc/<pid>/stat` 차분)와 RSS, 부하, PSI를 간격마다 기록한다.
   - 보고서는 `/proc/device-tree/model`이 Raspberry Pi일 때만 실기 증거로 표시한다. host 수치(Windows x86
     `match_motion` 80 ms 등)는 증거가 아니다.
   - 실기 실행은 HOLD다. 하드웨어가 없어 Pi 수치는 아직 없다. 절차는 도구 docstring과 device 검증 계획의
     2026-09-24 checkpoint에 있다.
   - control 패키지 크기(D-168 P6)는 split 판정을 유지한 채 기준만 28,868줄로 재판정했다.

   **R3 구현 메모 (2026-09-24).**
   - 선택은 파라미터가 아니라 환경 변수 `ROSY_EXECUTOR`(`single` 기본, `events`)로 한다. 노드 파라미터보다
     먼저, 노드 밖에서 정해야 하기 때문이다. 표의 "파라미터로 선택"은 이 방식으로 대체한다.
   - 14개 control 노드 `main()`과 rig가 `control/executor_choice.py` 하나를 거친다. 기본값은 이전과 같은
     `rclpy.spin(node)`다. `events`는 executor의 native `spin()`을 써서 rig와 같은 루프를 잰다.
   - `events`에서 알려진 차이: 콜백이 도착 순서로 돈다. 다른 스레드가 context를 끄면
     `ExternalShutdownException`이 난다. 콜백이 예외를 내면(watch_node `--once`의 SystemExit) native
     executor가 FATAL 줄을 먼저 남긴다. 종료 코드는 유지된다.
   - WSL 탐침(리뷰): SIGINT·SIGTERM 처리, sim-time 타이머, 다른 스레드의 `call_async`는 두 방식이 같았다.
   - R3는 아직 완료가 아니다. rig A/B(ENV:VALID 실행만), 콜백 순서 영향, 실기 측정(R8)이 남았다. 그전까지
     제품 기본값은 `single`이다.

   **R5 구현 메모 (2026-09-24).**
   - 시간 샘플 벡터화와 먼 점의 증명적 제외를 함께 썼다. 샘플별 원판 하한이 정확한 상한 U보다
     1e-6 이상 크면 그 점을 뺀다. 좌표·변 길이·내접 비율 가드를 못 넘으면 원본 경로로 계산한다.
   - 남은 점이 적으면 샘플을 쌓아 한 번에, 많으면 원본 `_clearance`로 샘플마다 계산한다. 모든 점을
     쌓은 broadcast는 루프보다 1.8배 느렸다.
   - 직진 한계는 `clearance > margin` 비교만 내보내므로, 이동 끝을 포함한 원판 하한이 margin을 넘는
     점을 호출당 한 번 뺀다.
   - 호출당 비용(host, 1440점)은 sweep 21–23→4–6 ms, 직진 한계 5–39→2–8 ms다. 점이 모두 가까운 최악
     입력에서는 원본과 비슷하다(20.9→19.7 ms).
   - 원본은 numpy 스칼라 명령 인자에 `np.float64`를 반환한다. 결과 동일 조건이라 그대로 두었다.
   - 독립 리뷰(APPROVE, MEDIUM 1·LOW 3) 반영: 직진 후보 가드를 maximum ≥ 1e-3으로 올리고(여유 약 1e4), 가드에 유한성 검사를 넣고, 반올림 논증을 |e|·r/R 기준으로 고쳐 쓰고, 가드 경계 코퍼스를 추가했다.
   - main 병합 후 control 패키지 크기(D-168 P6)는 split 판정을 유지한 채 기준만 29,037줄로 재판정했다(R3·R8 누적).

4. **범위 밖.** 줄 수·패키지 구조(D-168·D-171), 안전 판정 자체의 임계값은 바꾸지 않는다. CPU 절감을 이유로
   신선도 창이나 게이트 조건을 완화하지 않는다.

**Consequences:**
- 항목마다 비용과 결과가 기록된다. 실기 이득이 없는 항목(R4–R6)은 rig 판정력을 되찾기 위한 것임을 분명히 한다.
- 이 ADR만으로는 gate가 바뀌지 않는다. 실기 수치는 R8 전까지 HOLD다.
