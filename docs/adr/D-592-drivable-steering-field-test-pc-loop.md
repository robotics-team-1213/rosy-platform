## D-592 drivable 모델로 실물 조향 시험을 한다 — 모델 PC 루프가 CORE teleop으로 보낸다

**Status:** Accepted (2026-10-10, 사용자 결정 "싹 다 최신 버전으로 올려서 drivable로 해서 실제로 조향을 테스트해야 해, 더 이상 지체할 시간이 없다").

### Context

D-554 6항, D-576, D-475 §8은 drivable 출력에 조향 권한을 주지 않았고, D-378은 실물 자율 주행을 재생(R0) → 그림자(R1) → 누르는 동안(R2) 순서로만 들이게 했다. 차선 추종의 learned paint는 `lane_marking_mask`(차선 클래스)만 쓴다(`learned/runner.py`). v13-drivable의 차선 출력은 부모 v11과 같으므로, paint 포인터를 바꿔도 조향은 바뀌지 않는다. 사용자는 학습한 drivable로 실제 조향을 지금 시험하기로 했다.

### Decision

1. **시험 경로.** 로봇 코드와 릴리스는 바꾸지 않는다. 모델 PC의 시험 루프가 다음을 반복하고, CORE teleop API(`MANUAL`)로 속도를 보낸다.
   - 8kcn의 전방 카메라 원본 프레임을 받는다.
   - 최신 v13-drivable 후보(`v13.3.01`, `v13-drivable-20261010-86c86e7f`)로 추론한다.
   - D-566 4항·D-576 7항 후처리를 적용하고, 선 안쪽 절반을 포함한 drivable 영역을 만든다(D-554 10항).
   - 화면 아래 40%에서 그 영역의 무게중심 가로 오차로 각속도를 정한다.
   - CORE가 유일한 최종 `/cmd_vel` 발행자로 남는다. CORE의 몸체 정지, teleop 감시(watchdog), 모드 규칙은 그대로다.
2. **안전 한계.**
   - 시작 선속도는 0.03 m/s, 각속도는 ±0.4 rad/s 이하다.
   - 매 주기 공유 `RobotBody` 가드(LiDAR)를 통과한 명령만 보낸다.
   - 다음 중 하나면 0을 보내고 멈춘다: 아래 40% drivable 비율이 기준 미만, 프레임이나 추론이 0.5 s 넘게 늦음, 가드 거절, 시험 시간 상한.
   - 현장에 사람이 있다(D-574). 끝나거나 실패하면 `IDLE`로 돌린다.
3. **먼저 계산만 한다.** 모터를 움직이기 전에 같은 루프를 명령을 보내지 않는 모드로 실물 프레임에 돌린다. 오차 부호, 각속도 방향, 지연을 확인하고 기록한 뒤 움직인다.
4. **기록.** 주기마다 프레임 순번, 추론 지연, drivable 비율, 오차, 보낸 명령, 가드 결과를 남기고, 로봇 녹화(`rosy_rec.sh`)와 천장 녹화를 함께 돌린다. 결과는 `docs/validation/`에 남긴다.
5. **범위.** 이는 D-378의 R2(누르는 동안)에 해당하는 사용자 승인 실물 시험이다. 로봇 런타임에 drivable 조향 소스를 넣는 것(keep 모드 옵션), 운영 기본값 변경, 무인 주행은 이 시험 결과를 보고 따로 정한다.

**Related:** [D-378](D-378-real-drive-errors-and-autonomy-gates.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-566](D-566-v13-1-offroad-false-positive-and-model-pc-job-guard.md), [D-574](D-574-bev-collection-drive-stalls-and-run-rule.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md).
