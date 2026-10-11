# 정답 없는 도로 관측 산출 경계

Branch: `feat/perception-fitness-pipeline`. 계약: D-670.

1. 기존 runner 시험에 raw 도로 labels/crop/의미·logit 거절을 추가하고 관측 시험에 image 보류·anchor 보류·기준점 변환을 추가한다. 커밋한 HEAD의 원격 RED를 확인한다.
2. 기존 preprocess/session과 D-665/D-667 helper를 재사용해 최소 공통 추론·관측 함수를 구현한다. D-666 평가를 공통 추론에 연결하되 원본 정답 검증과 ROI 분모를 보존한다.
3. 원격 관련 GREEN 및 known-failure 비교, 독립 소스 검토와 최신 main 통합 검사를 거쳐 local main에 착지한다. 원본 로그·해시 receipt는 X: 세션에 보존한다.

영향 경로는 middleware/perception learned runner/road observation·module test, learning/evaluation/perception road fitness·기존 시험이다. CLI·ROS topic·shadow/paint slot·watcher·장치 설정은 이번 내부 구현 범위가 아니다. 실제 관측 producer와 보정, 별도 consumer/전달 및 device readback·clock alignment·지연/손실 증거는 후속 작업이다.

## 독립 크기·import 경계 재검토

2026-10-12 `review_fixed_fitness`가 `a34e14dde6`의 learned 2,435행을 source-only로 검토했다. 16개 파일은 모델 검증·추론·mask·서명·관측 증거 책임으로 묶이며 관측 파일은 44행, 최대 파일은 364행이다. 조향은 별도 drivable unit에 있고 이번 증분에는 transport·command authority가 없다. 별도 책임을 만들지 않는 분할은 indirection만 늘리므로 accept와 기존 +150행 재검토 조건을 유지한다.

D-667/D-670의 `core_common.observation`은 불변 증거 타입과 표준 라이브러리 기반 순수 유효성 검사다. D-155의 contract surface에 이 모듈만 정확히 포함하고 모든 core_common 또는 운영 core/core_features/core_api_web/core_events를 허용하지 않는다. 이 검토는 실제 장치 수용이나 시험 실행을 대신하지 않는다.
