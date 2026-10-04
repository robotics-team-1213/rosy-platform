# ACT 모델 bytes·관측 provenance와 큐 설정 비교

2026-10-04, 기준 HEAD `1cb2b340e355044b5e8aef66ba5d11ece29bb67e`의
`feat/learning-pipeline-closure` 로컬 변경. SOURCE/HOST numerical·replay 증거이며,
owner dispatch나 독립 SIM 과제·DEVICE/FIELD 수용 증거가 아니다.

## 구현과 시험

`learning/training/omx/act_inference.py`는 pinned artifact 파일을 확인한 후 config/weights/
정규화 bytes를 메모리에 snapshot하고 CPU ACT를 구성한다. mutable path를 다시 읽는
from_pretrained를 사용하지 않고 safetensors bytes를 직접 소비한다.
원본 RGB HWC bytes와 관절 순서·시각·camera binding은 불변 관측에 묶인다.
ACT queue 값은 처음 계산한 관측과 생성 시각을 보존한다. 새로운 frame으로 재표시하지 않는다.
별도 reset은 추론 큐만 지우며 어떤 owner/stop/승격 권한도 생성하지 않는다.

호스트 관련 회귀는 48 passed/1 skipped(torch 부재의 native 모델 시험),
native OMX+registry 회귀는 **73 passed**이다. 독립 리뷰 native OMX **24 passed**,
blocking issue 없음. 초기 source 부재와 queue 길이 입력 거절은 RED 후 구현했다.
native 모델 시험은 실제 safetensors load 후 원본 파일을 변조해도 이미 고정한 계산 결과가
변하지 않고, 새 load는 거절되는 것을 확인했다. 실제 source 모델도 검증했다.

```powershell
python -B -m pytest learning/training/omx/test/ test/architecture/test_platform_parts.py test/architecture/test_safety_separation.py -q -p no:cacheprovider --basetemp X:/DevTemp/act-inference-host-final
X:/DevTemp/rosy-omx-lerobot-044/Scripts/python.exe -B -m pytest learning/training/omx/test/ learning/registry/policy/test/ -q -p no:cacheprovider --basetemp X:/DevTemp/act-inference-native-final
```

## 실제 고정 조건 비교

train5/eval1 원본 Episode, seed42751, 40 optimizer steps, CPU4threads,
chunk_size4·동일 network/정규화를 고정했다. 기존 n_action_steps=4와 새 =1을 비교했다.
새 job은 실제 train/read/save/reload/offline report/Artifact까지 terminal 성공으로 마쳤다.
설정 변경 이외의 training history·normalization·weights bytes가 동일함을 확인했다.

| 조건 | 평가 프레임 | 실제 새 계산 | 과거 관측 queue | 현재 관측 불일치 | 관측/행동 age 위반 | MAE rad | 상수 기준 rad |
|---|---:|---:|---:|---:|---:|---:|---:|
| n_action_steps=4 | 12 | 3 | 9 | 9 | 각각 9 | 0.0296394555 | 0.0059898481 |
| n_action_steps=1 | 12 | 12 | 0 | 0 | 각각 0 | 0.0293680427 | 0.0059898481 |

이는 동일 held-out 12프레임의 controlled comparison이다. 독립 과제 성공 시험이 아니다.
두 설정 모두 nominal joint limit 위반 0이며, 두 모델 모두 상수 기준보다 오차가 커 reject이다.
프레임마다 다시 계산하는 설정은 이 호스트 replay의 시간/관측 문제를 없앴지만 품질을 수용하지 못했다.
모델을 clamp하거나 gate를 낮추어 통과시키지 않았다.

초기 v1 fixed-grid pacing은 decoder latency에 따라 100ms 미만 입력 간격을 허용했다.
독립 리뷰의 지적을 반영해 이전 반환 후 최소 period를 기다리도록 바꿨고, v1과 source를 보존했다.
최종 기본 모델 v2와 step1 v1 모두 실제 최소 입력 수신−이전 반환 간격은 **109ms ≥ 100ms**이다.
보고서 cadence는 minimum-period-after-return이며 실제 owner period 수용이라고 표시하지 않는다.
프레임마다 원래 sim capture/state/wall 시각과 replay monotonic 수신/생성 시각을 분리해 기록했다.

기존 policy revision:
`ede80a29f56e210bf814a4e888d931ed1462c2dc42eb374dfb0c611b0aa6dca9`

새 policy revision:
`4f5f3d148681483a05971a180ffb4d5d501b21adf7f2b5c6e479c88f74c5ff23`

새 Dataset revision:
`4232ddc5fff8d505f18f07f41adfd1f0c44b087fbcebf2ae96fcf5deb70f2f93`

새 Dataset은 6 Episodes/234 file refs profile closure로 등록됐으며 새 정책은
register+reject 두 event, stage unregistered이다. 독립 리뷰가 전체 8-event chain과
두 replay의 22 reader file hashes, 원본 시각·예측 metrics·source SHA를 재검증했다.
기존 정책·거절 이력은 유지했다. 연구용 로컬 원장에 추가했으며 운영 승격은 없다.

공통 weight SHA256:
`99aad120127dd01275ac5b317839fa5f954fe84c302b8beca47407ad8036651e`

## 로컬 evidence와 source

X:/DevTemp/rosy-learning-audit-20261004 아래:

- `omx-act-seed42751-step1/`: 새 실제 job, Dataset/Policy/config/정규화/학습 history/평가와 reader 원본
- `act-inference-replay-v2/`: 기존 모델의 최종 paced replay
- `act-inference-step1-replay-v1/`: 새 모델의 최종 paced replay
- `act-inference-comparison-audit.json`: 동일 weights/history/정규화, source/metrics/원장 재검증
- `policy-registry/`: 기존 기록을 보존한 연구용 immutable snapshots/SQLite

```
act_job.py SHA256 6a2fc05eadfd09832dc45ef78b047c088ce5d5c529ba788985463106776e0371
act_inference.py SHA256 cb2beade6345451a966fafec6c7e1740bb72347daefa4ffeb93a7bf5dd1139b3
act_inference_replay.py SHA256 08b991aab1a5d42e05b344638c8c707a6e04c98ecf9b4aba1dba2c33d5372336
```

## 남은 전체 목표

실제 trusted capture/issuer·scheduler·ROS owner composition, 승인된 설치 binding과 trust,
독립 SIM 과제와 목적에 맞는 시연/품질, durable rollback/독립 stop readback, Pinky CORE/Fleet
receipt 연결, 사람 라벨 검수·새 객체/신호 모델, 모델 PC 전체 job 및 DEVICE/FIELD는 남아 있다.
이 추론 함수는 actuator나 operating authority를 받지 않는다. owner/camera_profile은 아직
연구 선언이며 실제 정책 admission·물리 주행을 실행하지 않았다. 전체 목표 ACTIVE이다.
