---
module: docs
---

# Perception Fitness Pipeline Implementation Plan

**Goal:** 최신 인지 학습 경로를 확장하되, 관측한 도로·현재 구역 추정·따라갈 구역 선택의 책임을 먼저 구별한다.

**Architecture:** D-659의 의미 분리는 유지한다. 사용자 보완에 따라 인지 모델은 길 자체를 `drivable`로 검출하고 현재 구역/따라갈 구역은 관측과 위치·경계·미션을 사용하는 로직에서 판단한다. 경로 선택과 운영 권한은 기존 Drive/Fleet/CORE 계약을 따른다.

**Tech Stack:** 기존 Python/NumPy/OpenCV, ONNX manifest, ROS 2 Jazzy, 기존 Isaac/Gazebo 기록, remote committed-HEAD pytest.

상태: 도로 검출과 구역 판단의 분리 방향 확정; 구역 로직의 운영 owner/입력 유효성은 상세 검토 중. [D-663](../adr/D-663-versioned-road-label-semantics.md)의 선택 semantic 필드를 기존 builder/export/eval/delivery에 연결한다. 새 role·구역 segmentation head·운영 소비 활성화는 추가하지 않는다. 코드 기준은 착수 HEAD `8c10dd8a3`이며 통합 전에 최신 main과 다시 대조한다.

## 책임 배치 제안

| 질문 | 제안하는 논리 책임 | 전달물 | 목적지의 영향 |
|---|---|---|---|
| 무엇이 도로이고 어디에 경계·물체가 있는가? | Perception | 가시 도로면·경계·물체와 불확실성 | 없음 |
| 로봇이 지금 어느 도로 구역에 속하는가? | 현재 상태 해석; World 책임과의 정합성 검토 | 구역 후보, 근거, 위치·시각·보정 유효성, 확정 불가 사유 | 없음 |
| 어느 구역으로 진행할 것인가? | Drive 계획·도메인 규칙; 필요 시 Decision 후보 참고 | 선택 경로와 선택 근거 | 있음 |
| 지금 그 경로로 움직여도 되는가? | 기존 Fleet admission 및 CORE/장치 owner | 승인/거절과 실행 결과 | 미션·권한·안전 상태에 의존 |

이 표는 검토안이다. World에 현재 구역 추정 구현이 있다는 뜻이 아니며, 별도 서비스나 새 최상위 폴더를 요구하지 않는다. `operations/decision`의 자문 모델을 일상적인 차선 추종의 필수 실행기로 만들지 않는다.

현재 구역은 관측과 위치에 대한 사실 추정이다. 목적지에 맞춰 갈림길 한쪽을 제거하면 따라갈 구역 선택이 된다. 경계가 없는 연결부는 여러 후보 또는 불확실로 남길 수 있다. 가려진 도로를 임의로 채운 영역과 실제 가시 영역을 같은 정답으로 취급하지 않는다.

## 최신 구현에서 확인한 경계

| 경로 | 현재 동작 | 이행 시 주의 |
|---|---|---|
| `middleware/perception/vision/perception/learned/lane_mask.py` | `lane_bounded_drivable`은 근거리 시드·연결성·경계와 행 폭 제한으로 영역을 산출하고 `lane_evidence`가 소비 | 이 마스크를 전체 도로면 정답으로 재해석하지 않는다. 행 폭 제한은 교차로 후보를 좁힐 수 있다 |
| `middleware/perception/vision/perception/learned/drivable_paint.py` | `drivable_target`은 분기에서 D-384의 우측 선택을 적용하고 추종용 paint를 만든다 | 추종용 선택 결과와 선택 전 인지 영역을 평가에서 구별한다. 물리 경로 이동은 후속 계약·시험 뒤에 한다 |
| `operations/world/src/rosy/world/state/projections/map_pose.py` | 관측·odom으로 현재 MapPose를 투영 | 구역 귀속 기능과 정확도는 구현/검증되지 않았다. 상태 추정 배치 후보로만 사용 |
| `operations/decision/src/rosy/decision/` | Fleet이 소비하는 provenance를 가진 자문 후보 | 이름이 Decision이라고 주행 구역 선택 소유권이 자동으로 생기지 않는다 |
| `middleware/control/drive/tracking/path_follow.py` | 경로·위치의 유효성과 나이를 확인하며 추종 | 인지 모델의 점수나 설치가 이 입력의 유효성을 대신하지 않는다 |
| `learning/registry/perception/intake.py` | 고정 eval set 클래스 이름/role 비교, 세션·예약 출처 분리, IoU·champion 비교 | shadow 전달 적격성과 독립 인지 승인을 구별한다 |

