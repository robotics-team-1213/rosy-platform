## D-663 도로 라벨의 의미 버전을 보존하고 다른 의미의 평가·전달을 거절한다

**Status:** Accepted (2026-10-11, D-659 파이프라인 구현의 산출물 호환 계약). 적용 범위는 의미 기록·평가 호환·기존 전달의 거절 조건이며 새 segmentation 출력이나 운영 소비자의 활성화를 결정하지 않는다.

### Context

D-659는 도로면·현재 도로 구역·선택 경로를 구별하지만 실제 role/필드는 상세 계약 뒤에 바꾸도록 했다. 사용자 보완에 따라 현재 구역을 segmentation이 직접 예측할지, 관측과 위치를 조합해 산출할지는 아직 검토한다. 최신 source 기준선 시험은 연결 구역과 우측 추종 선택, hole filling의 차이를 확인했다. 클래스 이름과 `drivable` role만 같으면 이 차이를 현재 intake/champion 비교에서 추적할 수 없다.

### Decision

#### 1. 클래스 의미는 산출물 계보의 일부다

기존 클래스 이름·index·role·tensor shape와 model/1·dataset/1은 유지한다. `classes[]`의 선택 필드 `semantic`을 추가하고 모델은 `output.classes[]`에 같은 값을 수출한다. 초기 폐쇄 목록은 `drivable` role에만 적용한다.

| 값 | 정답 의미 | 목적지 의존 |
|---|---|---|
| `road_surface/1` | 보이는 도로 바닥 전체. 다른 도로 구역도 도로다. 가림과 미관측을 확정 바닥으로 채우지 않는다 | 없음 |
| `current_road_region/1` | 로봇이 속한 도로 구획의 가시 영역. 경계 없는 연결부는 두 갈래를 포함할 수 있다. 근거 부족은 255/불확실 | 없음 |
| `trajectory_band/1` | 기록된 궤적의 띠에 근거한 자동 학습 라벨. 전체 도로면 또는 확정 구역 정답을 뜻하지 않는다 | 기록 출처에 의존 |
| 필드 없음 | 구형 산출물의 의미 미확인. 원래 계약과 버전을 보존 | 추정하지 않음 |

`semantic: null`, 빈 문자열, 오탈자와 다른 role의 사용은 거절한다. 값을 class 이름·annotation_origin·model revision으로 자동 보충하지 않는다. 검수 classes 원본에 의미를 적고 기존 classes SHA/signature·승인·데이터셋 content SHA가 그 정의를 결속하도록 한다. 기존 승인·모델을 나중에 수정해 독립 정답으로 승격하지 않는다.

현재 구역이라는 개념을 모델의 필수 새 head로 만들지 않는다. 영상 기반 연결 영역은 평가 기준선 후보이며 실제 구역 귀속에는 시드·보정·위치 유효성과 모호성 처리가 필요하다. World/Drive/Decision의 운영 소유권과 새 현재 상태 필드는 후속 상세 계약에서 확정한다.

#### 2. 기존 producer 경로에서 값을 보존한다

`build.load_classes`와 자동 라벨 builder는 의미를 검증·보존한다. 검수 builder는 기존 `load_classes`와 봉인된 classes 바이트를 그대로 사용한다. trainer notebook은 dataset classes의 객체를 export에 전달하고 export_cell은 `semantic`을 보존한다. ONNX 수출 CLI도 같은 writer를 사용한다. 모델 loader는 필드를 검증하되 `ClassSpec`와 ROS/API payload를 확장하지 않고 raw manifest에 보존한다.

모델 기반 prelabel과 pixel draft job은 검증된 raw manifest classes의 ID·이름·role 및 각 클래스 semantic을 출력 classes YAML과 비교한다. 이름과 tensor ID가 같아도 의미가 다르거나 한쪽만 의미를 선언하면 출력 생성·프레임 추론 전에 거절한다. 같은 명시 의미는 그대로 보존하며 양쪽 의미 미확인은 구형 연구 호환으로만 유지한다. ClassSpec만으로 새 의미의 동일성을 추정하지 않는다.

