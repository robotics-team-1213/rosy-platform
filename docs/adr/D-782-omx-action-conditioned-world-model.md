## D-782 OMX 행동 조건부 World 모델 도입: 실행 전 검사기부터 시작하고, 예측은 거절 근거로만 쓴다

**Status:** Proposed

## Context

2026-10-17 사용자 요청: 로봇팔 작업을 위해 미래 상태를 예측하는 World 모델을 실제로 도입한다.
D-625 §6은 World State(현재 근거)와 Prediction(행동을 가정한 미래 추정)을 별도 계약으로 두되,
입력 revision·후보 행동·horizon·모델 digest·불확실성·만료, 실제 소비자와 독립 평가가 정해지기 전에는
구현하지 않기로 했다. 이 ADR은 그 빈칸을 OMX 팔 기준으로 채운다. 모델 선정이나 wire 발행은 아니다.

### 이번에 확인한 사실

| 항목 | 현재 | 근거 |
|---|---|---|
| World State | Pinky `MapPose`만 있다. `bridged`는 dead reckoning이다. 팔·물체·파지 상태 projection은 없다 | `operations/world`, D-630, D-752 |
| Prediction | `operations/prediction/world_model`, `learning/{training,evaluation}/world_model`은 목표 배치일 뿐 만들지 않았다 | D-625, 폴더 책임 안내 |
| ACT | Gazebo 3 episode·38 frame 학습이 상수 기준보다 나빠 reject. ACT 출력은 World 모델로 세지 않는다 | `docs/validation/omx-act-offline-2026-10-04.md` |
| 실물 데이터 | 실물 시연 0회. 첫 수집은 2026-10-18 D-770 G1 | D-770, 다음 날 실행 계획 |
| 수집 기록 | 10 Hz top/front RGB, 관절 관측, controller reference, 요청 목표, native 이벤트, 원본 시각. `664b101fa`부터 선택적 CameraInfo·카메라 장착 위치·검토 `object_result` | `deploy/robot/omx/collection_*`, `learning/curation/omx/native_review.py` |
| 카메라 | 현장 top/front publisher는 Image만 발행한다. CameraInfo 없음, calibration unverified | 2026-10-17 Fleet PC 읽기 확인 |
| 실패 기록 | 중단된 시도는 LeRobot dataset에서 빠지고 원본만 `rosy_provenance/`에 남는다 | `collection_intake.py` |
| 시뮬레이터 | Gazebo 손가락 접촉이 메쉬보다 5~9 mm 넓고 파지 중 joint1 jog마다 미끄러짐이 있다. Isaac은 Pinky 전용 | `STATUS.md` omx_adapter |
| 연산 | 모델 PC OMX 학습 환경은 CPU torch다. GPU 사용 여부는 정하지 않았다 | `learning/training/omx/README.md` |

## Decision

### 1. 첫 용도는 실행 전 검사기다

첫 World 모델은 **후보 행동 묶음(ACT chunk 또는 teacher 단계)을 받아 다음 몇 step의 관절·집게 상태와
물체 결과를 예측하고, 위험하면 거절·보류 근거를 내는 검사기**다.

- 예측은 **거절(REJECT)·보류(HOLD) 근거로만** 쓴다. 예측이 "문제없음"이어도 실행을 허가하지 않는다.
  허가는 기존 Fleet admission과 owner 재검사(D-773 §1·§4)가 그대로 맡는다.
- 예측기의 기권·만료·오류·부재는 기존 gate를 바꾸지 않는다. 예측기가 망가져도 지금보다 덜 안전해지지 않는다.
- 예측 성공은 실행 완료나 과제 성공의 증거가 아니다(D-625 §6, D-290). 결과 판정은 실제 관측과 사람 검토가 한다.
- 계획(MPC)·모델 안 정책 평가는 같은 모델을 쓰는 후속 용도다. 검사기의 수용 증거가 쌓인 뒤 별도 결정으로 연다.

### 2. Prediction 계약의 필드를 정한다

W2에서 `contracts/learning`에 ROS-free 타입으로 둔다. 그 전까지는 이 표가 설계 요구이며 wire 필드가 아니다.

| 구분 | 필드 | 뜻 |
|---|---|---|
| 입력 | `state_ref` | 수집 sample/owner 관측 식별자, host·source 시각, rig·calibration revision |
| 입력 | `action` | 절대 관절 목표 묶음(normalized 단위), 출처(teacher hash 또는 policy revision), step 간격 |
| 입력 | `horizon_steps` | 예측 step 수. 첫 범위 1..10 @ 10 Hz |
| 출력 | `predicted_states` | step별 관절·집게 예측값 |
| 출력 | `object_result` | `native_review.OBJECT_RESULTS` 각 값의 확률 |
| 출력 | `uncertainty` | step별 분산 또는 ensemble 불일치 |
| 출력 | `abstain` / `abstain_reason` | 입력 분포 밖, 입력 만료, 보정 revision 불일치 |
| 출력 | `verdict` | `NO_OBJECTION` / `HOLD` / `REJECT` / `ABSTAIN`과 근거. `ABSTAIN`은 예측값을 담지 않는다 |
| 계보 | `model_digest`, `dataset_manifest_sha256`, `produced_at_ns`, `expires_at_ns` | 승인 버전 대조와 만료 |

