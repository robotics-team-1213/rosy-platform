## 2026-11-21 · uncommitted · OMX ACT timing and hybrid handoff

- 변경: n_action 8 + async next-chunk, stale/late stop, timing log; --mode act|hybrid|taught; handoff (hold frames, FK z over rim, pose) -> discard ACT -> +z -> folded carry
- 증거: remote pytest; agy review
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음

## 2026-11-21 · uncommitted · OMX hybrid handoff Round 2

- 변경: 시뮬레이션 검증 전까지 파지 8프레임, 림 위 25 mm, XY 12 mm, yaw·수직 하향 자세 7°, 상승 10 mm를 기본값으로 사용한다. ACT 예산 소진 시 인계 없이 `human-hold`로 정지하는 회귀 시험을 추가했다.
- 증거: 가짜 셀과 모델로 CLI envelope 허용·거절, 10 Hz 상태 발행, 기본값, 예산 소진 정지를 확인했다. 원격 pytest는 미커밋 변경을 실행할 수 없다.
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
