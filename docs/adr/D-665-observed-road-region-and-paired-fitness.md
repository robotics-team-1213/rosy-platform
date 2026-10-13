## D-665 관측 도로면의 기준점 기반 현재 구역과 독립 평가 입력을 분리한다

**Status:** Accepted (2026-10-11, D-659 이행과 사용자 drivable/로직 분리 지시). 내부 관측·오프라인 평가 계약이며 운영 소비 활성화·API 변경·실물 적합성 승인은 아니다.

### Context

모델의 `drivable`은 보이는 길 자체다. 현재 구역과 목적지에 따른 경로는 로직이 판단한다. 기존 `lane_bounded_drivable`은 중앙 시드가 없으면 가장 큰 근거리 영역을 택하고 폭을 제한한다. 기존 `drivable_target`에는 가지 선택과 구멍 채우기도 있다. 이 조향 기준선을 실제 구역 귀속 또는 전체 도로 정답으로 재해석하지 않는다.

World는 D-656의 현재 관측 projection 소유자이고 perception은 영상 기하를 처리한다. 기존 MapPose는 위치를 제공하지만 카메라 화소의 구역 귀속을 확정하지 않는다. 기준점의 존재만으로 보정·위치 정확도가 입증되지 않는다.

### Decision

#### 1. 새 모델 출력 대신 관측과 로직을 연결한다

| 생산자/소비자 | 입력과 책임 | 출력/거절 |
|---|---|---|
| 기존 curation/training/export | D-663 `road_surface/1` drivable, 다른 칠은 자기 class, 미관측 255 | 모델의 전체 도로면 의미 보존 |
| perception `learned/road_region.py` | 정수 label image, raw classes, 확인된 기준점의 `(row, col)` 목록 | 한 연결 구역의 관측 drivable 화소 또는 보류; 조향·목적지 입력 없음 |
| World `state/projections/road_region.py` | 기존 `ObservationSnapshot` 영상/기준점 투영 근거, 판정 시각과 명시적 최대 나이 | 시각·validity·frame·calibration·transform·영상 reference 오류 목록; 화소 처리는 하지 않음 |
| learning `evaluation/perception/road_fitness.py` | 위 두 경로, 별도의 도로면/현재 구역 정답과 출처 도메인 | 의미별 지표·분모·불확실/보류 기록; 인지 승인은 HOLD |
| 후속 Drive/Decision | 검증된 관측과 목적지·통행 규칙 | 선택 경로. 이 단계에서는 연결/활성화하지 않음 |

기준점은 영상 관측에 맞춰 실물에서 얻을 수 있는 위치·보정·변환으로 투영한 구역 귀속 근거다. 투영 근거 snapshot은 원 영상 snapshot ID를 evidence reference로 포함하고 같은 camera frame·calibration revision·transform revision을 가진다. 유효·신선한 근거만 사용한다. 최대 나이는 측정 후 평가 profile에서 명시하며 새 임의 기본값을 넣지 않는다. 시뮬레이터 정답 위치/ID와 평가용 현재 구역 마스크를 기준점 생성에 쓰지 않는다. 실제 투영 생산자·보정/오차 검증이 없으면 실제 구역 판단은 HOLD다.

#### 2. 영상의 현재 구역은 목적지 없이 산출한다

초기 로직은 drivable 화소와 명시한 stop-line/crosswalk 칠을 통한 4-connected component를 만든다. lane-marking, 장애물, 다른 ignore class와 미관측 화소는 통과하지 않는다. 출력은 drivable 화소만이며 칠·가림을 채우거나 폭 제한·가지 선택을 하지 않는다. 도로면은 모든 drivable 화소를 유지한다.

모든 기준점이 같은 양의 component에 속할 때만 그 구역을 반환한다. 기준점 없음, 범위 밖, 도로 외/가림 또는 여러 component에 걸침은 보류한다. 중앙/최대 영역으로 대체하지 않는다. 경계 없는 연결 갈림길은 양쪽을 유지하고 목적지 변경은 도로면·현재 구역에 영향을 주지 않는다. component ID는 해당 영상의 임시 식별자이며 지도 lane ID나 시간 간 영속 ID가 아니다. 관측으로 분리된 영역을 보이지 않는 지도 연결로 채우지 않는다.

#### 3. 도로면과 구역 정답은 평가에만 사용한다

각 정답은 0=해당 영역 밖, 1=해당 영역, 255=불확실이며 독립적으로 만든다. 모델/구역 함수는 이 정답을 받지 않는다. 도로면 IoU·밖 오인·누락, 구역 IoU·다른 관측 도로 포함·자기 구역 누락, 정답 유효/불확실 화소와 보류를 따로 기록한다. 구역 보류에서도 정답 분모를 지우지 않는다. 실제/시뮬레이션과 조건은 별도 표본으로 남기고 합쳐서 실패를 상쇄하지 않는다.

임계값·최소 표본·coverage·장면 분리·독립 검수·실물 보정 및 장치 지연을 확인하기 전 결과는 진단/HOLD다. 합성 배열 시험은 로직 증거이며 실제 인지 적합성 증거가 아니다. 물체 독립 정답과 precision/recall은 별도 평가 경로로 연결해야 한다.

#### 4. D-663 엄격 의미를 실제 학습/평가 버전에 결속한다

`require_label_semantics: true`에서는 기존 store의 실제 content SHA와 읽은 manifest의 안정성을 확인한다. 평가 화소가 추론 중 바뀌면 설정 오류로 보류한다. 확인된 학습 classes와 모델의 의미가 다르거나 미확인이면 거절한다. 이는 사람 검수·독립 출처·coverage 승인의 증거를 대신하지 않는다. 기본 연구 경로와 기존 운용 모델·슬롯은 D-663대로 보존한다.

### Consequences and verification

전체 도로면은 인지가, 현재 구역은 관측 기하와 근거 유효성 로직이, 선택 경로는 후속 주행 판단이 맡는다. 새 구역 segmentation head·ROS field·Fleet route API·서비스·최종 command publisher는 추가하지 않는다.

시험은 양쪽 갈림길 유지, 분리된 다른 도로 제외, paint/가림/경계 처리, 시드 없음/불일치 보류, stale/invalid/frame/calibration/transform/reference 오류, 독립 정답의 분모와 보류 기록 및 설치 wheel을 확인한다. 실제 기준점 생산자·실물/시뮬레이션 정답·모델 고정 평가와 관측 전용 전달은 후속 실행 증거가 필요하다.

**Related:** [D-659](D-659-perception-fitness-and-road-region-semantics.md), [D-663](D-663-versioned-road-label-semantics.md), [D-656](D-656-responsibility-authority-and-orchestration-boundaries.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md).
