# perception_runtime logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
이 패키지로 옮기기 전 이력은 `git log --follow`와 `middleware/perception/logs.md`를 본다.

## 2026-11-03 · uncommitted · refactor(perception): split perception_runtime out of control
- 변경: `control.recording`, `control.keep_odom_veto`, `control.sensing.perception`의 차선 판정 16개 모듈, `learned`의 모델 계약·실행 10개 모듈(모두 28개, 6,491줄)을 이 패키지로 옮겼다. 본문은 그대로 두고 import 경로만 바꿨다. 이 모듈들만 시험하던 14개 시험도 함께 옮겼다.
- 증거: 이전·이후 import 닫힘을 AST로 계산해 `rclpy`·middleware 의존이 없음을 확인했다. 원격 시험 결과는 착지 기록에 남긴다.
- gate 변화: 신규. SOURCE·LOCAL GO, 나머지 N/A(라이브러리 등급).
- 결정: learning → middleware/perception 예외 4개를 integrations/perception 허용 한 줄로 바꿨다(사용자 결정 2026-11-03 「공유 추론 계층 신설」).
- 교훈: 없음.

## 2026-11-11 · 1e35310e23 · feat(perception): floor_pink_mask HSV paint source (D-1013)
- 변경: `perception_runtime/perception/lane_keep_lines.py`에 PINK_* 상수와 `floor_pink_mask`(HSV H 140–170·S ≥ 80·V ≥ 60, 수평선 잘림은 흰 마스크와 같은 마진, 작은 성분 제거 공유). 시험 `test/test_lane_pink_mask.py` 5건(그림자 유지·흰 도색·파란 테이프 배제·흰 마스크와 상호 배제)
- 증거: 원격 pytest(ai PC) 4파일 14 passed, exit 0 (run 1e35310e23-a2f4a9, 첫 실행 1e35310e23 2실패는 시험 코드 경계 오차·pose 요소 읽기 오류로 1e35310e23에서 수정)
- gate 변화: 없음
- 결정: D-1013 3항 프레임 수용의 색 소스. 흰 마스크의 MAX_SATURATION 배제와 상호 보완해 한 프레임에 두 도색이 공존한다
- 교훈: 없음
