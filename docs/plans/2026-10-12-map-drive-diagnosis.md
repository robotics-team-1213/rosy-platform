# map_v2_fleet 길 찾기 실패의 단계별 진단

2026-10-12. 기준 소스 commit `1e2dc23557`.
지도는 `map_v2_fleet` / `260919 MAP FILE.STL`의 curved 파생 자산을 유지한다.
이번 작업은 기존 D-676 실행과 D-708 관측 경로 기억의 후속 진단이다.

## 문제와 작업 경계

R29의 목표 소실, R31/R34의 관측 곡선 거절, R34/R35의 물리 정지 실패를 구분한다.
카메라에 보이는 곡선과 안전하게 채택할 수 있는 목표는 같은 증거가 아니다.
D-708은 독립 관측으로 확인한 형상을 짧은 공백 동안 유지하지만 최신
`drivable_closed` 거절을 덮지 않는다. 따라서 이를 완주 해결로 기록하지 않는다.

기존 helper와 topic을 재사용한다. 새 주행 API나 별도 최종 명령 publisher를 만들지 않는다.
CORE는 최종 명령을 소유하고 Fleet의 통행·회전 권한은 별도로 검증한다.

## 진단과 업데이트 구분

| 단계 | 입력과 직접 readback | 변경 대상 | 통과 기준 |
|---|---|---|---|
| 실행 환경 | source/map/model SHA, effective config, ROS domain, Gazebo partition, 자원 예약 | runner 또는 launch | 지정 소스·맵·모델이 실제 적재되고 타세션과 격리됨 |
| 관측 | RGB, class mask, ground, 원본 시각, source/current odom | Perception | 사용한 frame과 투영·기억의 시각을 함께 재현함 |
| 목표 채택 | centre polyline, 출구 후보, remembered edges, `exit_behind_line`, `ahead_m`, `target_now_m` | Drive 관측 추종 | 채택과 거절 모두 원래 경계 검사로 설명됨 |
| 경로 안내 | `line/lane_guide`와 `line/route_context`의 publisher·메시지, CORE lane cue, Fleet route와 pose trust | 안내 배선 | 각 채널의 발행·수신·만료·효과를 구분해 확인함 |
| 최종 명령 | CORE mode/owner, body/scan/containment refusal, 최종 command와 실제 odom | CORE | 권한과 안전 게이트가 승인한 명령만 나감 |
| 물리 정지 | zero command, wheel/caster 속도, 연속 정지, reset와 cleanup | simulator actuator/contact | 기존 정지 기준을 그대로 만족함 |

수정은 실패한 단계의 경로에만 적용한다. mask replay, 원격 pytest, 실제 Gazebo,
Isaac SDK, CI, 장치·현장 수용은 별도 결과로 기록한다.

## 실행 순서

1. 저장된 frozen-model 실패 mask를 최신 소스에서 원격 재생한다. 기존 출구 원호와
   중심 목표 및 짧은 lookahead를 같은 `_crosses`로 비교한다. 새로운 추론 결과를
   과거 실시간 mask나 정답 라벨이라고 부르지 않는다.
2. 여유 있는 sim PC에서 최신 committed source의 별도 build/install/run을 만든다.
   먼저 정지 카메라·observer·CORE·Fleet를 연결하고 guide publisher와 관측을 수집한다.
   `--pick sim`은 자원 예약을 수행한다. 실행 전후 자신이 소유한 예약·PID를 확인한다.
3. 후보가 실제 관측 corridor와 기존 안전 검사에 적합하면 해당 반례를 회귀로 고정하고
   공유 알고리즘을 최소 변경한다. 경계 검사를 삭제하거나 닫힌 길을 기억으로 덮지 않는다.
4. 관련 원격 회귀와 독립 소스 리뷰 뒤 같은 source/model/map에서 제한된 주행을 비교한다.
   실패한 단계, 진행 거리, 목표 채택, 최종 정지·cleanup을 함께 기록한다.

## 최초 확인

- 기준 소스는 main에 착지·원격 push 완료. 추가 pre-push 원격 시험 291 PASS,
  착지 시험 6,130 PASS/359 SKIP/NEW 0이다. CI는 별도 확인한다.
- R34 저장 trace에는 `exit_behind_line=true`, `drivable_closed`, `ahead_m=0`,
  `target_now_m=null`이 있다. D-708은 이 최신 거절을 보존한다.
- 소스에서 `line/lane_guide` subscriber는 발견했으나 publisher를 발견하지 못했다.
  실행 graph 확인 전에는 publisher가 없다고 확정하지 않는다.
- AI PC의 기존 Gazebo 준비물은 과거 snapshot이다. 새 build와 관측 실행을 준비한다.
  준비 상태는 실제 실행·주행·완주 성공이 아니다.

## 후속 결과

- 최신 소스의 AI PC 단일 frame 재생에서 실패 66/77은 `drivable_closed`와
  `exit_behind_line=true`를 재현했다. 89는 이력 없이 `drivable_creep`이므로
  같은 실패를 재현했다고 기록하지 않는다. 세 mask의 SHA와 실제 imported source를 확인했다.
