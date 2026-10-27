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

## 2026-10-11 · 97973b01d · fix(isaac): SDK 환경 분리와 headless 실행 복구

- 변경: Pinky headless 렌더를 640×480/AA0으로 제한하고 USD teardown 전에 불필요한 GUI 메뉴를 해제한다. SDK 전용 5.1 dependency repair pins와 현행 5.1/6.x 실행·환경 분리 안내를 추가했다. SDK 실패의 원래 종료 코드는 유지한다.
- 증거: headless config RED 뒤 원격 pytest 71 passed/1 skipped, known_failures 신규 0. 원래 Lab 설치를 보존한 SDK 복사본의 143-package closure에서 pip check exit 0. 실제 Jazzy URDF 생성·모델 검사, headless 600-frame SDK 단독 및 CORE 연동 실행에서 SDK/observer/CORE exit 0. CORE 연동 clock/odom/joints 각 400개·zero cmd_vel 413개, 단일 CORE publisher, viewer GET API 200을 확인했다. [실측 기록](../../../docs/validation/isaac-headless-repair-2026-10-11/result.md).
- gate: ROS-SIM HOLD 유지. 무명령·zero 출력에서도 yaw drift·caster 회전이 남았고 1-frame 진단에서 GUI callback이 재현됐다. map_v2_fleet Isaac 맵·센서·두 대 Fleet·신호 준수 완주·RL은 미확인이다.
- 교훈: 외부 Jazzy PYTHONPATH는 SDK dependency 검사에도 섞이면 안 된다. SDK close 반환·CLI process 종료·로그 무오류·물리 정지는 서로 다른 관측이다. 캐시와 swap 여유를 물리 RAM 32 GB 수용으로 취급하지 않는다.

## 2026-10-11 · 055fd333ce · fix(isaac): headless startup exclusion과 물리 드라이브 복구

- 변경: Wheeled import의 fixed reference links를 병합하고 바퀴만 readback이 확인된 force-type velocity drive로 설정한다. 기존 positive gain/fallback 1과 비구동 caster는 유지한다. headless SDK menu를 초기 startup에서 제외하고 실패했던 runtime unload/cleanup은 제거했다.
- 증거: 각 설정의 RED 뒤 원격 pytest 75 passed/1 skipped, known_failures 신규 0. 실제 공개 runner의 기본 옵션으로 2400-frame headless CORE 시험에서 SDK exit 0 및 SDK Error/Traceback 없음. 전진 평균 0.049952 m/s, 입력 만료 정착 0.35178/0.34113초, 격리된 CORE SIGKILL 후 SDK watchdog 정착 0.57224초. CORE exit 137은 소유 PID에 대한 의도한 장애 주입이며 watcher exit 0이다. [실측 기록](../../../docs/validation/isaac-headless-repair-2026-10-11/result.md).
- gate: I1/ROS-SIM HOLD. angular 0.3 목표에 실제 평균 0.194416 rad/s로 observer exit 1이며 유일한 실패 check는 rotation_tracking. 실제 STL 맵·센서·Nav2·두 대 Fleet·신호 준수 완주·RL은 미확인이다. main 착지·push·CI는 별도다.
- 교훈: 메뉴 확장의 runtime unload는 SDK UI callback을 남길 수 있다. 초기 제외와 후행 SDK dependency의 정상 lifecycle을 분리하고 전체 로그를 검사한다. publisher 죽음은 cached DDS graph 이름 대신 소유 PID와 실제 Twist 수신 중단으로 확인한다.

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

## 2026-10-12 · 7f8182d71 · 공유 맵 바닥 시각 자산

- 변경: 실제 training-curved world의 카펫 18개·기준 사각형 4개·도킹 표식 1개를 native scene에 연결한다. 기존 PNG·pose·크기·색상 modulation을 유지하며 맵 밖·누락 텍스처와 비정상 pose를 거절한다. 벽·페인트·주의 표식 조립은 같은 코드로 이동했고 runner는 584줄이다.
- 증거: source f6057b410의 맵·카메라·구조 원격 152 PASS·NEW 0. 독립 검토에서 텍스처 tint 누락과 다른 missing asset에 의해 우연히 통과할 수 있는 escape 회귀를 지적해 수정했다. committed source 7f8182d71의 보강 원격 5 PASS·NEW 0·독립 SOURCE APPROVE WITH NOTES다.
- gate 변화: 없음. SDK shader 렌더·UV 방향·실제 영상 밝기·카메라 인식 개선·주행 정지·전체 완주·병렬 RL과 교통/Fleet 수용은 아직 미확인이다. 기존 ground 배경·road_lines model Z offset까지 전체 시각 일치는 추가 확인한다.

## 2026-10-12 · 71c2fa595 · 공유 ground와 paint pose

