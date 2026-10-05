# OMX ACT 오프라인 학습 연구

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

Windows 출력은 X에 둔다. 새 출력만 허용하며 실패 시 state/error와 부분 산출물을
보존한다. 학습 중단 시 재개를 지원하지 않는 초기 연구 CLI이므로 새 run 경로를
사용한다. perception 반복 job·장치 배포 경로와 구분한다.

완료/clock/단위/관절·카메라·limits·world/calibration과 원본 provenance를 검증한다.
원래 export를 snapshot해 실제 Parquet/MP4 reader로 학습하고 파일 SHA를
DatasetManifest에 포함한다. train-only 정규화를 사용하며 RGB source/model shape,
resize/scale, 실제 source duration을 기록한다. chunk는 episode 경계를 넘지 않는다.

현재 설정: ACT ResNet18, dim64/head4/encoder1/decoder1, chunk4, VAE off,
pretrained weights 없음, CPU4threads, batch8, AdamW lr0.001.
모든 policy parameter를 하나의 optimizer group으로 학습한다. 저장 ACTConfig의
optimizer_lr/optimizer_lr_backbone은 둘 다 0.001, weight_decay는 0.0001이며
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
`act_owner_capture.infer_for_owner`는 명시적으로 주입한 기존 owner session과
ACTInference 사이의 private 입력 composition이다. `CapturedRGB`의 원 metadata와
bytes가 guarded camera에 정확히 일치해야 하고, 동일 clock·설치 policy·lease를
검사한다. 원 관절 관측을 재전달하거나 큐 시각을 갱신하지 않는다. 추론은 owner
잠금 밖에서 실행하며 반환 candidate의 실제 제출·최종 권한 판단은 기존
`session.submit`에 맡긴다. adapter가 명령·issuer·자동 scheduler·HOLD 해제를 만들지 않는다.
실제 trusted capture/issuer·승인된 모델의 ROS 프로세스 결선은 여전히 별도다.

기본 n_action_steps=4는 유지한다. `--n-action-steps 1`은 chunk_size4를 유지하면서
매 관측의 첫 행동만 반환하는 별도 config/평가/PolicyArtifact를 만든다. 허용 값은 1..4이다.
설정을 바꾸어 기존 artifact의 revision이나 거절 이력을 덮어쓰지 않는다.

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