- 짧은 lookahead 일부가 `_crosses`를 통과했으나 그 검사는 목표 이전 중심 원호에 대한
  15mm 경계 교차 검사다. 몸체 폭 전체의 여유를 증명하지 않는다. 후보 일부는 최초
  관측 x보다 앞에 있고, 관측 범위의 후보도 보수적인 body+paint 여유 검사를 충족하지
  못했다. 따라서 짧은 목표를 바로 채택하는 fallback은 구현하지 않았다.
- AI PC Gazebo r2는 기준 소스 7,494 파일 hash를 확인하고 17 ROS package를 새로 빌드했다.
  두 CORE에서 각각 최종 명령 1,671/1,670개가 전부 zero, odom 정지,
  line/keep_debug 각각 268개를 관측했다. 현재 drivable centre와 live expected path가
  생성됐다. 두 `line/lane_guide`의 publisher 목록과 개수는 실제로 비어 있었다.
  현재 keep 모드에서 `lane_graph_path` 설정만으로 이 legacy heading guide가 생성되지 않는다.
  CORE의 `line/route_context`와 observer의 수신 경로는 이미 존재한다. 따라서 legacy
  lane guide가 없다는 사실을 모든 trip 안내의 부재로 확대하지 않는다. 실제 trip에서
  route context의 positive sequence·신선도·bend 효과와 CORE cue를 따로 확인한다.
- r2 전체 runner는 Fleet의 `rosy.contracts.learning.incident_rule` import 실패로 exit 1이다.
  CORE 센서·정지 관측 성공과 Fleet 연결 실패를 구분한다. 종료 후 자기 partition의
  프로세스 부재, 세 포트의 연결 거절, 자기 lock 부재와 source hash 보존을 확인했다.
- 거절 trace가 admission 실패 전의 원인을 잃는 진단 누락을 보강했다. `camera_target`에
  reason·경계 거절·관측 중심 경로·near centre·벽 여유를 보존한다. 기존 zero 명령과
  admission은 유지한다. 원격 RED 3 FAIL 후 전체 Isaac 214 PASS/1 SKIP/NEW 0,
  독립 SOURCE APPROVE다. 최초 GREEN 전송의 SSH timeout은 시험 통과에 포함하지 않는다.
- Gazebo r3는 같은 소스와 모델에서 supervised CAMERA_LINE 요청을 실제 CORE에 전달했다.
  0.17 sim s에 `authority_none` HOLD로 거절됐으며 누적 이동은 0m,
  두 CORE 명령 각각 1,682개가 모두 zero였다. OFF 200·최종 OFF·실제 odom 연속
  0.3 sim s 정지를 확인했다. 전체 runner exit 0, source hash 보존과 자기 partition
  프로세스/포트/lock 종료를 독립 확인했다. 실제 주행 성공은 아니다.
- r3의 Fleet import 누락은 같은 소스의 `contracts/learning/src` 검색 경로를 포함해
  해결했다. ROS package build 성공만으로 Fleet wheel source closure를 증명하지 않는다.
- r3의 CORE overlay는 `authority_required=true`였으나 Fleet camera site는 통행권 발급이
  기본 false였다. 기존 기본 CORE/Fleet의 false/false 조합과 이 통행권 실행의 true/true
  조합을 구분해야 한다. shared camera site만 true로 바꾸면 기존 CORE false인 실행은
  `TRIP_AUTHORITY_NOT_REQUIRED`로 거절된다. 새 실행 manifest의 두 설정과 실제 caps를
  대조하고 기존 Fleet trip/AuthoritySender로 권한을 생성한다.

## 실제 센서와 주행 전제 확인

- Gazebo r5는 실제 Fleet plan 200 이후 start 422의 `TRIP_MODE_UNSUPPORTED`와
  `JUNCTION_TURN_UNSUPPORTED`를 확인했다. 이동 0m, CORE lease 없음, OFF 200과
  실제 정지를 확인했다. pose 기반 계획 생성과 실행 capability 검사는 별도 계약이다.
  회전 지원을 강제 표시하지 않고 D-400 motion basis의 실제 센서 증거를 확인한다.
- r6는 기존 URDF의 세 downward ray를 ROS bridge와 기존 `sim_ir_floor`에 연결했다.
  private SIM profile의 `sensor_adapter.mode=enforce`와 `simulation_sensors=true`를
  사용했다. 가짜 IR 값이나 현장 floor walker 선언은 사용하지 않았다. 두 로봇 각각
  세 ray가 동일 시각인 514/514 프레임, 실제 IR·IMU·scan과 junction_turn 및 lane_bend
  capability를 확인했다. 첫 로봇의 safety blocked=true는 유지하고 두 번째만 false였다.
  두 CORE 최종 명령 1,283/1,281개가 모두 zero였다. runner exit 0, 정지와 자기
  프로세스·포트·lock 종료 및 원래 소스 hash 보존을 확인했다. r6는 주행 시험이 아니다.