- 변경: 같은 training-curved world의 ground RGB·크기와 white paint model pose를 native에 적용한다. 원래 wall·caution·CORE·무효 관측 안전 정지와 학습 제외를 유지한다. 현재 알려진 수평 SDF 범위로 제한한다.
- 증거: source 560515c14 관련 원격 115 PASS·NEW 0, source 71c2fa595의 경로·ground·paint 비정상 입력 거절 보강 원격 8 PASS·NEW 0, 독립 SOURCE APPROVE WITH NOTES. 최신 main을 포함하는 source 66840266e의 7443 파일 hash 검증과 실제 SDK USD 24.5 메타데이터에서 RGB 0.13/0.14/0.13·size 100·paint Z 0.001·23 시각 plane·4 collision wall 및 shader 연결을 확인했다. 이는 116712KiB RSS의 비렌더 검사다.
- gate 변화: 없음. R26 전체 실행은 자원 gate의 7.9GB 예산으로 기준 8GB에 못 미쳐 SDK 시작 전에 거절됐다. 새 ground의 PhysX·영상·인식 개선·완주·교통/Fleet·병렬 RL은 미확인이다. 시스템 cache 조정에는 관리자 sudo 입력이 필요하며 보호 기준을 낮추거나 다른 프로세스를 종료하지 않았다.

## 2026-10-12 · d778f8b7c · 공유 바닥 native 재평가와 reset 진단

- 변경: 승인된 횡단 막대 구분과 공유 바닥을 통합했다. reset 확인 실패에는 phase·seed·요청 좌표·실제 pose·위치 오차를 남긴다. 기존 위치/속도 기준, 정지·초기화 거절·무효 카메라 정지·CORE 명령 권한은 그대로다.
- 증거: source 4f617d7c2 통합 원격 325 PASS·1 SKIP·NEW 0. 당시 main의 문서 변경을 포함한 source 40b389415 R29는 7457 source hash를 실행 전후 검증했다. 실제 renderer·주행·5개 960×540 녹화를 수행했고 ffprobe frame 수·renderer/physics receipt·42개 산출물 hash를 독립 대조했다. 무효 관측 후보는 모두 0, 각 episode 종료와 cleanup은 기존 실제 속도 정지 기준 미만이다. source d778f8b7c의 진단 보강은 원격 90 PASS·NEW 0·독립 SOURCE 승인이다.
- 결과: 첫 방향 baseline/frozen eval은 모두 0.110668m 진행 후 camera_lane_lost. 90도 baseline은 off_route, eval은 camera_lane_lost. 180도 baseline의 유효 카메라는 0회이며 다음 reset 확인에서 SDK exit 1로 중단됐다. 270도는 시작하지 못했다. 기존 정책 evaluation-only이며 새 updates나 개선을 증명하지 않는다.
- gate 변화: 실제 공유 바닥 렌더와 제한 주행 진단만 확인했다. 네 방향 전체 시험·완주·교통/Fleet·병렬 RL·ROS-SIM·실물 수용은 미완료다. reset 실패의 어느 기준이 초과됐는지 기존 기록으로 구분할 수 없어 값을 보강하며, 추정으로 기준을 바꾸지 않는다. 원본 영상과 실패/정지 검증은 private 일지에 보관했다.

## 2026-10-12 · b9dc219e4 · R31 정지 실패와 곡선 진단 교훈

- 증거: 사용자의 관리자 적용 이후 ARC 상한 2147483648 bytes와 MemAvailable 9753800kB를 읽었다. 최신 main 포함 source 54cba0b3f, 7465 source hash 검증으로 R31 native SDK를 실행했다. baseline 707은 0.110668m 진행 후 관측 무효화, eval 뒤 실제 정지·cleanup 정지 검사 실패로 exit 1이다. 27개 산출물과 2개 영상을 private에 보존·hash/frame receipt 대조했다. 새 학습 또는 완주 증거가 아니다.
- 교훈: 실패 전방 PNG에 흰 선이 보이지만 target_now_m=null·ahead_m=0이었다. camera_target_unavailable을 차선이 영상에서 사라졌다는 뜻으로 설명하지 않는다. RGB·mask·투영·목표점·CORE 허용을 분리해서 진단한다. 저장소 workflow 교훈과 private 일지에 사용자 맵 사진 및 trace 시점을 기록했다. segmentation 원본 mask와 맵 렌더 일치 여부는 미확인이다.
- 변경: velocity solver 반복 1의 rest trace spike에 대해 8로 높이는 수치 정확도 비교 실험을 준비했다. 위치 반복 수 보존과 실제 SDK readback 일치를 강제하고 summary에 남긴다. source b9dc219e4 원격 119 PASS·NEW 0·독립 SOURCE APPROVE. 적용 효과는 SDK 재시험 전 미확인이다. 바퀴 gain·캐스터·정지 .005/.02 및 연속 .3s·2s 제한·CORE/Fleet 권한은 유지한다.
- gate 변화: 없음. 네 방향 완주·새 RL·두 대 Fleet·교통 규칙·ROS-SIM·실물 수용은 HOLD다.