입력 관측이 만료됐거나 rig·calibration revision이 학습 데이터와 다르면 예측하지 않고 기권한다.

### 3. 팔 World State는 사실만 담는다

`operations/world`의 projection으로 팔 상태를 둔다. 예측과 섞지 않는다(D-625 §6).

- 관절·집게: 기존 owner 관측에서 온다. owner가 단일 writer이며 World는 읽기만 한다.
- 물체: 첫 단계는 사람 검토의 `object_result`(사후 라벨)뿐이다. 실시간 물체 자세는 top 카메라 검출과
  카메라 보정이 수용된 뒤에 별도 결정으로 추가한다.
- 카메라 intrinsic은 D-636 측정 도구·D-775 승인 경로를 재사용한다. OMX 카메라가 CameraInfo를 발행하는 것은
  그 수용 뒤의 일이며, 그 전에는 수집 profile에 `camera_info_topics`를 넣지 않는다.

### 4. 모델은 작은 것부터 단계를 밟는다

| 단계 | 모델 | 입력 | 연산 | 여는 조건 |
|---|---|---|---|---|
| M1 | 저차원 동역학 ensemble(첫 구현: bootstrap ridge) | 관절·집게 상태 + 행동 묶음 | CPU | W1 데이터 기준 충족 |
| M2 | M1 + 물체 결과 분류 | M1 + top/front RGB | CPU 또는 GPU | M1 수용, `object_result` 라벨 충분 |
| M3 | 사전학습 영상·latent World 모델 fine-tune | RGB + 행동 | GPU | M2 수용, GPU 결정, 라이선스 검토 |

모델 계열·라이브러리는 이 ADR에서 고르지 않는다. M3 후보를 고를 때 라이선스·가중치 출처·추론 지연을 함께 기록한다.

### 5. 데이터는 성공만이 아니라 행동과 결과 전체를 모은다

- World 모델 dataset은 BC dataset과 따로 만든다. 성공·실패·중단 시도를 모두 포함하고, 사람 검토의
  `outcome`·`object_result`를 라벨로 쓴다. `unknown`은 학습 라벨에서 빼되 원본은 보존한다.
- 중단 시도는 `rosy_provenance/`의 원본 RGB·관절·명령에서 다시 만든다. LeRobot dataset 형식을 우회하는
  새 저장소를 만들지 않고 `learning/curation/omx`에 builder를 추가한다.
- 분할은 session 단위로 독립시킨다. 같은 session·cycle이 train과 eval에 나뉘면 거절한다.
- 행동 다양성: 같은 teacher 반복만으로는 행동과 결과의 관계를 배울 수 없다. teacher 변형(시작 자세·물체 위치·
  목표의 제한된 섭동)은 각각 별도 acceptance와 D-430 Safety 리뷰를 받는다. 수량을 채우려 범위를 넓히지 않는다.
- 제안 목표(품질 보장 기준이 아님): M1 학습에 **10개 이상 session, 100회 이상 시도, 실패 20회 이상**,
  M3 검토에 **500 episode 이상**. 실제 확보 수량은 따로 보고한다.

### 6. 수용 기준은 단순 기준선을 이겨야 한다

- **오프라인(W1·W2):** 독립 session에서 horizon별 관절 예측 오차가 ①상태 유지 기준 ②"목표에 그대로 도달"
  기준을 **둘 다** 이긴다. 불확실성 구간의 실제 포함률을 보고한다. 물체 결과는 정해진 오경보율에서
  실제 실패 재현율을 보고한다.
- **그림자(W3):** 실물 실행은 그대로 하고 예측 verdict만 기록한다. 실제 결과와 대조해 거절 정밀도·재현율을 낸다.
- **실사용(W4):** 그림자 결과와 사용자 승인 뒤에만 veto를 켠다. 수치 기준은 W3 결과를 보고 별도로 정한다.

### 7. 단계와 폴더는 실제 소비자가 생길 때 만든다

D-773 §5대로 빈 폴더를 미리 만들지 않는다. 각 단계는 한 브랜치로 착지한다.

2026-10-17 사용자 요청으로 W1~W3의 **코드 기반**을 먼저 만들었다. 각 위치에는 구현과 시험이 있고 빈 폴더는 없다.
실물 데이터가 없으므로 끝난 기준(실물 session 보고, 오프라인 기준 통과, 그림자 대조)은 아직 충족하지 않았다.
W4 결선은 하지 않았다. 아래 `현재` 열이 그 상태다.