관련 계약: [D-659](../adr/D-659-perception-fitness-and-road-region-semantics.md), [D-576](../adr/D-576-drivable-own-road-beyond-boundary-blocked.md), [D-656](../adr/D-656-responsibility-authority-and-orchestration-boundaries.md). D-576은 경로 계획이 갈림길을 선택한다고 명시한다. 구현 파일의 위치와 논리 소유권을 구별한다.

## Task 1: 현재 구역의 산출 책임과 평가 대상을 결정한다

1. 위 source 경로와 실제 호출자를 추적해 선택 전 관측, 구역 추정, 추종용 선택을 표시한다.
2. 모델의 `drivable`은 도로면 전체를 학습한다. 현재 구역은 기존 도로·경계·검증된 위치로 산출하는 로직을 평가한다. 구역 segmentation head와 목적지/통행 정책을 라벨로 섞는 방식은 추가하지 않는다. 독립 현재 구역 정답은 로직 평가용이며 도로면 학습 라벨로 대체하지 않는다.
3. 같은 영상·위치에서 목적지만 바꾼 경우 도로면과 현재 구역 후보는 같고 선택 경로만 달라야 한다는 독립 사례를 작성한다. 경계 가림·위치 무효·두 갈래 연결부도 포함한다.
4. owner, 입력, 불확실 상태, 출력 소비자, 기존 `drivable` 호환·거절 조건을 상세 ADR로 기록한다. 이 결정 전에는 모델 클래스와 라벨을 변경하지 않는다.

도로면 검수의 새 정의는 `learning/curation/perception/classes/road_surface_v1.yaml`을 사용한다. 기존 lr6/v13 데이터셋에 파일만 덮어씌우지 않는다. class 이름·role은 기존 기본 lane-seg 목록이며 `drivable.semantic`으로 범위를 결속한다. 차선/정지선/횡단보도 칠은 자기 class를 유지하고 가림/미관측은 255로 남긴다.

## Task 2: 라벨부터 평가까지 의미를 보존한다

대상: `learning/curation/perception/build.py`, `learning/training/perception/export_cell.py`, `learning/training/perception/gen_notebook.py`, `learning/registry/perception/intake.py`, `learning/registry/perception/intake_eval_gate.py`와 실제 검수/수출 호출자. 시험은 `test/learning/perception/`의 기존 builder/export/intake suite를 확장한다.

1. Task 1의 계약에 따라 producer·manifest·평가·consumer·fixture 대응표를 확정한다. 기존 산출물의 의미를 임의로 보충하지 않는다.
2. 의미 불명·의미 불일치·원본 split 중복을 거절하는 시험을 먼저 커밋하고 원격 RED를 확인한다.
3. 기존 store/CLI 경로에서 최소 전파·검증을 구현하고 원격 GREEN 및 known-failure 비교를 기록한다. notebook은 generator에서 재생성한다.

## Task 3: 독립 인지와 구역 추정을 각각 평가한다

대상: `learning/evaluation/perception/road_replay.py`와 기존 input/metric helper, `learning/registry/perception/intake.py`, 관련 `test/learning/perception/` 시험.