`v13-drivable`의 명시적 의미는 `current_road_region/1`만 허용한다. 기존 의미 미확인 v13은 호환 읽기가 가능하되 상세 인지 적합성의 증거로 인정하지 않는다. 전체 도로면 모델은 v13으로 위장하지 않는다.

검수의 unknown 병합·indexed draft import/apply·승인에서는 명시적 `road_surface/1`을 자기 차선 안쪽으로 제한하지 않는다. 다른 차선의 가시 도로도 정답에 남겨야 하기 때문이다. 구형 의미 미확인과 현재 구역 라벨의 기존 차선 제한은 유지하고, 이미 검수한 화소를 덮거나 초안을 자동 승인하지 않는다. 자기 차선 초안을 만드는 lane clipping/Qwen completion 도구는 전체 도로면 classes를 처리 전에 거절한다. 기존 클래스 바이트나 검수 작업공간을 소급 변경하지 않는다.

#### 3. 의미가 다른 점수와 champion은 비교하지 않는다

고정 평가 보고서는 matched drivable 클래스의 model/eval 의미, 불일치 및 의미 미확인 클래스를 기록한다. 한쪽만 선언한 경우도 일치가 증명되지 않으므로 거절한다. 둘 다 필드가 없는 구형 연구 비교는 유지하되 의미 미확인으로 보고한다. champion은 같은 평가 content SHA와 같은 선언 의미에서만 고른다.

기존 gate의 선택 bool `require_label_semantics`를 추가한다. true이면 미확인 또는 정답과 매칭되지 않은 drivable 클래스가 하나라도 있는 후보를 거절한다. false/default는 기존 연구 호환 경로다. 상세 인지 적합성 평가에서는 true와 `require_eval`을 함께 사용하고 기존 독립 출처/split/검수·표본/coverage/임계값 관문을 별도로 충족해야 한다. 이 옵션 하나를 켰다고 인지 승인이 생기지 않는다.

#### 4. 기존 조향 소비자의 의미를 보호한다

기존 모델 전달은 의미가 선언된 `road_surface/1`·`trajectory_band/1`을 lane_seg 조향/paint/shadow 슬롯에 넣지 않는다. 현재 구역 선언도 기존 lineage·서명·intake·슬롯 제한을 모두 통과해야 한다. 구형 모델의 원래 슬롯 호환은 유지한다. 같은 클래스 이름이라는 이유로 도로면 모델을 기존 조향 입력으로 변환하지 않는다.

직접 로드와 pointer 변경에서도 같은 경계를 지킨다. 기존 `LaneSegModel`의 lane evidence·paint·drivable 후처리는 추론 전에 같은 의미 검사를 수행한다. `ModelSlot`은 다른 의미의 lane 모델로 교체를 거절하고 이전 모델을 유지한다. 검사는 manifest 공통 helper를 전달 도구와 런타임이 재사용한다. manifest 검증·원시 session 로드는 오프라인 도로면 평가에 계속 사용할 수 있다.

전체 도로면에 대한 새 관측 전용 consumer와 전달물은 후속 단계다. 현재 intake 결과는 D-356 shadow 전달 적격성이다. 도로면 후보를 오프라인으로 평가할 수 있어도 그 결과로 기존 슬롯 전달이 승인되지는 않는다.

### Consequences and verification

실물/시뮬레이션, road_surface/current_region 및 선택 경로의 평가 범위가 명확해진다. 기존 의미 미확인 데이터와 모델은 strict fitness를 통과할 수 없으므로 기존 검수 경로에서 정의·출처를 확인해 새 산출물로 만들어야 한다.

시험은 classes→dataset→export 의미 보존, 잘못된 값/role, v13 의미 위장, model/eval 불일치, 한쪽만 선언, 구형 strict 거절, champion 혼용 거절과 delivery의 SSH 이전 거절을 확인한다. 원격 source 회귀·lint는 실제 독립 정답, 학습된 모델 정확도, 장치 지연·관측 전달 또는 주행 수용을 대신하지 않는다.

**Related:** [D-659](D-659-perception-fitness-and-road-region-semantics.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-356](D-356-perception-learning-loop-and-model-delivery.md), D-637.
