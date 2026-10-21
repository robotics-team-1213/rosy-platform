# OMX ACT 오프라인 학습 연구

공식 native recorder/자동 교사 데이터는 [native 실행 안내](../../curation/omx/README.md)의
`native_cycle.py` 경로를 사용한다. byte-bound 검토 분할 → 공식 ACT CLI → 별도 프로세스
model/processor 재적재 → eval 재생을 연결한다. 아래 `act_job.py`의 SIM rad 계약과 혼합하지 않는다.

`act_job.py`는 기존 LeRobot 0.4.4 export의 원본 OMX 시연을 검증하고,
episode 단위 train/eval → ACT 학습 → weights 저장·재독출 → offline 평가 →
공통 DatasetManifest/PolicyArtifact까지 연결한다. 분리된 CPU 환경에서 실행하며
장치나 ROS에 연결하지 않는다. 승격/READY/dispatch를 만들지 않는다.

`deploy/robot/omx/requirements-lerobot-export.txt`의 Python 3.12 CPU 환경을
사용한다. source checkout의 adapter와 foundation을 PYTHONPATH에 둔다.

```text
python learning/training/omx/act_job.py
  --train-export <LeRobot-episode-a-root> <LeRobot-episode-b-root>
  --eval-export <independent-episode-root>
  --out <new-artifact-directory> --steps 40 --seed 42750 --n-action-steps 4
```

`--eval-export`는 여러 독립 에피소드를 받는다. 학습 에피소드만으로 정규화와
학습 chunk를 계산하며 검증 에피소드 사이에는 정책 큐를 초기화한다. 보고서는 전체
오차와 에피소드별 오차를 함께 보존한다. 고정 물체 과제는 train 20/validation 5를
분리하고, 새 SIM 과제 20회의 성공률을 별도로 측정한다.

`--action-representation joint_delta_from_chunk_source_v1`은 원 target에서 chunk 시작
관측 상태를 뺀 이동량을 학습한다. 미래 target도 모두 같은 시작 상태를 기준으로 한다.
추론 시 그 원 상태를 더해 절대 target chunk를 한 번 복원하고 큐에 저장하며, 이후
관측으로 다시 기준을 바꾸지 않는다. 외부 profile과 timestamp·owner 검사는 유지한다.
새 정규화는 `action_transform` 안에 type·mean·std·absolute_baseline을 기록하며
기존 최상위 action_mean/action_std를 두지 않아 구 소비자는 모델 생성 전에 거절한다.
평가 baseline은 원 절대 train target 평균이다. 기본 `absolute`의 정규화 구조는 그대로다.

`--action-representation joint_delta_tanh_from_chunk_source_v1`은 새 checkpoint용으로
ACT linear action head의 역정규화 이동량 `d`에 `0.035*tanh(d/0.035)`를 적용한다.
미분 가능한 같은 activation을 학습·validation·재적재·byte 추론에 설치하며 정규화의
type과 정확한 `max_delta_rad: 0.035`를 hash로 결속한다. 기존 weight key는 유지된다.
원 절대 target을 자르지 않으므로 0.035rad 밖의 정답은 정확히 재현할 수 없다.
chunk 전체는 같은 원 관측 기준이다. 그 뒤 readback 이동까지 제한하지는 못하며 기존
owner 0.04rad 검사는 계속 필요하다. 이 구조 자체가 물체 과제 성공의 증거는 아니다.

상대 표현의 `--state-noise-std-rad 0.02`는 선택한 train 입력에만 관절별 독립
Gaussian 교란을 주는 연구 옵션이다. 전용 RNG(seed+1)를 쓰고 원 절대 target·RGB·
시각을 유지하며 모든 미래 target에서 같은 noisy 시작 상태를 뺀다. 실제 train만으로
정규화를 fit하고 validation·추론에는 교란을 넣지 않는다. 분포·std·seed·관절·적용 범위는
정규화·보고서와 DatasetManifest transformation hash에 결속한다. 교란 입력은 synthetic이며
실제 관측·추가 시연·SIM truth가 아니다. 관절 한계 밖 상태나 0.04rad 초과 이동량도 만들 수
있고 clipping하지 않는다. 실제 recovery 정답이나 native 성공을 보장하지 않는다.
기본값 0에서는 전용 RNG와 추가 augmentation metadata를 만들지 않는다.

`lerobot_export.py --sim-ground-truth <truth.json>`으로 검증한 고정 물체 과제의
원본 증거는 `rosy_sim_truth/`에 복사된다. 학습 snapshot과 공통 Episode에도 같은
bytes를 보존하고 실제 judge를 기록한다. 명시한 증거가 없으면 기존 operator
기록을 유지하며 독립 성공 판정을 만들지 않는다.

