# pinky_pro logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-24 · uncommitted · feat(robots): pinky_pro robot package carries the profile CORE loads (D-196)

- 변경: `src/core/core/config/profile.pinky_pro.yaml`와 `capabilities.yaml`을 이 패키지의 `config/profile.yaml`·`config/capabilities.yaml`로 옮겼다. CORE는 `robot.model`(기본 `pinky_pro`, `ROSY_ROBOT`)의 share에서 읽고, 소스 트리에서는 `src/robots/pinky_pro/config`로 폴백한다. 이미지 필수 패키지 목록에 올렸다
- 증거: `python -m pytest src/robots/pinky_pro/test -q` 2 passed; core 시험 전체가 이 파일을 읽고 통과 (2026-09-24 Windows host)
- gate 변화: 신규 기록. SOURCE GO, LOCAL GO, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED
- 결정: D-196 Proposed
- 교훈: 없음
