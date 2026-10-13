# 자동 초안의 도로 의미 계보 검사

Branch: `feat/perception-fitness-pipeline`. 계약: D-663.

클래스 ID·이름·role이 같더라도 모델과 classes YAML의 drivable 의미가 다르면 자동 초안을 만들지 않는다. 현재 `ClassSpec`은 semantic을 가지지 않으므로 검증된 raw manifest classes를 공통 `prelabel.resolve_classes`에 함께 전달한다. 양쪽 의미 미확인은 기존 연구 호환으로 유지하되 한쪽만 선언한 의미 또는 불일치는 거절한다. semantic을 새 값으로 보충하지 않는다.

1. 공통 검사에서 의미 불일치·한쪽만 선언·같은 의미·구형 호환·클래스 행 순서 사례와 CLI 출력 생성 전 거절을 시험하고 원격 RED를 확인한다.
2. `prelabel`과 `pixel_label_job`의 호출을 raw manifest 계보에 결속하고 관련 fixture를 맞춘다. 색상·클래스 ID·초안 pending 동작은 유지한다.
3. 원격 관련 GREEN/known failures, 독립 소스 검토와 최신 main 통합을 거쳐 local main에 병합한다. 실행 기록은 X:에 보존한다.

다른 클래스 의미를 선언해 기존 모델의 출력을 새 의미로 바꾸는 경로만 막는다. 실제 도로면 후보 학습·독립 정답·장치 관측 전달은 이 소스 검사로 증명하지 않는다.
