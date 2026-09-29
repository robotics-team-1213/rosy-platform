# isaac_sim logs

## 2026-09-30 · uncommitted · chore(sim): add package marker for the structure scan (D-322, D-168)

- 변경: `package.xml`·`setup.py`·`resource/isaac_sim`·`AGENTS.md`·`progress.md`·`logs.md` 신설 — `src/sim/isaac_sim`이 D-168 구조 스캔에 보이게. Isaac 실제 실행은 별도(D-322 HOLD).
- 증거: `test/architecture/test_module_structure.py` 구조 스캔이 isaac_sim을 패키지로 인식하는지 확인.
- gate 변화: 없음.
- 결정: 마커 전용 — 설치·빌드 불가. honest-hole 노트 제거.
- 교훈: 없음.