## 2026-10-12 · 1158008ac1 · held-path 작업 통합과 곡선 거절 진단

- 변경: 사용자 지정 wt-held-path-b73c92의 clean HEAD0bda628988(D-708)을 우리 Isaac worktree에 병합했다. 두 충돌에서 native scan·return pose·stale 검사·wall 전달·CORE containment와 정확한 현재 pose 소비를 함께 보존했다. held camera_tick은 기존 camera_checks helper로 통합하고 runner alias를 유지했다. held 출처는 RL state None·gain1이며 최신 거절을 덮어쓰지 않는다. 상대 worktree 파일은 수정하지 않았다.
- 증거: source8934364652 목표 거절 원인 보존은 RED3FAIL/67PASS 후 원격90PASS/NEW0·독립 SOURCE APPROVE. 통합1158008ac1은 원격322PASS/1SKIP/NEW0·독립 SOURCE INTEGRATION APPROVE. 병합으로 들어온 D692 gap을 실제 ADR 존재 확인 후 e84631d1a에서 제거했다. 이후 main439e80c47 병합은 Discord 문서2개만 변경했다.
- 진단: R31 실패 RGB의 동일 frozen model 오프라인 재추론에서 lane7210/drivable18253/way16937픽셀과 target[.19,.137]·ahead0·exitleft를 얻었다. 과거 실시간 mask 증거로 부르지 않는다. 이 프레임의 단독 DrivableSteer 재현은 pivot 허용 true/false 모두 exit_behind_line=true·drivable_closed·출력없음이다. 원래 주행 전체의 odom·LiDAR·이력을 재현한 결과는 아니다. fresh closed 사례는 D708 gap 유지 기능만으로 해결되지 않는다.
- SDK: R32는 실제 solver position32/velocity8을 읽었지만 4개 최종 episode·중단된 baseline909 영상 이후 정지/cleanup 정지 실패로 exit1, 완주0이다. 실제5개 영상/43개 산출물을 private에 독립 검증 보존했다. R33 source0b4ddd5af9(7469 source hash 검증)는 자원 대기 중이며 SDK 시작 증거는 아직 없다.
- 조율: 대상 별도 세션은 연결 agent 목록에 없어 직접 메시지 전송이 실패했다. 사용자에게 알리고 private drive-session-handoff에 대상·증거·통합·거절 경로를 기록했다. 문서 존재와 별도 작업자의 수신을 구분한다.
- gate 변화: 없음. 실제 곡선 완주·새 강화학습·두 대 교통/Fleet·ROS-SIM·실물 수용은 미완료다.

## 2026-10-12 · af519cab1e · Isaac 질량 기준 프레임 보존과 R34 반례

- 변경: 요청한 merge_fixed_joints=true를 SDK에서 읽어도 enabled mass0 footprint actor와 .8kg base_link actor가 별도로 남는 것을 확인했다. Isaac 준비 단계에서 차체의 기존 질량/관성/visual/collision을 footprint 기준으로 옮기고 직계 child joint 원점을 같은 translation만큼 바꾼다. base_link 이름/virtual frame은 유지하며 원본 xacro/Gazebo/실물 모델은 바꾸지 않는다.
- 증거: RED4FAIL/4PASS/1SKIP 뒤 전체 Isaac229PASS/1SKIP/NEW0·독립 SOURCE APPROVE. 실제 R33/R34 prepared URDF는 0각도/비영 wheel·caster 각도 두 상태에서18개 world frame 차이0, 총질량1.54kg 및 각 질량의 world COM/inertia가 같았다. SDK R34에서 footprint mass.8와 기존 관성, 빈 base_link actor 제거를 읽었다. 같은 source7469 hash를 실행 전후 검증했다.
- 결과: R34는 첫 baseline 종료 정지 검사와 cleanup 정지 검사에서 exit1이다. 최종 episode0, 중단 영상1/21개 산출물을 private에서 hash/frame receipt 대조했다. 이 구조 수정이 실제 정지 실패 해결이라는 가설은 입증되지 않았다. I1 import 설정/모델 metadata는 얻었지만 종료 timeout124였으며 전체 SDK 성공으로 부르지 않는다.
- 추가 회귀: held-path 후속831d9bdc6 통합 source9f676b1928의 전체 Perception/Isaac·관련 CORE authority/crosswalk/junction/lane_return3508PASS/113SKIP/NEW0. 이후 최신 main의 incident/calibration 변경을 병합하고 실제 존재하는 D705의 gap을 정리했다.
- gate 변화: 없음. 기존 traffic 파이프라인은 main19054491e2에 landing17,926PASS/823SKIP/NEW0으로 착지했지만 당시 push는 사전 검사 중이었다. 이번 질량 준비 변경은 작업 브랜치 검증이며 새 RL/네 방향 완주/두 대 Fleet·한국 교통/ROS-SIM/실물 수용은 미완료다. 정지·권한·카메라 gate를 완화하지 않았다.