Windows 출력은 X에 둔다. 새 출력만 허용하며 실패 시 state/error와 부분 산출물을
보존한다. 학습 중단 시 재개를 지원하지 않는 초기 연구 CLI이므로 새 run 경로를
사용한다. perception 반복 job·장치 배포 경로와 구분한다.

완료/clock/단위/관절·카메라·limits·world/calibration과 원본 provenance를 검증한다.
원래 export를 snapshot해 실제 Parquet/MP4 reader로 학습하고 파일 SHA를
DatasetManifest에 포함한다. train-only 정규화를 사용하며 RGB source/model shape,
resize/scale, 실제 source duration을 기록한다. chunk는 episode 경계를 넘지 않는다.

현재 설정: ACT ResNet18, dim64/head4/encoder1/decoder1, chunk4, VAE off,
pretrained weights 없음, CPU4threads, batch8, AdamW main lr0.0001/backbone lr0.00001.
ACT의 `get_optim_params()`로 backbone과 나머지 parameter 그룹을 나눈다. 저장 ACTConfig의
optimizer_lr는 0.0001, optimizer_lr_backbone은 0.00001, weight_decay는 0.0001이며
offline-report는 실제 optimizer parameter group의 lr/weight_decay/betas/eps와
실행 옵션, gradient clip norm 1.0을 기록한다. 기존 artifact는 덮어쓰지 않는다.
영상 정책을 학습하지만 task/duration 정책을 학습했다고 주장하지 않는다. HOLD/reset/stale는 선언이며
실제 owner 집행은 후속이다. camera_profile은 null을 유지하고 rig fingerprint는
별도로 보존한다.

고정 episode에서 rad MAE·상수 목표 평균 기준·joint limit·목표 다양성을 평가한다.
다양성은 0.001rad bin 최소 3 target cluster의 연구 기준이다. 실물 safety/품질
표준이 아니며 통과해도 offline_only다. independent task success·owner contract·
SIM 실행이 없으면 L0를 등록하지 않는다.

실행 증거: [실제 시연 ACT 학습](../../../docs/validation/omx-act-offline-2026-10-04.md).

## 모델 bytes와 추론 관측 binding

`act_inference.ACTInference(root, policy_revision)`는 pinned PolicyArtifact의 실제
config/weight/정규화 bytes를 검증해 메모리로 snapshot한다. safetensors byte loader를
사용하며 모델 구성 후 mutable 경로를 다시 읽지 않는다. 지원 범위는 CPU/LeRobot0.4.4,
front RGB 한 개와 OMX SIM 절대 관절 목표이다. pretrained 다운로드/temporal ensemble는 없다.

`InferenceObservation`은 ordered joint rad, sequence/수신 시각, camera identity/calibration/
CHW shape와 **HWC 순서의 interleaved RGB uint8 bytes**를 보존한다. 가변 byte buffer는 복사한다.
모든 수신/생성 시각은 owner와 같은 monotonic clock domain이어야 한다. reset은 추론 큐만
지우며 owner HOLD나 local stop을 해제하지 않는다. clock rollback anchor는 reset으로 지우지 않는다.

ACT의 `n_action_steps` 큐를 유지하고, queued action은 **최초 소비 관측과 최초 생성 시각**을
그대로 반환한다. 현재 호출에 새 이미지가 들어와도 큐 값의 관측이라고 주장하지 않는다.
`InferenceResult.candidate_fields()`는 기존 local 후보 필드이며 public wire/실행 권한이 아니다.
호출자가 실제 owner에서 원래 sequence/time/camera frame을 대조하게 해야 한다.
후보는 원frame SHA와 `camera_received_at_ns`를 함께 전달해 동일 RGB의 다른 capture와
구별한다. 큐 출력도 원 수신 시각을 보존한다. owner의 guarded metadata capture와 실제
immutable RGB snapshot을 맞춰야 하며 timestamp 필드 자체가 capture 신뢰를 부여하지 않는다.
공통 `rosy.contracts.learning.inference`는 기존 InferenceObservation/InferenceResult
DTO를 소유하며 이 모듈은 같은 타입을 재수출한다. owner의 명시적
`capture_inference_input(rgb, camera)`는 guarded camera와 원 metadata·RGB의
SHA·크기를 대조하고, 기존 잠금 안에서 원 lease·관절 입력을 고정한다.
학습 쪽 `act_owner_capture.infer_captured`는 이 DTO와 같은 caller clock·policy
revision만 받아 결과를 반환하며 안전 owner 타입을 import하지 않는다.
현재 isolated caller 시험이 잠금 밖 추론과 lease 재검사·PolicyCandidate 구성을
연결한다. 원 관측 재전달·큐 시각 갱신은 없다. 실제 제출·최종 판단은 기존
`session.submit`에 맡긴다. 기본 runtime·명령·issuer·자동 scheduler·HOLD 해제는 없다.
Private SIM caller는 추론 뒤 lease 연속성만 재검사하고 미승인 후보를 반환한다.
추론 중 철회·설치 파일 변경이 생겼어도 후보 반환 자체는 실행 승인이 아니며,
calibration의 전체 검사 또는 기존 `session.submit`의 최종 검사에서 거절해야 한다.
실제 SIM actor는 새 입력 대기를 기존 `require_live()`의 과제 종료·감시 조건에
연결한다. 원본 입력의 freshness와 모든 owner 검사는 유지하며 추론·이미지 저장 후와
제출 전에도 종료를 검사한다. callback 없는 호출의 기존 획득 시간 한도는 유지한다.
실제 trusted capture/issuer·승인된 모델의 ROS 프로세스 결선은 여전히 별도다.

