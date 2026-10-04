# OMX 원카메라 시각 binding과 final safety 검사

2026-10-04. 기반 commit de2b2fa4d12c1205dbf389df633300829c9d9891 이후 변경.
범위는 SOURCE/HOST이며 실제 issuer/ROS owner activation/SIM task/DEVICE/FIELD 증거가 아니다.

## 구현과 회귀

로컬 PolicyCandidate는 ordered camera_received_at_ns를 전달할 수 있다. ACTInference는
immutable 원 RGB SHA와 실제 원 수신 시각을 함께 반환하며 queue에도 새 시각을 붙이지 않는다.
capture_observation은 기존 guard에서 joint/camera metadata를 freeze한다. 실제 pixel bytes는
trusted composition에서 별도로 같은 SHA에 맞춰 제공해야 한다.
guard가 검증한 camera snapshot 집합만 bounded history에 보존하고 exact SHA/시각으로
원frame을 선택한다. source age/produced 시각 인과성을 최종 fence 안에서 다시 검사한다.
기존 timestamp 없는 후보는 strict latest-frame 규칙을 유지한다. 최신입력 freshness는 유지한다.

RED: 신규 camera 경로13건, ACT 필드2건 실패 후 구현했다.
독립 리뷰가 reentrant provider의 HOLD swallow 및 fence.trip 후 dispatch를 재현했다.
submit/capture/renew HOLD RED3와 실제 LocalStopRequest stop RED1 후 수정했다.
renew의 마지막 provider 뒤 stop 검사 누락 RED1와 final stop-store read 지연 뒤 lease 만료
RED1도 재현·수정했다. provider 이후 HOLD/pinned config/정확한 epoch·generation fence를 확인하고
stop-store read 이후 clock/lease/freshness를 검사한다. renewal은 기존 lease와 새 lease가
모두 유효할 때만 교체하고 오류 시 active own-command cancel을 요청한다.

실행:

```powershell
python -B -m pytest middleware/execution/local/test/ learning/training/omx/test/test_act_inference.py test/architecture/test_safety_separation.py -q -p no:cacheprovider --basetemp=X:/DevTemp/rosy-camera-source-final --tb=short
```

110 passed. 별도 native torch/LeRobot 실제 safetensors 테스트16 passed.
독립 focused86 passed와 renewal stale/rollback/owner 변경 scratch 검사 후 D-430 source safety 승인.
cancel 요청은 독립 stopped proof가 아니다.

검토 SHA256:
- omx_policy.py: f75bfe08c3110ba2f3fbae3e2093def7a0e7e7fbd45c38c56e6da0963ee2d12c
- act_inference.py: bb087a99a83f6a9575ef27e00b529eeec42a1b103a8f80855b3c92e1f2c292bd

rosy-execution-local0.1.4 wheel은 X: source copy에서 빌드하고 session source bytes 일치를 확인했다.
wheel SHA256 21261ccbaf4eb1bfd7d92a34e877a42e3bcba6e8ef42e9ba4bed60e3bdebda27.

## 실제 ACT HOST replay

기존 step1 정책/동일 bound Dataset/고정12frame reader로 실제 ACT 추론과 candidate_fields를 실행했다.
출력 X:/DevTemp/rosy-learning-audit-20261004/act-camera-source-step1-replay-v1/.
source에는 실제 추론/replay와 관측용 subclass 스크립트를 보존했다. subclass는 numerical 결과를
변경하지 않고 원candidate 필드만 수집했다. 12개 모두 SHA와 camera receipt 시각이 소비한 원관측과 일치했다.

MAE .02936804271834803rad / 상수 기준 .005989848105380092rad로 기존 reject를 재현했다.
12 computations, queue0/mismatch0/action-age violation0. 최소 입력 주기125ms≥100ms.
이번 HOST 실행은 observation-age violation10/12로50ms 예산을 만족하지 못했다.
이를 통과로 표시하거나 기준을 늘리지 않았다. 이전 실행과의 부하/계측 조건 차이를 고려해야 하며
새 timestamp 필드가 이 지연의 원인이라고 단정하지 않는다.

독립 reviewer가12candidate의 SHA/시각/sequence/생성시각/positions를 consumed source와 대조하고,
원 video를 decode해12RGB SHA를 재생성했다. 22reader 파일과 현재 source snapshot hash,
모든 age/cadence/MAE 집계가 일치했다. observation age는31~656ms였으며50ms 통과로 판단하지 않았다.
독립 검증은 readback/decode이며 추론을 다시 실행한 것은 아니다.

## 남은 목표

기존 actual SIM50ms 타이밍 실패와 모델 품질 거절은 그대로 남아 있다.
guarded metadata와 실제 immutable RGB snapshot을 연결하는 trusted capture/issuer/scheduler,
실제 owner/ROS composition·독립 과제와 stop readback, 설치/승격 trust, Fleet receipt,
Pinky CORE/shadow/rollback, 사람 영상 라벨 검수와 새 모델 학습, model PC 전체 job,
DEVICE/FIELD는 미완료이다. source/host positive fixture가 이를 승인하지 않는다.
push/merge/deploy/물리 동작 또는 operator HOLD 해제를 수행하지 않았다.