1. 실물 원본 capture group과 시뮬레이션 원본 장면을 예약·분리하고 독립 정답을 준비한다. 정답용 위치/ID는 모델 입력과 분리한다.
2. 도로면 검출과 현재 구역 추정에 각각 정답·분모·불확실/제외 사유를 둔다. 후속 선택 경로의 성공 여부를 인지 점수로 합치지 않는다.
3. 실물/시뮬레이션 및 조건별 결과를 별도 기록한다. 기준선 측정과 표본·coverage·임계값 고정 전에는 인지 승인을 HOLD로 둔다.

## Task 4: 관측 전용 장치 전달과 후속 주행 경계를 확인한다

기존 `learning/registry/perception/deliver.py` 및 장치 소비자 경로를 재사용한다. 새 표현을 기존 조향 입력으로 자동 변환하지 않는다. 고정 버전·전처리 readback, 촬영부터 결과까지 지연·손실 및 환경 범위를 기록한 뒤 인지 전달물을 만든다. 새 실물 주행·운영 소비 활성화는 후속 주행 계약과 수용 근거가 필요하다.

## 검증과 통합

시험은 노트북에서 실행하지 않는다. 커밋한 HEAD로 `tools/remote/remote_pytest.py --log-dir <X: 세션 logs> -- <관련 suite>`를 실행하고 반환 로그를 `test/known_failures.py`와 비교한다. remote RED는 결함 확인이며 통합 적격성을 의미하지 않는다. GREEN과 lint 후 최신 main 통합·재시험을 거쳐 `tools/land.py`로 착지한다. push, 배포, 장치·현장 수용의 증거를 각각 기록한다.

## 기준선 책임 검토 증거

`middleware/perception/test/test_road_region_baseline.py`에서 기존 함수를 별도로 호출해 세 가지를 확인했다. 연결된 갈림길은 폭 제한을 끈 관측 후보에 양쪽이 남지만 추종 대상에는 우측 선택이 적용된다. 분리된 다른 도로는 후보에서 제외된다. 가림/횡단보도 화소와 crop 밖은 관측 후보에 포함되지 않지만 추종 대상은 둘러싸인 구멍을 채운다.

`c952f2a0a` 원격 시험의 terminal exit는 0이며 known-failure 비교는 NEW 0이다. 추가 시드 불명 사례를 포함한 최신 검증은 별도 기록한다. 첫 시험의 부분집합 가정 실패는 코드 결함으로 확정하지 않았다. 기존 D-597의 gap closing/hole filling을 조사한 뒤 관측된 화소에 대한 포함 관계와 채운 화소의 차이를 따로 검증했다.

이 기준선은 영상 중앙 근거리 시드에 의존한다. 중앙 시드가 없으면 가장 큰 근거리 영역을 택하므로 로봇의 실제 구역 귀속을 확정하는 근거가 될 수 없다. 보정·위치·경계 유효성과 모호한 시드에 대한 보류 계약이 더 필요하다. 현재 구역을 모델로 직접 출력하도록 확정한 근거도 아니다.

구현 증거: D-663의 버전별 drivable 의미가 검수 classes→dataset→export→model/eval/champion까지 보존되며, 기존 조향 슬롯에는 도로면 의미를 전달하지 않는다. `0ab4b7d073` 전체 perception 학습·모델 manifest·harness 원격 회귀는 terminal exit 0, NEW 0이다. `c90bf2d94f`의 엄격 학습/평가 content SHA 및 학습 classes 의미 결속 관련 원격 회귀도 terminal exit 0, NEW 0이다. 이 결과는 소스 시험이며 실제 정답·모델 성능의 수용 증거가 아니다.

현재 구역 로직: D-665가 내부 입력·보류·소비자를 정의한다. World는 관측 snapshot의 시각·유효성·frame/calibration/transform/reference를 확인하고, perception은 확인된 기준점이 하나의 연결 영역에 속하는 경우만 현재 구역을 산출한다. learning의 `road_fitness.evaluate_frame`은 도로면/현재 구역의 독립 정답을 각각 점수화하고 구역 보류에서도 정답 분모를 보존한다. `b64dc94e0a` 원격 합성 로직·기존 기준선·World 설치 wheel 시험은 terminal exit 0, NEW 0이다.

