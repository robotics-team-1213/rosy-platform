# 도로면 검수 경계 수정 계획

Branch: `feat/perception-fitness-pipeline`. 계약: D-659/D-663.

목표는 새 도로면 검수에서 현재 구역용 차선 제한이 정답을 자르지 않게 하는 것이다. 기존 클래스 바이트·작업공간·검수 승인과 의미 미확인/현재 구역 동작을 보존한다.

1. `review_masks`의 unknown 병합과 경계 검사, indexed draft import/apply/approve에 도로면 사례를 추가하고 원격 RED를 확인한다. 기존 구역·구형 시험도 유지한다.
2. 검증된 classes의 명시적 `road_surface/1`에만 차선 제한을 적용하지 않는다. reviewed pixels 불변·255·pending·승인 버전 결속은 유지한다. 차선 내부 초안을 만드는 `clip_lane_draft`와 `qwen_review_completion`은 전체 도로면 입력을 처리 전에 거절한다.
3. 관련 원격 GREEN, known failures 비교, 독립 검토와 최신 main 통합 후 local main에 병합한다. 실행 기록은 X:에 둔다.

영향은 공통 `review_masks`, indexed import/preview/update, Qwen completion와 차선 clipping CLI 및 관련 시험이다. 기존 Desktop 데이터를 수정하거나 자동 초안을 독립 정답으로 승인하지 않는다. 다른 자동 라벨 producer의 도로면 지원, 실제 독립 검수와 관측 전달은 별도 검증한다.
