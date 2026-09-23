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

4. **범위 밖.** 줄 수·패키지 구조(D-168·D-171), 안전 판정 자체의 임계값은 바꾸지 않는다. CPU 절감을 이유로
   신선도 창이나 게이트 조건을 완화하지 않는다.

**Consequences:**
- 항목마다 비용과 결과가 기록된다. 실기 이득이 없는 항목(R4–R6)은 rig 판정력을 되찾기 위한 것임을 분명히 한다.
- 이 ADR만으로는 gate가 바뀌지 않는다. 실기 수치는 R8 전까지 HOLD다.