남은 구현: 실제 기준점 투영 생산자와 보정/위치 오차 검증, 독립 정답 데이터/예약/split과 실물·시뮬레이션별 실행·coverage 보고, 물체 독립 평가, 사전 고정 수용 profile, 관측 전용 장치 전달과 지연 readback. 새 도로면 정답 검수·학습과 현장 수용은 아직 확인되지 않았다.

## 20261010 검수 데이터 연결

사용자가 알려 준 Desktop 패키지와 AI PC 원본을 [직접 확인했다](../validation/drivable-reviewed-desktop-2026-10-11.md). 후속 `v13-drivable-human-20261010`은 2,769장(2,167 train / 358 val / 244 test), 모든 frame에 human_edit/done 기록이 있으며 이미지·마스크 5,538개의 hash가 일치했다. 동일 이미지의 split 중복은 0이다. 검수 자료가 없다는 기존 탐색 가정은 이 확인으로 해소됐다.

다만 이 drivable은 선과 로봇 연결성에 따른 기존 구역 의미다. 전체 도로면으로 재해석하거나 semantic을 소급 덧붙이지 않는다. 기준선과 재검수 원본으로 활용하고, 원본 영상 단위 분리·독립 authority·새 도로면/현재 구역 정답을 각각 결속한다. v2 Desktop에는 원본 dataset이 없으므로 AI PC 원본의 manifest 파일 hash와 실제 image/mask hash를 함께 유지한다. manifest 파일 hash를 store content SHA로 대체하지 않는다. crop 112..239 좌표 결속과 평가 분모 차이를 재생 평가 구현에 반영한다.

## 도메인별 집계와 경계 오차 구현

`road_fitness.summarize_frames`는 evaluate_frame의 내부 결과를 받는다. 실물/시뮬레이션과 각 조건을 따로 집계하고, TP·FP·FN 합으로 IoU를 산출한다. 조건이 겹치는 표는 더하지 않으며 조건 없는 frame 수와 입력 오류/구역 보류 사유를 남긴다. 전체 정답 분모와 실제 점수화 분모를 모두 유지하고, 추론 보류와 정답 전체 255를 구별한다. 다른 구역 포함/자기 구역 누락도 별도 합계로 보존한다.

경계 오차는 알려진 네 이웃을 가진 foreground 경계 화소 사이의 양방향 최근접 거리 합/화소 수다. 단위는 화소이며 실제 거리·지도 정확도를 뜻하지 않는다. 영상 끝/미관측 이웃 때문에 제외된 경계 수를 기록하고, 어느 쪽 경계가 없으면 0 대신 미산출과 사유를 남긴다. 집계는 양쪽 경계가 있는 frame만의 거리 분모를 명시하고 보류 frame의 정답 경계 분모도 유지한다.

`468ae9e5ab` 원격 합성 지표·구역·기존 기준선 44개 시험은 terminal exit 0이다. known-failure 비교와 전체 회귀는 별도 기록한다. 데이터/모델 재생 연결과 원본 출처 단위 불확실성 분석·독립 성능·고정 임계값은 아직 미완료이며 결과는 HOLD다.

## 고정 모델의 프레임 재생 연결

`evaluate_model_frame`은 기존 LaneSegModel 로더로 연 모델과 원본 BGR 영상, 독립 도로면/구역 정답, 원본 화소 좌표의 기준점을 받는다. 추론에는 기존 preprocess의 영상 텐서만 전달한다. 원본 정답 값·크기와 모순을 resize/crop 전에 확인하고 정답은 nearest-neighbour로 변환한다. 기준점은 원본 화소 중심의 스케일 변환을 사용한다. 모델 출력의 shape/finite 값도 매 frame 확인한다.