## 2026-10-12 · afb9205c2 · D-708 관측 형상 기반 공백 추종

- 변경: 방위각/직선 가설 대신 연속 중심 polyline과 실제 접선을 기억하고 current odom으로 목표를 계산한다. 마지막 독립 관측 age·누적거리·관측 구간 상한, 최신 거절/무효 기하/odom 소실의 즉시 폐기를 적용한다. Isaac held 출처는 RL state와 gain에서 제외하며 CORE 명령·권한·장애물 gate를 유지한다.
- 증거: 원격 RED로 기하와 최신 거절 경계를 재현했다. 유효 자원 모델 PC의 afb9205c2 회귀는 498 passed/1 skipped/NEW 0, 독립 SOURCE APPROVE다. 전체 affected 초기 네 NEW는 fixture와 거버넌스 검사를 수정한 뒤 재검증한다. 노트북의 오실행은 중단·폐기했고 floor 미달 fallback은 수용에 쓰지 않았다.
- gate 변화: SOURCE/LOCAL 구현 근거만 추가. 실제 Isaac 재실행·R29 최초 목표 소실 해결·ROS/Fleet 완주·장치/현장 수용은 미확인이다. 계획은 docs/plans/2026-10-12-observed-path-gap-implementation.md, 계약은 D-708을 참조한다.

## 2026-10-12 · 831d9bdc6 · D-708 최종 원격 선택 시험

- 변경: D-708 구현의 최종 원격 선택 시험과 번호/문서 검사의 수정을 기록했다. 구현 코드는 바꾸지 않았다.
- 증거: 자원 기준을 충족한 원격 PC의 affected 두 invocation은 6,086 passed/359 skipped/terminal exit 0이며 known_failures는 각각 NEW 0이다. lint 0 errors/28 warnings와 ADR Log BOM/CRLF를 확인했다. 구현의 독립 SOURCE APPROVE 및 held에서 정책 gain 1.7과 1의 출력 일치를 검증했다.
- gate 변화: SOURCE/LOCAL 후속 구현 검증. 실제 Isaac 재실행·R29 최초 소실 해결·이번 main 착지·push·CI·실물 수용은 아니다.

## 2026-10-12 · 0fa0161d4 · 관측 곡선 거절과 실행 배선 분리 진단

- 변경: camera_target 거절 진단에 reason·경계 교차·중심 경로·벽 여유를 보존한다. 계획은 docs/plans/2026-10-12-map-drive-diagnosis.md이며 CORE 안전·학습 admission과 무효 명령 0은 유지한다.
- 증거: 원격 RED 3 FAIL 뒤 전체 Isaac 214 PASS/1 SKIP/NEW 0, 독립 SOURCE APPROVE. AI PC의 기준 main 소스 Gazebo 정지 관측에서 현재 목표/경로와 guide publisher 0을 확인했고 전체 runner의 Fleet import 실패 exit 1 및 정리 readback을 별도 기록했다. 짧은 목표 fallback은 몸체 여유 증거가 부족해 채택하지 않았다.
- gate 변화: SOURCE 진단 및 원격 회귀 근거다. Gazebo 부분 관측은 Fleet 연결·자율 주행·완주 수용이 아니다. 실제 Isaac SDK 재실행·네 방향 완주·실물 수용은 미확인이다.

## 2026-10-12 · bf7054de3 · 공유 바닥 크기와 기본 정지 분리

- 변경: 기존 맵 생성기의 ground를 100m에서 5m로 바꾸고 Gazebo world 3종을 재생성했다. Isaac은 같은 값을 읽으며 CAD·차선·벽·주의 표시와 정지 기준은 유지한다. 최신 main의 카메라 진단·관측 경로 변경도 통합했다.
- 증거: 동일 출발 위치·방향에서 100m ground만 있는 조건과 전체 맵 조건은 5개 정지 구간 중 2개가 실패했고 2400개 샘플이 동일했다. 전체 맵을 유지하고 ground만 5m로 바꾼 조건은 5개 모두 통과, 기준 초과 샘플 0이었다. bf7054de3의 실제 SDK에서는 CORE cmd_vel_cycle 0 명령 2400회·경고 0·5개 정지 구간 통과·terminal exit0을 확인했고 실행 전후 7501개 source hash를 대조했다. 원본과 독립 검증은 private 일지에 보관했다.
- 회귀: bf7054de3 원격 338 PASS/1 SKIP/NEW0·독립 SOURCE 승인. 벽 누락 검사의 무조건 통과를 막은 6cad8938f 후속은 원격 24 PASS/NEW0, lint 0 errors/28 warnings다.
- gate 변화: 기본 in-process CORE/PhysX 정지 증거다. 주행 후 정지·카메라 곡선 추종·새 강화학습·네 방향 완주·Gazebo 두 대 Fleet·한국 교통 규칙·ROS-SIM·실물 수용은 미완료다. 이 비교만으로 PhysX 내부 원인을 확정하지 않는다.

