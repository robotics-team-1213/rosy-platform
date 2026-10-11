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
