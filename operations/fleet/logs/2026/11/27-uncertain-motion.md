## 2026-11-27 · uncommitted · 불확실 이동 표시(_uncertain_motion)를 표시 뒤 정지 증거로만 해제

- 변경: goal_lease._uncertain_motion에 표시 시점(단조 시계·wire version·motion epoch)을 저장하고 표시 이후 시작한 measured standstill·확인된 E-stop·exact custody 정지 증명으로만 해제. cancel 응답 해제 경로 없음, 시간 경과 해제 없음, 전역 admit_wire 유지
- 증거: docs/validation/fleet-uncertain-motion-2026-11-27/result.md; 원격 시험(모델 PC·AI PC)
- gate 변화: SOURCE=GO
- 결정: 없음
- 교훈: 없음
