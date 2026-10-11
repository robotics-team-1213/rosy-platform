# isaac_sim logs

## 2026-09-30 · uncommitted · chore(sim): add package marker for the structure scan (D-322, D-168)

- 변경: `package.xml`·`setup.py`·`resource/isaac_sim`·`AGENTS.md`·`progress.md`·`logs.md` 신설 — `src/sim/isaac_sim`이 D-168 구조 스캔에 보이게. Isaac 실제 실행은 별도(D-322 HOLD).
- 증거: `test/architecture/test_module_structure.py` 구조 스캔이 isaac_sim을 패키지로 인식하는지 확인.
- gate 변화: 없음.
- 결정: 마커 전용 — 설치·빌드 불가. honest-hole 노트 제거.
- 교훈: 없음.

## 2026-09-30 · uncommitted · fix(sim): isaac_sim 등록 뒤끝 — functional surface·gate 정확화

- 변경: harness.yaml isaac_sim 항목에 tests·functional_kind(pytest)·functional(자기 시험 3건)을 선언해 D-73 계약을 충족. progress.md의 cmd ":" 노옵을 실제 시험 명령으로 바꾸고 ROS-SIM을 N/A에서 HOLD로 정정(D-322가 Isaac 실행·ROS-SIM 수용 HOLD를 명시). AGENTS.md "no own tests" 문구를 실제(test/ 3건)에 맞게 수정하고 Key Files에 model_checks·import_omx·prepare_omx_urdf·run_rosy·test/를 추가.
- 증거: test_module_functional_surface 4 passed(등록 후), src/sim/isaac_sim/test 3 passed — 2026-09-30 Windows (수정 전 functional surface는 1 failed: functional_kind None).
- gate 변화: isaac_sim ROS-SIM N/A→HOLD (D-322 명시와 일치; 새 blocker 기록).
- 결정: 없음.
- 교훈: 패키지 마커 랜딩은 harness functional surface까지가 한 단위다 — 노옵 cmd(:)로 GO를 통과시키면 다음 게이트가 붉다.

## 2026-09-30 · uncommitted · fix(sim): isaac_sim을 D-310 target 표에 등록