- 센서 helper에서 최신 mid와 오래된 좌우 ray를 합쳐 바닥 증거를 갱신하는 별도 오류를
  수정했다(commit `8226c122f8`). 세 채널의 동일한 정규 timestamp와 source age를
  검증하고 한 프레임을 한 번만 발행한다. 원격 Gazebo 318 PASS/4 SKIP/NEW 0,
  독립 SOURCE APPROVE, 착지 검사 584 PASS/4 SKIP/NEW 0 및 push 검사 291 PASS다.
  main commit `3d5f58a3e9`까지 푸시했다. r6는 수정 전 helper 실행이므로 새 helper의
  실제 실행 증거로 대체하지 않는다.

다음 주행 시험은 safety blocked=false인 두 번째 로봇만 실제 Fleet trip·통행권으로
실행한다. 첫 로봇은 OFF를 유지한다. CORE 소스 commit `1e2dc23557`과 새 helper
commit `8226c122f8`의 조합을 명시하며 전체 최신 소스 실행이라고 부르지 않는다.
private SIM profile에서 기존 typed `line/route_context`를 활성화하되 실제 positive seq와
CORE cue는 별도 확인한다. 5 sim s·누적 이동 0.15m·wall 8s 중 먼저 닿는 문턱에서
OFF와 취소를 요청한다. 정지 중 이동을 포함한 총거리, lease 해제·OFF readback·실제
연속 정지를 따로 확인한다. 준비 코드는 독립 SOURCE
APPROVE이며 자원 gate가 거절한 시도는 실행·주행 결과에 포함하지 않는다.

## 한정된 실제 Fleet trip

r7는 정규 sim 자원 gate를 통과해 같은 지도와 모델에서 실행했다. Fleet plan/start 200,
실제 trip lease와 CORE FREE 통행권을 확인했다. 새 helper는 세 ray의 동일 시각 프레임
525건을 수신하고 ADC 495건을 발행했다. 이 차이는 source age·중복 frame 검사 후 실제
발행량이며 r6의 수정 전 helper 증거와 구분한다. typed route context publisher는 존재했으나
메시지와 positive seq는 관측하지 못했다.

진단 stop guard가 이전 제어 tick의 HOLD/authority_none과 갱신된 FREE 통행권을 함께 읽어
즉시 OFF를 요청했다. 이동 0m·모든 명령 zero이므로 CORE의 차체 거절이나 방향 소실을
재현했다고 판단하지 않는다. cancel 200과 terminal canceled, lease 해제, OFF 200,
실제 연속 정지와 자기 프로세스·포트·lock 종료를 확인했다. 다음 시험은 이 진단 guard가
현재 authority가 FREE/HOLDING인 혼합 응답의 authority_none만 재관측하도록 고친다. 다른 거절,
정지 문턱, 통행권과 실제 센서 검사는 유지한다.

r8는 이 진단 판정만 수정하고 정규 자원 gate를 통과했다. Fleet start 200·lease와
CORE FREE 갱신을 거쳐 TRACKING 및 양의 최종 명령을 관측했다. 선택한 두 번째 로봇의
최대 명령은 0.08221m/s·0.36036rad/s였고 첫 로봇 명령은 모두 zero였다. 4.488 sim s에
누적 이동 0.171995m에서 정지를 요청했다. 0.15m 문턱보다 약 22mm 늦게 감지됐고,
정지 중 약 7.1mm를 더 이동해 최종 누적 거리는 0.179107m였다. cancel 200과 canceled,
lease 해제·OFF 200·실제 연속 정지 및 자기 실행 cleanup을 확인했다. runner exit 0이다.
typed route context 메시지는 0회다. 이 실행은 실제 전진과 종료의 증거이며 지도 완주나
곡선 목표 소실 수용의 증거로 사용하지 않는다. 짧은 이동 문턱만으로 정확한 최종 거리
상한을 보장하지 못했으므로 후속 시험에서도 요청 시점과 정지 후 총거리를 함께 기록한다.
계획 speed_cap은 0.08m/s였으므로 최대 명령과 약 2.2mm/s 차이가 있음을 보존한다.
독립 소스 추적에서 이 값은 경로 비용·ETA에만 사용되고 CAMERA_LINE 시작과 통행권에는
속도 필드가 없음을 확인했다. 실제 Pinky profile의 cruise/max는 0.10m/s다. 따라서
CORE hard cap 위반이나 적용 지연으로 단정하지 않으며, 계획 속도와 실행 한도의 연결이
없다는 경계로 기록한다. 이 결과로 0.08m/s 준수를 수용하지 않는다.
start 이후 목표는 계속 live였으며 held 사용과
목표 소실은 관측하지 않았다. 후속 비교는 이 곡선 관측의 비주행 replay에 짧은 목표
gap을 넣어 strict-stop과 bounded ExpectedPath의 변환·예산·새 충돌 거절을 대조한다.

제품 수정 commit `3d5f58a3e9`의 전체 CI run `38206143801`은 terminal SUCCESS다.
후속 실제 실행은 최초 CORE와 새 IR helper의 조합이므로 전체 최신 main 실행과 구분한다.

현재 길 찾기 해결·네 방향 완주·물리 정지 안정성은 미확인이다.
