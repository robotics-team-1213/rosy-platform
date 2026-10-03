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
