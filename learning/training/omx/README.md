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
  --out <new-artifact-directory> --steps 40 --seed 42750
```

Windows 출력은 X에 둔다. 새 출력만 허용하며 실패 시 state/error와 부분 산출물을
보존한다. 학습 중단 시 재개를 지원하지 않는 초기 연구 CLI이므로 새 run 경로를
사용한다. perception 반복 job·장치 배포 경로와 구분한다.

완료/clock/단위/관절·카메라·limits·world/calibration과 원본 provenance를 검증한다.
원래 export를 snapshot해 실제 Parquet/MP4 reader로 학습하고 파일 SHA를
DatasetManifest에 포함한다. train-only 정규화를 사용하며 RGB source/model shape,
resize/scale, 실제 source duration을 기록한다. chunk는 episode 경계를 넘지 않는다.

현재 설정: ACT ResNet18, dim64/head4/encoder1/decoder1, chunk4, VAE off,
pretrained weights 없음, CPU4threads, batch8, AdamW lr0.001. 영상 정책을 학습하지만
task/duration 정책을 학습했다고 주장하지 않는다. HOLD/reset/stale는 선언이며
실제 owner 집행은 후속이다. camera_profile은 null을 유지하고 rig fingerprint는
별도로 보존한다.

고정 episode에서 rad MAE·상수 목표 평균 기준·joint limit·목표 다양성을 평가한다.
다양성은 0.001rad bin 최소 3 target cluster의 연구 기준이다. 실물 safety/품질
표준이 아니며 통과해도 offline_only다. independent task success·owner contract·
SIM 실행이 없으면 L0를 등록하지 않는다.

실행 증거: [실제 시연 ACT 학습](../../../docs/validation/omx-act-offline-2026-10-04.md).