- 변경: test/architecture/test_target_layout.py의 TARGET에 "sim/isaac_sim": "sim/isaac_sim"(자기 경로 — 이동 없음, sim 도메인 유지)을 추가. 패키지 마커 랜딩이 구조 스캔만 보고 이 배치 계약은 놓쳤다.
- 증거: test_target_layout 전체 통과(포함 test_each_package_sits_where_the_phase_allows) (2026-09-30 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 새 패키지의 체크리스트는 package.xml·harness functional·D-310 target 세 곳이다 — 이번에 두 곳을 놓친 것이 CI를 3단계 붉게 만들었다.

## 2026-10-04 · uncommitted · docs(isaac): 모델 PC의 주행·관제·적재 연계 검토

- 변경: 단일 CORE 주행·정지, Nav2, 두 로봇 Fleet, 이동 후 적재 순서의 목표와 원격 호스트·clock·명령·독립 관측 책임을 정리했다. 현재 6.1 import API와 D-434의 5.1 설치 기록 차이, watchdog·센서·다중 로봇 미수용을 명시하고 stale progress 경로/버전 설명을 고쳤다. 런너와 SDK 코드는 바꾸지 않았다.
- 증거: 현재 learning/envs/isaac/test 10 passed/1 skipped. 실제 xacro 렌더는 overlay 부재로 skipped. 5.1 공식 ROS 2 Navigation/Clock 문서와 현재 graph·CORE navigation remap을 대조했다. 모델 PC runtime은 실행하지 않았다.
- gate 변화: SOURCE/LOCAL 상태 유지, ROS-SIM HOLD 유지. host helper 시험은 실제 주행 수용이 아니다.
## 2026-10-04 · uncommitted · fix(isaac): SDK 호환 import와 명령 만료 경계

- 변경: 5.1 legacy importer와 최신 API를 capability로 구분하고 defaultPrim이 있는 USD를 live stage에 참조한다. 명령 수신 시각 기반 watchdog과 graph/USD wheel-target 초기·pause·reset·stale zero를 추가했다. 실제 SDK에서 확인된 graph attribute 경로를 절대 경로로 연결하고, SDK 종료가 Python 예외를 exit 0으로 덮지 않게 했다.
- 증거: host 33 passed/1 skipped, owned Python lint·diff 통과. 독립 리뷰는 최신 source와 모델 PC run7 증거를 직접 확인했다. Isaac 5.1/Python 3.11/격리 CPU Torch 2.7 환경에서 graph callback 120회, Gate와 USD wheel target zero 확인 243회, 독립 observer clock/odom 각 117개. Twist publisher 없이 실행했다.
- gate 변화: ROS-SIM HOLD 유지. SDK close 반환 뒤 interpreter가 제한 120초를 넘어 exit 124로 종료됐다. 실제 바퀴 속도·주행 중 명령 단절 정지·Nav2·두 대 Fleet·GPU Torch 학습은 미검증이다.
- 결정: 기존 모델 PC checkout/SDK/ML 환경을 보존하고 별도 검증 환경만 사용했다. 한 번의 무주행 graph 결과를 I1 주행 수용으로 승격하지 않는다.
- 교훈: ScriptNode output은 graph가 멈춰도 남을 수 있으므로 graph 밖에서 USD drive target까지 0으로 만들고 읽어 확인해야 한다. SDK 정상 반환과 프로세스 정상 종료를 따로 기록한다.

## 2026-10-04 · uncommitted · fix(isaac): CORE I1 경로 실측과 passive caster 검증

- 변경: SDK CLI는 실제 runner cleanup 뒤 원래 종료 코드를 유지하며 종료한다. 명시적인 finite-positive `--wheel-damping`과 live USD readback 검증을 추가하고, URDF로 비구동 continuous caster임을 확인한 두 joint의 importer servo만 해제한다. wheel command·속도 제한·freshness·CORE 단일 publisher는 보존했다.
- 증거: gain/passive 검사는 RED 후 구현했으며 host 69 passed/1 skipped, 신규 known failure 0, scoped Python lint·diff 통과. 독립 source review 후 모델 PC에서 실제 CORE auth API·단일 publisher·odom/joints/clock·applied gain/action을 관찰했다. A07은 1000 graph callback, 593 Twist receipt, 367 graph/USD target zero readback, SDK main 정상 반환·CORE/SDK exit 0·두 소유 PID 부재를 확인했다.
- gate: I1 주행·물리 정지는 HOLD. CORE cmd_vel 만료는 약 0.4초에 zero지만 전진 추종 실패·회전 만료 후 actual yaw drift가 남았다. finite-frame 종료 후 SDK GUI callback traceback 2건과 native interrupt-close 오류도 close 반환·process 종료와 별도다. 세부 시도·hash·남은 일은 [I1 실측 기록](../../../docs/validation/cell-isaac-2026-10-04/isaac-core-drive.md)에 기록했다.
- 교훈: command target zero를 실제 stop으로 승격하지 않는다. importer가 passive caster에 position drive를 만들 수 있으므로 actuator identity와 실제 tensor gains를 확인한다. 정상 SDK close·process 종료와 native interrupt-close 오류는 분리 기록한다.


## 2026-10-04 · uncommitted · fix(ci): keep physics regression sources plain UTF-8

- 변경: passive-caster 및 wheel-damping Python 시험의 UTF-8 BOM만 제거했다. 모델과 시험 본문은 같다.
- 증거: main CI의 source encoding guard가 두 파일을 지목했다. 수정 뒤 source guard PASS, 두 Isaac 시험 24 PASS, 독립 byte-only 검토 APPROVE.
- gate 변화: SOURCE/LOCAL 형식 수정이다. 새 physics/device/field 증거를 주장하지 않는다.

## 2026-10-11 · a759f1e6f · fix(isaac): 최신 CORE 메인 위에서 헤드리스 재시험

- 변경: main ea6d4c0a2의 D-627/D-628/D-630 구조를 유지하고 기존 SDK headless/importer/force-drive 수정과 회귀만 적용했다. SDK 전용 pins와 실제 경로·운용 안내를 갱신했다. CORE·계약·Fleet 실행 권한은 그대로다.
- 증거: 원격 전체 CORE/Isaac/설치 4361 passed, 11 skipped, 0 NEW. 최신 archive 6982파일 hash를 전후 확인한 R2에서 SDK 2400 frames/exit 0, CORE 단일 publisher와 실제 직진·만료/CORE-loss 정지를 관측했다. R1의 이전 archive 덧씌움은 SHA readback으로 적발해 수용 증거에서 제외했다.
- gate 변화: SOURCE/LOCAL GO, ROS-SIM HOLD 유지. 회전 목표 0.3 rad/s 대비 실제 0.19396으로 observer/scenario exit 1이다. 실제 맵·센서·두 대 Fleet·RL은 미검증이다. [최신 검증 기록](../../../docs/validation/isaac-latest-core-main-2026-10-11/result.md).
- 교훈: 최신 main에서 만든 archive라도 실행 스크립트가 옛 소스를 덧씌울 수 있다. 실제 runtime 파일 hash를 실행 전과 정리 후 확인한다.

## 2026-10-11 · dc25401e61 · feat(isaac): 실제 맵 한 대 CPU RL 진단

- 변경: D-638에 따라 기존 STL generator·curved graph·Drive PathFollower·CORE CommandManager/최종 port를 재사용하는 simulation-only CPU Q-learning을 추가했다. 경로 창은 기존 alignment 이력을 유지하고 POLICY freshness·epoch·제한을 최종 출력까지 검증한다. 운영 CORE/Fleet API는 추가하지 않았다.
- 증거: R6 baseline/학습 6회/고정 eval 202·303 complete, 37,591 Q updates, 9.342m ordered 경로와 실제 stop dwell 확인, SDK exit 0. R6 GUI close traceback 1건은 R7의 공유 headless-close 수리로 별도 재시험했고 SDK exit 0/error 0/잔여 PID 없음. source 전후 7,014파일 확인, policy SHA와 원시 evidence는 [결과](../../../docs/validation/isaac-map-rl-2026-10-11/result.md)를 따른다. 관련 원격 회귀/known_failures NEW 0과 독립 소스 검토를 거쳤다.
- gate: SOURCE/LOCAL GO 유지, 전체 ROS-SIM HOLD 유지. 단일 native CPU 진단은 D-606 Isaac Lab, ROS localization/sensors, 두 대 Fleet·신호 및 실물 수용을 대신하지 않는다. baseline도 완주했으므로 성능 향상은 주장하지 않는다.
- 기록: 내부 날짜별 상세 일지는 `private/isaac/{plans,journal,results,templates}/`, 원시 로그는 관리된 X: session이다. 이번 RL topic은 main 착지·push 전 상태다.
- 교훈: 작은 caster의 60Hz 접촉 진동은 zero target만으로 stop이 아니다. 240Hz 재시험도 raw body velocity와 dwell로 확인한다. importer가 시작 뒤 GUI 메뉴를 다시 켤 수 있으므로 headless stage-close 전에 실제 메뉴를 제거하고 종료 코드와 raw traceback을 따로 확인한다.

## 2026-10-11 · b6a8d0d2e8 · feat(isaac): 고정 정책 네 시작 방향 실제 화면 녹화

- 변경: 정책 JSON을 한 번만 제한 크기로 읽고 기존 QPolicy를 검증 복원한다. 평가 전용 0/+90/180/-90도 시작 방향, SDK Camera의 실제 RGBA→H.264·Fabric 시각/pose 기록, 실패 시에도 encoder close/wait/reap을 추가했다. 기존 CORE 최종 port·Drive·생산 API는 유지한다.
- 증거: TDD RED 뒤 b6a8d0d2e8 원격 Isaac/Drive/CORE cycle/harness exit 0/NEW 0, 독립 Safety-Review APPROVE. R8 전체 baseline/6학습/2고정 eval 재시험은 SDK exit 0/error 0, source 7,050파일 일치. R9는 고정 정책 네 방향 모두 9.342m ordered 경로 complete·물리 stop, 실제 960×540 영상 4개, source 7,053파일 일치, SDK exit 0/error 0. 원시 trace/프레임/MP4 전체 디코딩과 해시를 독립 검증했다. 상세 수치·정확한 실행 source는 [결과](../../../docs/validation/isaac-map-rl-2026-10-11/result.md)를 따른다.
- gate: SOURCE/LOCAL GO 유지, 전체 ROS-SIM HOLD. 네 시작 방향은 역순 경로·모든 방향·두 대 Fleet·신호·횡단보도 또는 센서/실물 수용이 아니다.
- 기록: 사용자의 private 보관 요청에 따라 최종 영상·미리보기·열람 페이지를 `private/isaac/media/2026-10-11-directions/`에 보관한다. 원시 로그/전체 trace는 X: session에 유지한다. 한국 교통 규칙과 Fleet는 새 후속 목표다.
- 교훈: Fabric의 referenceTimeNumerator/Denominator를 확인하고 프레임 시각 단조성과 실제 마지막 stop을 검사한다. pipe close 실패에도 child wait/kill을 수행해야 encoder가 남지 않는다.

## 2026-10-11 · 764b591ed6 · refactor(isaac): 여러 package 조합 진단을 tools/sim에 배치

- 변경: map_task/run_map_rl/native_recording을 기존 시뮬레이션 도구 소유인 tools/sim/isaac로 이동했다. SDK helper 위치·시험·CLI/계획 참조를 갱신했다. 기존 CORE/Drive 내부를 호출하는 도구를 learning package에 넣은 D-427 위반을 제거했다. 물리/학습/cleanup과 CORE 생산 코드 변경은 없다.
- 증거: 착지 검사에서 발견한 architecture/legacy-path/release guard NEW 4건은 실패로 기록했다. 수정 HEAD 764b591ed6의 원격 Isaac/architecture/release/harness exit 0, NEW 0. 독립 소스 Safety-Review는 저장소 경로·SDK helper 연결·최종 권한·물리 정지·정책 고정·source lineage를 승인했다.
- gate: SOURCE/LOCAL GO 유지. R8/R9 runtime 증거는 이전 SHA에 귀속하고 ROS-SIM/두 대 Fleet/실물 HOLD를 유지한다.
- 교훈: CORE를 재사용하는 진단은 여러 package를 조합하는 tools/sim의 기존 소유를 따른다. 이동 전 성공 실행으로 import/소유 검사를 대신하거나 새 위반을 허용 목록에 넣지 않는다.

## 2026-10-11 · fb355522f5 · fix(isaac): 유효 카메라 관측만 Q-learning에 반영

- 문제: 기존 카메라 runner가 관측 없는 기본 bin도 학습하고, camera loss 판정 전 갱신하며 실패 결과에서 실제 업데이트 수를 누락했다.
- 변경: 모델 관측의 source age와 처리 시간을 합쳐 freshness를 확인한다. 무효 관측과 이전 관측 없는 transition은 제외하고 연결을 끊는다. tick 도중 만료하면 권한 메타데이터를 유지한 zero 후보만 제출한다. loss 판정 뒤 학습하며 실패 결과에도 실제 updates와 제외 이유를 보존한다. 기존 경로 기반 update→choose 순서는 유지한다.
- 증거: 원격 RED 6 NEW/19 pass 및 만료 회귀 RED 1 NEW/25 pass 뒤 전체 Isaac 152 pass/1 skip, known_failures NEW 0. 독립 소스 Safety-Review 수용. native 재시험과 카메라 완주·두 대 Fleet·ROS-SIM·실물 수용은 아직 별도다.
- 목표: 같은 기존 인식 모델·CORE 주행의 고정 gain 기준선과 비교해 곡선의 오차·흔들림을 줄이는 효과를 검증한다. 신호·횡단보도·Fleet 통행권은 학습 보상으로 우회하지 않는다.
- gate 변화: SOURCE/LOCAL 유지. 카메라 전체 완주·두 대 Fleet·ROS-SIM·DEVICE·FIELD는 HOLD이며 이번 소스 회귀로 승격하지 않는다.

## 2026-10-11 · 152cb908fe · feat(isaac): 동일 조건 카메라 기준선과 고정 정책 비교

- 문제: baseline101과 eval202/303은 시작 조건이 달라 RL 개선의 직접 비교 근거가 아니었다. 전역 frame 기반 카메라 cadence도 episode마다 달랐다.
- 변경: 카메라 학습 후 세 seed, 저장 정책의 네 시작 방향마다 고정 gain baseline과 고정 정책 eval을 짝짓는다. seed·방향·목표 초기 pose·시간 제한·정책 상태 hash 일치 및 실제 초기 pose 오차 한도를 검사하며 baseline 실패도 보존한다. 카메라 관측과 녹화를 episode 시작 기준으로 정렬하고 각각 실제 화면을 기록한다. 정책 상태 canonical hash와 원본 정책 파일 bytes hash를 구분한다. 기존 경로 정책 일정·CORE 최종 권한·물리 정지·독립 cleanup은 유지한다.
- 증거: 원격 RED 3 NEW/26 pass, 비교 admission RED 9 NEW/29 pass, 독립 리뷰 회귀 RED 7 NEW/35 pass 뒤 전체 Isaac 168 pass/1 skip·known_failures NEW 0·exit 0. 독립 Safety-Review는 152cb908fe의 cadence/hash blocker 해소를 확인하고 source 범위를 승인했다. 이후 main UI 통합 commit 4799c1972는 Isaac source 변경이 없다.
- gate 변화: SOURCE/LOCAL 유지. 실제 paired native freshness·완주·RL 개선은 아직 미입증이며 두 대 Fleet·한국 교통·ROS-SIM·실물 HOLD를 유지한다.
- 목표: 같은 기존 모델과 line_follow에서 곡선 오차·조향 변동을 비교해 RL의 추가 효과를 검증한다. 관측 손실·신호·통행권을 학습으로 우회하지 않는다.

## 2026-10-11 · e2a94abaa3 · fix(isaac): 현재 경로 접선과 전방 안내각 분리

- 문제: 카메라 guide의 현재 경로 방향 자리에 25cm 전방 목표각을 다시 전달해 기존 keep의 here/ahead 계약을 혼용했다.
- 변경: 기존 전방 목표각을 보존하고 현재 route index의 비중복 접선 방향을 별도 계산한다. 경로 끝은 마지막 비중복 구간을 사용하고 두 각도 모두 현재 yaw 기준으로 wrap한다. source 시각·진행·이탈·pivot 설정과 strict camera target·CORE 최종 권한·정책 고정·물리 정지는 유지한다.
- 증거: 원격 RED6 NEW/42 pass 뒤 전체 Isaac174 pass/1 skip·NEW0·exit0. 독립 source Safety-Review 수용 후 중복·끝 시험을 +y/90도로 보강한1610f52b2d도 같은 회귀를 통과했다. 기록된 실패 PNG의 고정 기존 모델 CPU replay는 here/ahead를 분리해도 guided pivot/target loss/HOLD를 유지했다. 입력 계약 수정이 목표 상실 해결이라는 증거는 없다.
- gate 변화: SOURCE/LOCAL 유지. 실제 native 새 입력·카메라 완주·RL 개선·벽 안전 센서 연결·두 대 Fleet·한국 교통·ROS-SIM·실물 수용은 미완료다.

## 2026-10-11 · c229738784 · fix(isaac): 명시적 렌더에서 카메라 receipt 갱신

- 문제: 정지 시간의 렌더 초기화는 SDK 기본 수집 주기의 simulation dt를 채우지 못해 current_frame이 초기값0으로 남았고 기존 Fabric 검증에서 첫 녹화 쓰기가 거부됐다.
- 변경: recording/front Camera의 frequency를 매 렌더 수집(-1)으로 명시한다. 관측24-step/녹화48-step cadence, legacy path 렌더 cadence, 실제 frame 검증·freshness·CORE·정지·cleanup은 유지한다.
- 증거: 원시 receipt0 재현과 기본120Hz→-1 단일 변수 진단 뒤 c229738784 원격 Isaac174 pass/1 skip·NEW0·exit0 및 독립 source Safety-Review 수용. wrapper 없는 committed-source native에서 전체7123파일 hash를 고정했다. baseline101은 유효98/101관측·10sim초·0.190177m·시간 제한 뒤 실제 정지, Fabric 검증을 통과한52프레임 MP4를 확인했다.
- gate 변화: train0은 유효0/22관측·2.191667sim초 뒤 camera loss, updates0·invalid_camera_observation527로 후보를 거부했고 SDK exit1로 종료했다. 녹화 수정의 근거이며 전체 완주·RL 효과·두 대 Fleet·한국 교통·ROS-SIM·실물 수용은 미완료다.

## 2026-10-12 · 005a247b94 · fix(isaac): 첫 camera 학습 실패 뒤 다른 seed도 시험

- 문제: train0에서 유효 카메라 관측0이면 실패 기록·실제 정지를 남긴 뒤에도 다른 curriculum seed를 실행하지 않고 SDK 전체를 종료했다.
- 변경: 훈련 실패는 camera_usable=false로 남기고 다음 seed를 실행한다. 무효 observation은 Q 갱신에서 제외하고 episode reset/실제 정지·baseline/eval 유효카메라·updates>0·learned state 방문·heldout 전체완주 조건은 유지한다. seed 하나의 실패를 성공으로 바꾸거나 map-only 명령으로 대체하지 않는다.
- 증거: committed source 모델 PC 원격 camera_lane/map_task93passed·known_failures0NEW. 실패 episode의 무효 transition은 updates0, 이후 유효 transition만 update하며 baseline/eval 무효 관측은 여전히 거절하는 회귀를 포함한다.
- gate 변화: 없음. 실제 여러 seed native camera 학습·RL 성능 개선·전체 완주·교통/Fleet 수용은 미검증이다.

## 2026-10-12 · cb0ee3cd51 · fix(isaac): native scan을 CORE 몸체 경로 판정에 연결

- 문제: native scan은 drivable wall 요약·return evidence에만 전달돼 CORE 기존 body_stop/path 장애물 경로가 같은 센서 표본을 받지 못했다. R14 frozen-model replay에서 train0은 drivable영역을 인식하지만 guided drivable_pivot_right 선택 뒤 strict camera target 거절임을 확인했고, 높이5mm 차이로 해결되지 않았다.
- 변경: actual native 생성자는 scan과 같은 URDF nominal body·simulation collision box 회전반경을 받아 path/body 형상을 설정한다. 기존 gateway front_clearance를 호출해 동일 검증·body/scan points를 전달하고 return evidence를 중복 전달하지 않는다. native body 불일치와 no-return UNKNOWN은 관측/학습 admission에서 거절한다. guided pivot·map-only motion을 유효 camera state로 바꾸지 않는다.
- 증거: AI PC committed-source camera_lane/native_scan62passed·known_failures0NEW. 실제 표본에서 먼 벽은 주행, 정지 간격 내 가까운 벽은0, UNKNOWN은유효state없음, body불일치는거절을 검증했다. replay는 recorded pixels·CPU 추론이며 native 주행/학습/완주 증거가 아니다.
- gate 변화: 없음. actual native 재실행·유효RL·전체완주·교통/Fleet·실물 수용은 미검증이다.


## 2026-10-12 · eae0f59da0 · test(isaac): 카메라 RL 업데이트와 진단 실패 기록

- 변경: 실제 headless Isaac 한 대에서 고정 segmentation·기존 line_follow/Drive/CORE·native LiDAR 몸체 검사로 6개 순차 seed와 3개 baseline/frozen RL 쌍의 10초 진단을 실행했다. 유효 업데이트 1938회·상태 5개·무효 관측 2923개 제외. seed 0/1은 관측 0이며 나머지 seed는 70/1199/527/142회 갱신했다. 병렬 환경 학습은 아니다.
- 증거: SDK exit 1, held-out full-map completion failed. baseline 진행 0.190~0.200m·eval 0.180~0.200m, 평가 완주 0/3·모두 timeout으로 개선 미입증. 정책 hash 2492e21e54187bd0369009339c4b65be43583cb3b91ec6b3d020f721dc84b3c5. 실제 영상 7개 hash/ffprobe 960x540 프레임/렌더 순서·episode 정지·cleanup 정지·SDK 잔여 0 확인 후 private 51개 artifact hash 검증 보관. 훈련 영상은 없고 trace·전방 이미지는 보존한다.
- 자원: 사용자가 runtime ZFS ARC 상한 4GiB→2GiB를 적용하고 readback했다. 다른 세션 시험·서비스는 유지했으며 영구 설정 변경은 없다. 최신 main c90833b2a를 통합한 e4bf2710cf에서 Isaac/body 원격 264PASS1SKIP·Gazebo/domain 87PASS1SKIP·각 known_failures 0NEW.
- gate 변화: native 카메라 RL 유효 학습 생성 확인. 완주·정책 개선·네 방향·병렬 RL·교통/Fleet·Gazebo 두 대 주행·실물 수용은 HOLD 유지. 영상은 진단 부분 주행이며 full-lap이 아니다. 다음 실행은 최신 통합 소스의 긴 진단과 카메라 손실 원인 검증이 필요하다.

## 2026-10-12 · 25add33f95 · fix(isaac): 실패 픽셀 보존과 네 방향 진단 계속

- 변경: 0cb3c199b에서 무효 카메라 타깃의 여섯 진단 필드와 원인별 실제 PNG를 최대 8개로 제한해 기록했다. 25add33f95에서 camera admission 실패를 episode에 남기고 실제 정지 검증 후 다음 방향을 측정한다. 실패 pair의 비교를 제외하고 admission 오류 하나라도 있으면 full_map_complete=false·종료 실패를 유지한다. 무효 관측의 명령 0·학습 제외·고정 정책 검사는 유지한다.
- 증거: 원격 관련 시험 111 PASS 후 최종 117 PASS·각 known_failures NEW 0, 독립 소스 리뷰 차단 결함 없음. R18 실제 SDK는 600초 제한에서도 seed707 baseline/RL 약 0.220m에서 13.7/13.8초 차선 상실, +90도 seed808 유효 관측 0/18로 실패했다. 종료 1, 정책 SHA-256 불변. 실제 영상 3개 및 원본 19개 artifact hash·프레임·시각 순서·실제 정지·SDK 잔여 0 확인 후 private 보관했다. R19는 준비 소스 25add33f95의 7313개 파일을 검증하고 자원 예약 해제 뒤 22 cores·9GB와 빈 GPU에서 시작했다. 실행 시작은 결과 수용 증거가 아니다.
- gate 변화: 없음. 네 방향 native 최종 결과·완주·정책 개선·교통/Fleet·Gazebo 두 대 주행·병렬 RL·실물 수용은 HOLD다. 카메라 containment/crosswalk evidence의 native CORE 연결과 주의 표시 판정은 아직 미구현이다.

## 2026-10-12 · fff1b93a6 · fix(isaac): 콘솔 admission 오류와 R19 픽셀 재현

- 변경: admission 오류를 episode에 넣은 뒤 EPISODE를 출력해 콘솔에도 거절 사유를 남긴다. 기존 최종 수용·명령·학습 판단은 유지한다.
- 증거: committed-source 원격 camera_lane/map_task 103 PASS·known_failures NEW 0. R19 실제 네 방향 baseline/eval 8회는 모두 차선 상실로 SDK 종료 1, 정방향만 0.220m 진행했다. 실제 영상 8개 hash·ffprobe 960x540·프레임 수 및 원본 57개 복사 hash, episode/cleanup 실제 정지·정책 hash 불변·GPU 작업 종료를 확인했다. 원본 픽셀 14개의 CPU 재현은 모델 drivable 출력이 있으나 pivot/reorient 선택 뒤 native strict 관측이 거절함을 보여준다. 기존 CORE turn_spot/odom_pivot 회전 경로와 camera containment/Fleet cue 연결이 빠져 있으며 지도 pivot_ok=true는 회전 가능 증거가 아니다. 기록 및 재현 결과는 private에 보관했다. 단일 프레임 재현은 scan/시간 기억/주행 증거가 아니다.
- gate 변화: 없음. CORE 회전 검증 경로 연결·camera 재획득·완주·교통/Fleet·Gazebo 두 대 주행·병렬 RL·실물 수용은 미완료다. 무효 카메라를 학습 상태로 승인하거나 안전 정지를 해제하지 않는다.

## 2026-10-12 · fa75953dfe · feat(isaac): native camera containment 관측 연결

- 변경: D-692/API v1.210의 ISAAC 출처로 keeper의 같은 영상 경계·횡단보도 관측을 strict typed CORE에 전달하고 trace에 보존한다. 승인된 projection/detection bounds가 없으므로 uncertainty null을 유지하며 GAZEBO 2px 오차를 상속하지 않는다. invalid 관측·학습 제외·명령 0은 유지한다.
- 증거: committed-source 원격 camera/producer/crosswalk/protocol alignment 100 PASS·known_failures NEW 0. 첫 시험의 API description·changelog 정합성 NEW 2를 같은 브랜치에서 수정했다. 독립 D-430 소스 리뷰 차단 결함 없음. R21은 fa75953dfe 파일 7314개 hash 검증 후 22 cores·9GB·빈 GPU에서 시작했다. R20은 문서 정합성 수정 전 준비만 했으며 SDK를 실행하지 않았다.
- gate 변화: SOURCE 관측 연결만 확인했다. unknown error로 lane-return/crosswalk 안전 증거는 생성되지 않는다. 실제 R21 결과·오차 검증·회전/Fleet 연결·재획득·완주·교통·두 대·병렬 RL은 미완료다.

## 2026-10-12 · 484ce96805 · fix(isaac): 지도 prior를 회전 승인으로 사용하지 않기

- 변경: native camera_route_guide의 무조건 pivot_ok=true를 제거했다. 지도 방향은 유지하지만 실제 Fleet turn spot·native sweep clearance 증거가 없는 prior는 false다. invalid camera의 명령 0·학습 제외는 유지한다.
- 증거: 원격 camera/map_task 104 PASS·known_failures NEW 0. R21 맵 정적 기하 비교에서 시작점은 Fleet 허용 지점에서 37.66mm로 18mm 허용 범위 밖이며 남쪽 두 spot의 native 충돌 원 페인트 겹침 29.78/37.30mm는 기존 25mm 한도를 넘었다. static paint/AABB 계산은 센서/회전 승인 증거가 아니며 원본 JSON을 private hash 대조 보관했다. R22 committed source 7331개 파일 검증 준비 후 strict Isaac 자원 floor에 거절되어 SDK는 미실행이다.
- gate 변화: 없음. 실제 Fleet cue·CORE 회전 연결·재획득·native 완주·교통/Fleet·Gazebo 두 대·병렬 RL·실물 수용은 미완료다. geometry 승인·SDK 결과 없는 회전을 성공이나 안전 증거로 보고하지 않는다.

## 2026-10-12 · ccc7905f2 · 공유 지도 NE/SW 진입 정합성

- 변경: lane_rules의 기존 TurnBan으로 NW·SE 재진입을 금지하고 두 lane_graph를 재생성했다. Fleet import·신호 접근로 검사가 금지를 보존하며 camera sim site는 cap1 roundabout과 NE·SW 신호 접근로를 설정한다. Isaac 경로는 reverse 도로로 합법적인 진입을 사용한다.
- 증거: 두 파생 지도의 접근로·cap1·신호 plan과 실제 routing successor, native 금지 경로 거절 회귀를 추가했다. 원격 시험과 독립 안전 리뷰 결과는 후속 기록한다. 실제 Fleet A18 readback은 이전 설정에서 signals=[]·링 분리 블록을 확인한 원인 증거이며 새 설정의 성공 증거가 아니다.
- gate 변화: 아직 없음. 새 경로 baseline/RL·네 실제 신호 표시 연결·CORE/Fleet 회전 연결·완주·교통/장애물·Gazebo 두 대·병렬 RL·실물 수용은 미완료다. 다른 경로의 R17/R21 수치를 개선 비교에 사용하지 않는다.

## 2026-10-12 · a3150e7669 · 공유 지도 진입 규칙 원격 검증

- 변경: NE·SW 진입/NW·SE 진출 규칙을 공유 지도·Fleet·native route에 반영했다. 독립 D-430 소스 리뷰를 통과했다.
- 증거: 관련 6개 원격 파일 135 PASS·exit 0·known_failures NEW 0. 현장 PC 격리 pytest이며 물리 주행은 없다. lint 일지 heading 3개를 수정한 후 0 errors·28 warnings. A19 소스 전송은 Broken pipe·exit 1, 후속 SSH 두 번 timeout으로 서버를 실행하지 않았다.
- gate 변화: SOURCE 회귀만 확인했다. 실제 신호 적재·네 표시·새 경로 baseline/RL·완주·교통 안전·두 대·병렬 학습은 미완료다. 다른 작업의 예약과 부분 전송 소스를 실행 승인으로 해석하지 않는다.

## 2026-10-12 · aea25e6c15 · 최신 main 통합과 실제 Fleet 설정 readback

- 변경: main 16e6fa373을 작업 브랜치에 통합했다. 기존 TurnBan·공유 지도·camera site 신호 설정을 실제 격리 Fleet 서버에서 적재 확인했다.
- 증거: 통합 후 관련 원격 135 PASS·exit 0·NEW 0, lint 0 errors·28 warnings. A20 source archive SHA 양쪽 일치. 실제 인증 readback에서 map_v2_fleet·두 TurnBan·roundabout cap1·sig_ring NE/SW 접근로·errors=[] 확인. runner exit 0, 종료 후 독립 PID 부재·ECONNREFUSED 확인. private 원본 네 파일 hash 대조 보관.
- gate 변화: SOURCE/설정 적재만 확인했다. 신호는 virtual occupancy, online 0/total 2이며 실제 CORE/Gazebo·grant·주행·네 표시·완주·병렬 RL 수용이 아니다. main 착지·push는 아직 하지 않았다.

## 2026-10-12 · a49a754e94 · 새 합법 경로 native 평가와 Gazebo 연결 준비

- 변경: 새 NE/SW 진입 ordered 경로를 기존 segmentation·CORE·frozen RL로 실제 headless 평가했다. 최신 main 통합 소스로 별도 Gazebo build/install과 두 CORE·실제 Fleet 연결 정지 시험을 준비했다.
- 증거: R23 source 7,337 파일 실행 전후 hash 검증, SDK exit 1, 네 heading baseline/eval 완주 0/8·진행 0m. 영상 8개 ffprobe·SHA·시각 증가, 무효 camera 명령 0·최종 정지·GPU 없음·독립 runner PID 부재 확인. private 원본 56개 hash 대조 보관. A21 ROS 17 패키지 빌드 exit 0; 실행 직전 공식 sim selector는 eligible 없음·exit 1이다.
- gate 변화: 완주/RL 개선은 HOLD다. trace의 lane_cue null·junction idle과 camera_target_unavailable을 기록했다. native Fleet 회전·공간/오차 승인·재획득과 두 대 실제 주행이 남았다. 정지 sensor/Fleet 연결 script는 준비·syntax 확인뿐이며 A21 SDK/CORE/Fleet 실행을 주장하지 않는다. 기존 안전 정지를 완화하지 않았다.

## 2026-10-12 · uncommitted · native 카메라 검증 책임 분리

- 변경: run_map_rl.py의 카메라 tick·episode admission·sampling 네 검증 함수를 camera_checks.py로 옮기고 기존 이름을 동일 함수로 재노출한다. native 실행 조립은 600줄, 검증은 31줄이며 새 SDK 의존성이 없다.
- 증거: 착지 통합 회귀에서 628줄 초과 NEW를 확인했다. 이동 전후 함수 AST 일치를 확인했고 기존 기능 회귀와 네 export identity 시험을 유지한다. 독립 검토·원격 수정 후 시험은 진행 중이다. 기록된 정책 digest는 보관된 policy.json과 직접 대조해 기존 exact public provenance에 등록했으며 원본 일지는 보존했다.
- gate 변화: 없음. 안전 정지·무효 관측 학습 제외·샘플 주기·동일 조건 평가 거절을 변경하지 않았다. 실제 SDK 재실행·완주·병렬 RL 수용은 남았다.