- 후속 기본 운동: 같은 bf7054de3 실제 SDK에서 CORE 명령 3120회·경고 0·terminal exit0. 직진 0.03m/s 1초는 0.030106m, 좌/우 0.3rad/s 1초는 +0.242819/-0.245348rad였다. 각 동작 후 마지막 연속 정지는 1.991667s 이상이며 cleanup도 통과했다. 원본 샘플의 변위·회전 부호·연속 정지와 파일 hash를 독립 재계산했다. 이는 짧은 운동 및 주행 후 정지의 제한된 증거다. 요청 회전량 대비 약 18~19% 편차가 남아 정밀 추종·완주·새 RL 수용은 아니다.

## 2026-10-12 · b98eb3fd1 · SDK 중복 바닥 충돌 제거

- 원인: 실제 SDK stage에서 ground의 표시 Mesh와 Plane 양쪽 충돌이 활성화돼 있었다. SDK GroundPlane wrapper는 표시 Mesh에 collision과 physics material을 붙인다. 초기 출발점 통과와 바닥 크기 조정만으로 다른 자세의 정지 안정성을 보장하지 못했다.
- 변경: native map runner는 표시 Mesh 충돌을 끄고 기존 바닥 재질을 Plane에 연결한다. 예상 SDK 구조·재질과 변경 readback이 맞지 않으면 실행을 거절한다. CORE 명령·정지 기준·물리 timestep·wheel gain은 유지한다.
- 증거: 실패 자세의 기존 진단은 초기/cleanup 정지가 실패했다. 중복 충돌 제거 및 재질 연결 비교는 실제 SDK exit0, 3120개 샘플, 직진 0.030046m, 좌/우 +0.245280/-0.248329rad, 모든 정지와 cleanup의 마지막 연속 안정 구간 1.991667초 이상이었다. 원본 hash·운동·정지를 독립 재계산했다.
- gate 변화: 이는 진단 비교이며 제품 반영 후 재시험·전체 학습·완주·교통/Fleet 수용을 대신하지 않는다. 회전 추종 편차도 남는다.

- 제품 재시험: b98eb3fd1 원격 Isaac 236 PASS/1 SKIP/NEW0. 실제 SDK의 제품 helper·reset 뒤 읽기 전용 검증을 사용한 같은 자세 기본 운동은 exit0, 3120개 샘플과 모든 단계/cleanup 통과였다. 샘플은 진단 비교와 byte hash가 동일했다. 고정 정책 카메라 평가는 별도 진행하며 새 학습 증거로 세지 않는다.

- 카메라 후속: 같은 커밋의 네 시작 방향 고정 정책 평가 8개 episode와 실제 영상 8개가 끝났다. 초기/각 episode/최종/cleanup 정지 11개는 모두 통과했지만 완주는 0이며 camera admission 실패로 SDK exit1이다. 정상 방향 baseline 0.110668m, eval 0.100579m 후 차선 관측 거절이며 정지 안정성 개선을 차선 추종 해결로 표현하지 않는다.

## 2026-10-12 · 45e92d326 · 카메라 관리자 설정과 곡률 역산 일치

- 변경: CameraLane이 기준 관리자 설정으로 DrivableSteer를 구성한다. 설정된 곡률과 명시적인 RL gain 조절을 구분한다.
- 증거: 원격 camera 회귀 82 PASS, known_failures NEW 0이다. 기존 .04/.4 구성은 이전 gain/cruise 비율을 유지한다.
- gate 변화: 호스트 회귀만 확인했다. 새 native Isaac SDK 실행·곡선 완주·실물 수용은 미확인이다.

## 2026-10-12 · d67b191d4 · 현재 카메라 저속 목표의 출처 구분

- 원인: shared drivable_creep는 현재 관측·기억 목표를 함께 사용하지만 native Isaac은 관측 출처를 구분할 수 없어 모두 거절했다. 현재 영상의 목표와 누적 경계 검사를 단일 프레임 재추론만으로 대체하면 안 된다.
- 변경: 실제 선택한 현재 목표와 관측 key를 별도 metadata로 제공한다. 유효 odom·유한 전방 목표·누적 경계 arc 검사를 통과할 때만 제공하며 native는 현재 stamp와 일치하고 전략 전환·기억 출구가 아닐 때만 받는다. shared 조향·예산·realign·ExpectedPath와 CORE 최종 명령 권한은 유지한다.
- 증거: 원격 RED 2개로 출처 누락과 승인 실패를 재현한 뒤 관련 123개 통과/NEW 0. 실제 mask→shared steer→native 경로 및 전략 전환 거절을 포함한 Isaac·drivable·ExpectedPath 확장 회귀도 exit0/NEW0이다. 제품 소스 독립 검토는 현재 관측 출처와 native 승인 범위에 한정한다.
- gate 변화: SOURCE 및 원격 회귀 증거. 실제 곡선 주행은 별도 재시험 중이며 완주·교통 규칙·Fleet·ROS-SIM·실물 수용을 승인하지 않는다. nominal arc 검사는 RL gain 적용 후 모든 경계 비횡단을 보장하지 않는다.

