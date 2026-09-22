# omx_adapter logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/apps/omx_adapter`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register omx_adapter under D-168
- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가
- 증거: `python -m pytest src/apps/omx_adapter/test -q` 10 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD PARKED
- 결정: D-168
- 교훈: 없음