| 단계 | 할 일 | 새 위치 | 끝난 기준 | 선행 | 현재 |
|---|---|---|---|---|---|
| W0 기록 | 카메라 모델·장착 위치·물체 결과 기록 | 없음(기존 수집기) | `664b101fa` 착지 | 없음 | 완료 |
| W1 데이터 | 중단 시도 포함 World 모델 dataset builder, session 분할, 기준선 평가 스크립트 | `learning/curation/omx` 안 | 실물 session으로 builder·기준선 보고 | D-770 G1 | 코드·합성 시험 |
| W2 M1 학습 | Prediction 계약, M1 학습 job, 오프라인 평가 | `contracts/learning`, `learning/training/world_model`, `learning/evaluation/world_model` | §6 오프라인 기준 통과 | W1 | 코드·합성 시험 |
| W3 그림자 | 승인 버전 추론, verdict 기록만 | `operations/prediction/world_model` | 그림자 대조 기록 | W2, D-773 A3 | 검사기·기록·오프라인 재생. 실물 결선 없음 |
| W4 veto | owner 재검사 또는 Fleet admission에서 REJECT/HOLD 근거로 사용 | 기존 owner·admission 안 | 사용자 승인, D-430 Safety 리뷰 | W3, D-773 A4 | 미결선 |

## Alternatives

| 접근 | 판단 |
|---|---|
| 처음부터 사전학습 영상 World 모델(M3) 도입 | 실물 데이터 0회, CPU 환경, 접촉 시뮬 부정확. 검증할 근거가 없어 지금은 선택하지 않음 |
| 계획(MPC)을 첫 용도로 | 모델 오류가 바로 행동 선택에 들어간다. 검사기로 신뢰를 쌓은 뒤 연다 |
| ACT 정책을 World 모델로 간주 | 정책은 행동을 내고 결과를 예측하지 않는다. 폴더 책임 안내가 이미 거절했다 |
| Gazebo 데이터로 먼저 학습 | 접촉·파지 동역학 차이가 커서 실물 예측 근거가 되지 않는다. 형식·파이프라인 시험에만 쓴다 |
| 예측을 허가 근거로도 사용 | 예측기 오류가 실행 권한으로 이어진다. veto 전용이 기존 권한 경계를 지킨다 |
| **작은 검사기 → 그림자 → veto** | 권장. 데이터가 적을 때 시작할 수 있고 실패해도 기존 안전 경계를 낮추지 않는다 |

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | middleware·operations·learning 경계 유지. 학습·평가는 learning, 그림자 추론 소비는 operations에 둔다 |
| D-429 | 새 위치는 `api` 모듈 import 규칙을 따른다. W3 전까지 operations 쪽 코드는 없다 |
| D-430 | 이 ADR은 safety 경로를 바꾸지 않는다. teacher 변형(§5)과 W4 veto 결선은 Safety 리뷰 대상이다 |
| D-290 | 모델 설명이 실행 사실을 덮어쓰지 않는다. 예측은 사실이 아니다 |
| D-503 | 실제 추가 소비자 조건을 W3 그림자 소비자로 충족한다 |
| D-516, D-527 | 모델 PC 학습·평가, AI PC 승인 버전 추론, Fleet 판정, 장치 재검사 순서 유지 |
| D-625 | §6 Prediction 계약의 필드·소비자·평가를 이 ADR이 정한다. 목표 폴더는 §7 단계에서만 만든다 |
| D-630, D-752 | World는 현재 상태 projection. 팔 상태도 같은 원칙으로 둔다 |
| D-647 | 공통 판단을 World 모델로 묶지 않는다. 예측은 판단의 입력 중 하나다 |
| D-636, D-775 | OMX 카메라 intrinsic은 기존 측정·승인 경로를 재사용한다 |
| D-770 | 데이터는 D-770 수집 경로에서 온다. W1은 G1 뒤에 시작한다 |
| D-773 | 새 실행기·최상위 폴더 없음. 예측은 후보를 거르는 근거이며 실행 권한이 없다. W3·W4는 A3·A4에 묶인다 |

## Consequences

- World 모델 작업이 지금 바로 할 일(데이터 기록)과 데이터가 쌓여야 할 일(학습·그림자·veto)로 나뉜다.
- 예측이 veto 전용이라 성능이 낮아도 운영 위험은 늘지 않는다. 대신 허가 속도를 높이는 효과는 W4 뒤에야 생긴다.
- teacher 변형마다 acceptance와 Safety 리뷰가 필요해 데이터 수집 속도가 느려진다. 안전 경계를 위한 비용으로 받아들인다.
- 정해지지 않은 것: GPU 사용 여부와 위치, M3 모델 계열, 실시간 물체 자세 추정 방법, W4 veto의 수치 기준.

## References

- [D-625 의미 구조와 단계적 이전](D-625-semantic-structure-and-staged-migration.md)
- [플랫폼 정체성과 구조 설계 §5](../plans/2026-10-11-rosy-platform-identity-and-structure-design.md)
- [D-770 OMX 자동 시연 수집과 모방학습](D-770-fleet-omx-autonomous-imitation-pipeline.md)
- [D-773 OMX와 AI를 더하기 위한 플랫폼 구조](D-773-omx-ai-extension-platform-structure.md)
- [OMX 다음 날 실물 수집 실행 안내](../plans/2026-10-17-omx-next-day-collection.md)
- [현재 폴더 책임](../reference/platform-folder-responsibilities.md)