- 실제 R39 재시험: 고정 정책으로 네 시작 방향 8회 실행, 완주 0회·정지 11회 통과·SDK exit1. 정상 방향 baseline/eval은 모두 약 0.110668m에서 camera_lane_lost였다. observed_creep 승인 경로는 이 정상 방향 실행에서 사용되지 않았다. 따라서 출처 연결 수정만으로 현재 곡선 실패가 해결됐다고 주장하지 않는다. 연속 way/누적 경계/실제 선택 목표를 추가 기록해 원인을 분리한다.

## 2026-10-12 · 0a690a83b · 카메라 종료 벌점과 실행 행동 연결

- 원인: camera_lane_lost 종료의 현재 state=None을 이유로 실패 보상도 누락했다. 새 원격 회귀로 재현하고 known_failures NEW 1로 기록했다.
- 변경: 실제 CORE nonzero 전달 receipt로 확인한 episode 내 마지막 유효 행동에만 target 상실의 terminal reward를 연결한다. ZERO 구간은 기록을 유지하고 held 등 비학습 이동은 연결을 끊는다. stale·추론·scan 오류는 제외하며 invalid state bootstrap과 기억 명령 재실행은 허용하지 않는다.
- 검증: 유효/미실행/다른 종료/외인성 오류/held 연결 차단 회귀 통과. Isaac 전체와 architecture 원격 통합은 exit0/NEW0. 기존 helper를 camera_checks에 옮겨 재노출하며 600줄 기준을 유지했다.
- gate 변화: SOURCE/원격 회귀 증거이며 native 종료 credit·완주·독립 병렬 학습·두 대 Fleet 교통 수용은 별도다.

- 실제 R41: d653def0b headless 한 대 학습6회와 고정 평가3회·baseline4회가 종료됐다. Q 갱신27,957회 중 목표 상실 terminal credit5회를 실제 확인했고, trace로 독립 재계산한 최종 Q는 저장 정책과 정확히 일치했다. 각 credit의 원래 nonzero CORE receipt·유효 state·후속 ZERO·종료 bootstrap0을 검사했다. 기록된 정지16개와 실제 영상7개를 검증했지만 전체 완주는0회이며 SDK exit1로 정책 채택은 거절했다. 병렬 학습·교통/Fleet 수용은 여전히 미완료다.

## 2026-10-12 · ba1347294 · 카메라 관측 구간 학습

- 근거: R41 원시 trace에서 동일 source_stamp 내 행동 변경11,055회와 ordinary Q update26,797회를 확인했다. 물리240Hz에 gamma0.95를 적용한 시간 의미를 수정 대상으로 삼았다.
- 변경: 새 유효 stamp에서 gain 선택, 구간 보상 합산, 성공 dispatch receipt를 가진 구간만 갱신. 매 tick CORE·camera 안전 실행은 유지한다. 종료 credit은1회이며 외인성 실패·미실행 구간은 제외한다. schema2는 이전 physics-tick 정책 복원을 거절한다.
- 검증: 첫 원격 시험은 helper 미구현 assertion으로4 setup ERROR/NEW4였다. 구현·연결 후 관련129 PASS, legacy schema 거절 추가 후 Isaac 전체와 module_structure322 PASS/1 SKIP/NEW0. runner597행. 이 시험은 SDK 실행을 포함하지 않는다.
- 후속 검증: CORE select 실패가 warning ZERO를 보낼 때 이전 실행 연결이 남는 문제를 원격 NEW1로 재현해 수정했다. 관련133 PASS, 최신 main 반영 후 Isaac 전체와 module_structure325 PASS/1 SKIP/NEW0. 독립 소스 검토는 f2697eab11ea1f095cba02a97553fb7e611851f7의 카메라 관측 주기 변경을 승인했다.
- 실제 R42: 같은 SHA로 headless 학습6회·baseline4회·eval3회가 종료됐다. 구간 raw reward 합계와 Q 갱신1,165회(종료6회)를 독립 재계산해 저장 정책과 정확히 일치했다. 동일 관측 행동 유지44,551회, 산출물91개 hash, 영상7개 프레임 수를 검증했다. 정지 receipt16개를 확인했으나 성공 정지 구간 전체 raw sample은 저장되지 않아 연속 정지 독립 검증과 구분한다.
- gate 변화: 전체13회 모두 camera_lane_lost로 완주0, SDK exit1, 후보 미채택이다. 진행량 증가는 완주나 안정적인 곡선 추종 증거가 아니다. 병렬 환경·신호·횡단보도·Fleet·ROS-SIM·실물 수용은 미완료다. 원본과 독립 verifier는 private/isaac/media/2026-10-12-r42-camera-cadence에 보관했다.

