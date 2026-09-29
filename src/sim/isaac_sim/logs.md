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