기본 n_action_steps=4는 유지한다. `--n-action-steps 1`은 chunk_size4를 유지하면서
매 관측의 첫 행동만 반환하는 별도 config/평가/PolicyArtifact를 만든다. 허용 값은 1..4이다.
설정을 바꾸어 기존 artifact의 revision이나 거절 이력을 덮어쓰지 않는다.

기본 학습 표본은 `--sampling all_frames`다. 고정 6관절 OMX SIM 물체 과제의
`--sampling command_entry`는 각 원 command/goal 쌍에서 팔 target-state 차이
0.035rad 이하·그리퍼 0.04rad 이하인 첫 원본 frame을 학습 시작점으로 고른다.
독립 SIM 정답을 요구하며 모든 명령에 표본이 없으면 거절한다. 그리퍼의 학습
여유는 보장하지 않는다. 원본 arrays·target·시각·chunk 순서·전체 validation은 유지한다.
선택 indices와 규칙은 `training-index.json` 및 DatasetManifest config SHA에 결속한다.
학습 표본 선택은 실제 최종 readback 승인이나 물체 성공을 보장하지 않는다.

`act_inference_replay.py`는 bound Dataset 파일에 포함된 실제 LeRobot 평가 reader로
모델의 입력/행동/큐 provenance·latency를 새 X artifact에 보존하고 기존 offline metrics를
재현한다. 원래 sim capture/state/wall 시계는 별도 필드로 보존한다.
재생 입력 수신 시각을 원래 센서 수신 시각이라고 표시하지 않는다.

```text
python learning/training/omx/act_inference_replay.py
  --policy-root <ACT-run> --dataset-root <bound-dataset-root>
  --eval-export <bound-reader-input> --policy-revision <canonical-hash>
  --out <new-directory-on-X>
```

이는 numerical/replay 증거이다. 모델 pin은 integrity이며 승격/설치 trust가 아니다.
owner dispatch·독립 SIM 과제·물리 수용을 증명하지 않는다.
고정 seed/data의 4행동/1행동 실제 비교와 남은 품질 거절은
[추론 binding 검증](../../../docs/validation/act-inference-binding-2026-10-04.md)에 기록했다.

## Native OMX ACT 준비

`native-act.example.json`은 공식 LeRobot 0.4.4 CPU smoke 설정이다. [실행 안내](../../curation/omx/README.md)에 따라 검토한 train 경로를 채운다. SIM rad 데이터와 섞지 않는다. 실제 GPU 학습·독립 평가는 별도다.

`native_cycle.py`는 split receipt의 환경 원본·hash·episode 창·요약·split coverage도 시작과
별도 모델 재적재에서 재검증한다. cycle receipt와 offline evaluation에 환경 coverage를
보존한다. 이 값은 sparse 변경 이벤트 집계이며 에피소드 전체 환경 수용률이나 환경별 과제
성공률이 아니다. 환경 이력이 없는 기존 receipt는 unrecorded로 표시한다.

## 학습 결과를 L0 정책으로 등록 (D-793)

`native_cycle.py`의 `cycle-receipt.json`에는 `policy_revision`(모델 파일 목록의 해시), `rig_revision`, `calibration_revision`이 남는다. `register_policy.py`는 이 영수증으로 Fleet에 L0 제안을 올린다. 근거는 영수증의 SHA-256이다. L0은 실행 권한이 아니며 관리자가 `/console/policy`에서 결정한다.

```bash
python learning/training/omx/register_policy.py --cycle <run> --fleet https://<site>:8443 --workcell <id> --dry-run
ROSY_FLEET_TOKEN=<policy-admin token> python learning/training/omx/register_policy.py --cycle <run> --fleet https://<site>:8443 --workcell <id> --confirm
```
