# perception_runtime logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
이 패키지로 옮기기 전 이력은 `git log --follow`와 `middleware/perception/logs.md`를 본다.

## 2026-11-03 · uncommitted · refactor(perception): split perception_runtime out of control
- 변경: `control.recording`, `control.keep_odom_veto`, `control.sensing.perception`의 차선 판정 16개 모듈, `learned`의 모델 계약·실행 10개 모듈(모두 28개, 6,491줄)을 이 패키지로 옮겼다. 본문은 그대로 두고 import 경로만 바꿨다. 이 모듈들만 시험하던 14개 시험도 함께 옮겼다.
- 증거: 이전·이후 import 닫힘을 AST로 계산해 `rclpy`·middleware 의존이 없음을 확인했다. 원격 시험 결과는 착지 기록에 남긴다.
- gate 변화: 신규. SOURCE·LOCAL GO, 나머지 N/A(라이브러리 등급).
- 결정: learning → middleware/perception 예외 4개를 integrations/perception 허용 한 줄로 바꿨다(사용자 결정 2026-11-03 「공유 추론 계층 신설」).
- 교훈: 없음.