## 2026-10-21 · uncommitted · 공통 실험 catalog·run 기록

- 변경: OMX-F import의 제한된 조건과 항만 미준비 시나리오, 불변 설정·지문·요청 중복 방지·revision 상태·최종 결과·검증된 산출물 저장을 추가했다. SDK나 HTTP에 의존하지 않는 기록 단위이며 D-834 Proposed로 실행/증거 경계를 연결했다.
- 증거: 원격 b566945754에서 새 catalog/store 부재로 28개 실패를 먼저 확인했다. GREEN·문서 계약은 최종 커밋으로 별도 확인한다. 모델 PC read-only 점검에서 기존 GPU·SDK 설치와 동일 계정 model-code root를 확인했다.
- gate 변화: 없음. GPU 실행·웹 연결·실제 import는 후속이며 새 SDK 실행은 NOT RUN이다.

## 2026-10-21 · uncommitted · 제한된 공통 Isaac 실행기

- 변경: 기존 model-code work.lock·학습 gpu.lock과 협력하는 동일 계정 admission, 불변 launch intent·중복 요청 재조회·unit 소유권 대조·중지 요청, 고정 SDK worker와 선택적 import 보고서를 구현했다. 원격 CLI·웹 adapter는 후속 분리 단위다.
- 증거: admission 부재7실패, controller/report 부재2실패·6오류, worker 부재3실패를 원격 RED로 확인했다. 구현 후 admission7 PASS, controller/report/기존 entrypoint31 PASS, Isaac 전체349 PASS/1 SKIP. 실제 subprocess timeout·stop·출력 제한과 보고서/GPU 잔존 판정 시험을 포함한다.
- gate 변화: 없음. SDK application·물리 집기·학습/승격은 미실행이며 원격 host 검증과 구분한다. D-834는 Proposed를 유지한다.

## 2026-10-21 · uncommitted · 공통 SIM 실제 SDK·교차 조회

- 변경: 웹 workspace가 전체 binding 지문을 controller·worker까지 고정한다. 실제 host에서 발견한 UNKNOWN 진단 오인·user bus 누락과 준비 거절 응답을 수정했다.
- 증거: 소스9dbaca197b의 실제 OMX-F 보고서120프레임·관절·articulation을 독립 검증했다. run은 cleanup/GPU 해제 미확정으로 UNKNOWN이며 외부 llama-server를 종료하지 않았다. 소스c47e8454e3의 웹 start를 CLI가 같은 최종 FAILED/admission_refused/SDK_NOT_STARTED로 조회·재전송·fetch했다. 관련 원격479 PASS/1 SKIP. 상세는 docs/validation/isaac-shared-runs-2026-10-21/result.md.
- gate 변화: 실제 SDK 부분 증거를 추가했으나 최종 무점유 import·실제 stop·물리 집기·학습 수용은 보류다. UNKNOWN을 성공으로 변경하지 않는다.

## 2026-10-21 · uncommitted · 공통 SIM 무점유 성공·실제 중지

- 변경: 무점유 상태의 모델 검사와 웹 실행·CLI 중지의 후속 증거를 추가했다.
- 증거: 외부 GPU 점유가 자연 해제된 뒤 소스8aa57b3d0e의 새 run981e96c0bd105e38bf8b1923159ad614가 모델 검사120프레임·exit0·GPU 해제와 최종 SUCCEEDED로 끝났다. 웹에서 만든 별도 run83ef940c7e0d553cade26575bc72dffd는 CLI 중지 요청 뒤 STOPPED·exit-15·GPU 해제·최종 fetch를 확인했다.
- 보존: 이전 UNKNOWN·FAILED와 모든 입력·결과를 유지했다. 외부 프로세스를 종료하지 않았다. frozen 후속 기록은 docs/validation/isaac-shared-runs-2026-10-21b/result.md다.
- gate 변화: 제한된 import/실행 중지 수용만 추가한다. ROS-SIM·물리 집기·적층·협응·학습/실물 수용의 gate는 이동하지 않는다.

## 2026-10-25 · 7d0cfcd6e9 · 정지 적재면·컨베이어 접촉 왕복

- 변경: 고정 합성 fixture와 CAD IK·접촉 관측·독립 판정을 공통 catalog/runner/CLI에 연결했다. 기존 import와 실행 잠금·상한·종료 검증을 유지한다.
- 증거: run36041b241ee25366986bb3a6262ba0be의3,624 physics step·양방향 접촉 lift/이송·해제 후 안정·FINAL6파일·GPU 해제. 독립 검토와 원격377 PASS/1 SKIP, NEW0. 앞선4개 SDK 실패를 보존했다.
- gate 변화: Pinky 정지 tray proxy·컨베이어 proxy의 단일 SIM 스모크 수용이다. full Pinky·실측 카메라 정합·주행·learned AI·실물 수용이 아니다. 상세는 docs/validation/isaac-pinky-conveyor-roundtrip-2026-10-25/result.md. CE 구동 방식 교훈 새 기록.