crop 밖 label은 255이고 점수화할 정답에서 제외한다. 실제 정답 255와 crop 때문에 제외된 알려진 정답을 구별하며, 전체 resize grid 대비 coverage와 crop 내 coverage를 모두 보고한다. 다른 입력/모델/촬영 좌표계를 같은 것으로 간주하지 않는다. 모델 클래스 의미 검사는 D-665 기존 함수가 수행한다.

`a8212d3806` 원격 55개 합성 모델/좌표·구역·기존 기준선 시험은 terminal exit 0이다. 실제 ONNX Runtime의 crop/전체 영상 사례 2개가 포함되며 이를 실행할 ML 패키지가 없는 일반 시험 환경에서는 해당 2개만 제외된다. 일반 session-factory 사례는 항상 실행한다. crop 제외 처리를 제거하면 2개 시험이 실패하고, 원본 정답 모순 검사를 별도로 제거하면 1개 시험이 실패하는 것을 확인한 뒤 복구했다.

이 연결은 프레임 재생 어댑터다. 고정 dataset 버전과 source/capture group·예약·사람 authority, model file/manifest의 실행 전후 결속, 실제 보정·기준점 생산자, 오프라인 CLI/보고서 파일 작성은 다음 단계다. 합성 모델의 ONNX 실행은 독립 실물 인지 성능·장치 수용의 증거가 아니다.

## 고정 정답·관측 입력의 오프라인 실행

D-666의 `rosy_ml fitness`는 두 사람 승인 eval set의 동일 영상·identity, 모델/전처리, 별도 관측 입력, 선언된 학습 source/group/영상 중복과 실행 전후 content를 결속한다. 기존 store·검수 publisher의 authority 형식을 사용한다. 로봇 설정 전에 분기하고 intake/delivery/watch를 호출하지 않는다. 정상 실행은 항상 HOLD 보고서다.

D-667은 공통 `core_common.observation`을 학습과 World가 함께 사용하도록 하며 World의 기존 API 객체를 재노출한다. 관측 생산·상태와 실제 보정은 World 책임이다. 서명 코드 묶음은 공통 계약 누락을 거절한다. 패키지 의존 버전은 새로운 계약 파일이 없는 기존 설치본을 구분한다.

2026-10-12: 재생 20개 합성 시험은 terminal exit 0이다. 승인 hash 검사와 짝 영상 검사를 제거하면 각각의 거절 시험이 실패하는 것을 확인하고 복구했다. World/학습 import 경계와 wheel 설치 시험도 공통 계약 이전 후 통과했다. 최신 패키지 버전·전체 회귀·착지는 별도 증거를 기록한다.

이 단계는 독립 실물/시뮬레이션 정답을 만들거나 승인하지 않는다. 기존 20261010 검수 데이터는 연결된 현재 도로 구역 의미로 보존한다. 전체 도로면의 독립 정답·구역 정답 pair, 실제 관측 기준점 생산자/보정·출처, upstream 학습 closure·검수 독립성, 물체 평가, 조건/출처 단위 불확실성, 사전 고정 수용 profile, 장치 관측 전달/지연/손실은 후속 작업이다. 이 자료가 없으면 성능 승인과 주행 단계는 HOLD다.

## 출처 단위 불확실성 진단 연결

2026-10-12: D-690은 고정 재생의 검증된 capture group을 결속해 출처별 표본 수·coverage와 조건별 percentile 재표집 구간을 추가한다. 프레임을 따로 재표집하지 않고 도로면·현재 구역의 기존 합산 분모를 유지한다. 단일 출처나 미정의 분모는 구간을 만들지 않는다. [원격 시험 기록](../validation/perception-source-uncertainty-2026-10-12.md). 이 항목의 소스 구현은 완료했으며 출처 분류의 독립 검수·충분한 표본 수·고정 수용 profile 및 실제 성능 수용은 계속 HOLD다.