## 2026-10-25 · uncommitted · OMX import 보고서의 공개 소스 포트

- 변경: 기존 개발 기준 a46daee90b7의 import_report·선택적 import_omx 보고서·회귀를 공개 accepted source에 그대로 옮겼다. 기존 벤더 자산과 importer를 유지한다. 보고서는 정상 SDK 정리 뒤 배타적으로 생성하며 모델·관절·자산·프레임 증거를 별도 검증한다.
- 증거: 원래 소스와 세 파일의 canonical Git blob 일치를 확인하고 이 포트의 커밋된 SHA에 대한 원격 검사·독립 검토·CI를 별도로 결속한다. 과거 SDK 성공을 새 포트의 실행 성공으로 바꾸지 않는다.
- gate 변화: 없음. 새 SDK 실행·접촉 과제·학습 정책 평가·실물 제어는 수행하지 않았다.

## 2026-10-25 · uncommitted · 고정 Isaac 실행 관리자의 공개 소스 포트

- 변경: 개발 기준 a46daee90b7의 run admission·binding·catalog·control·store·system·worker와 다섯 회귀 파일을 공개 소스에 연결했다. contact producer·verifier가 아직 없으므로 접촉 시나리오만 일시 비활성화하고 거절 회귀를 추가했다. 나머지 원래 검증·잠금·소유권·불변 증거·복구 동작을 유지한다.
- 검증: 커밋 SHA에 결속한 원격 Isaac 패키지와 선택된 guard, 독립 base/head 검토 및 CI를 확인한다. 기존 SDK 실행은 이 새 공개 SHA의 실행으로 재명명하지 않는다.
- gate 변화: 없음. 이 단계의 실행 가능 시나리오는 모델 import뿐이며 SDK 신규 실행·학습·실물 명령을 수행하지 않았다.

## 2026-10-25 · uncommitted · 접촉 왕복 producer·판정기의 공개 소스 포트

- 변경: a46daee90b7의 conveyor fixture·report·task·회귀를 그대로 보존하고 catalog를 원본과 같이 활성화했다. 단계 PNG와 보고서는 기존 실행 원장의 크기·해시 검증을 거쳐 Learning 소비 경로에 연결된다.
- 증거: 원래 source7d0cfcd6e94f/run36041b241ee25366986bb3a6262ba0be의 frozen 검증·실패·drive-mode 교훈을 보존한다. 이번 공개 SHA의 원격 호스트 회귀·독립 검토·CI는 새 SDK 실행과 구분한다.
- gate 변화: 기존 단일 합성 접촉 스모크의 소스가 공개된다. 새 SDK 실행·동기화 Episode 수집·학습 정책 평가·실물 명령은 수행하지 않았다. CE는 기존 교훈을 재사용하며 새 해결 기록을 늘리지 않는다.

## 2026-10-27 · uncommitted · SDK 6.2 운영 연결과 ROS 제어 검증

- 변경: 정확한 SDK 6.2 binding 허용, Kit EULA 환경, 선택 SDK ROS library 해석, live PhysX variant와 현대 Manipulator position gain을 연결했다. SDK 예외 종류도 보존한다. 기존 SDK 설치·불변 binding·Wheeled 설정은 유지한다.
- 증거: 소스 6df916084147ce51bb10b34e8339e302a88fdfe6의 원격 Isaac 전체 시험 exit 0·신규 실패 0. 모델 PC ROS conformance는 관절 이동·취소 정지·양쪽 카메라·토픽·GPU 정리를 통과했다. 두 PC의 PhysX/PPO 설치 검증과 모델 PC의 기본 SDK pointer 6.2 전환은 [검증 기록](../../../docs/validation/isaac62-sdk-migration-2026-10-27/result.md)을 따른다.
- gate 변화: 이번 특정 SDK/소프트웨어 실행 증거를 추가한다. 학습 정책 일반화·실물·현장 수용으로 확대하지 않는다. AI 추가 ROS 시험은 외부 GPU owner로 SDK 시작 전에 거절됐고 승인 서비스는 복원했다.
- 교훈: [import 성공 뒤 position drive 누락](../../../docs/solutions/runtime-errors/isaac62-imported-articulation-with-zero-position-drive-2026-10-27.md)을 기록했다. 초기 UNKNOWN/조기 실패의 정확한 원인은 미확정으로 유지한다.

## 2026-10-27 · uncommitted · AI 추가 ROS 거절 근거 보충

- 보충: 앞 항목의 외부 GPU owner는 helper의 오류 문구다. 당시 점유와 조회 오류를 구분한 원본 응답을 저장하지 않았으므로 GPU 무점유 확인 조건 미충족까지만 확인된 사실로 유지한다. SDK 미시작·승인 서비스 복원은 확인했다.
- gate 변화: 없음. AI ROS 통과를 주장하지 않는다.
