# 저장된 OMX 시연의 ACT 학습·재로딩 검증

2026-10-04 KST. 저장된 실제 Gazebo 녹화 export를 사용한 CPU 연구 실행이다.
새 Gazebo 실행이나 장치 제어, 정책 승격을 완료한 증거는 아니다.

## 입력과 실행

기존 LeRobot 0.4.4 export의 완료된 3개 Episode만 사용했다. train은
`e404b518-8ea3-44c3-aaee-c2083477d75a` 15프레임과
`f8f9c67c-0051-4074-b2d1-8d6d234ecf3d` 11프레임, 고정 eval은
`91723c28-d02c-463e-9b4d-6f65f6a2b614` 12프레임이다. 총 38프레임이며
미완료 기록은 제외했다. 원본 기록의 증거는
[기존 Gazebo export 검증](omx-demonstration-lerobot-2026-10-01/README.md)에 있다.

`learning/training/omx/act_job.py`는 입력 export를 새 출력 아래로 복사하고
실제 LeRobotDataset reader로 Parquet/영상·시계를 확인한다. 원본/공통 Episode와
118개 입력 파일을 DatasetManifest로 묶었다. 입력과 출력은 X 드라이브에 있다.

Python 3.12.14, torch 2.7.1+cpu, torchvision 0.22.1+cpu, LeRobot 0.4.4의
기존 환경에서 seed 42750, CPU 4 threads, batch 8, 40 steps를 실행했다.
ACT는 ResNet18(pretrained 없음), RGB 64×64, 6 joint state/action,
dimension 64, heads 4, feed-forward 256, encoder/decoder 각 1층,
chunk/action steps 4, VAE off, dropout 0이다. AdamW lr 0.001,
weight decay 0.0001, gradient clipping 1을 사용했다.
정규화 통계는 train에서만 계산했고 episode 경계를 넘어 chunk를 만들지 않았다.

## 실제 결과

| 고정 eval 12프레임 | 결과 |
|---|---:|
| ACT joint target MAE | 0.0162095522 rad |
| train 평균 목표를 출력하는 상수 기준 MAE | 0.0000806680 rad |
| joint limit 위반 | 0 |
| 0.001 rad 단위 목표 cluster 수 | 2 |
| 저장·재로딩 후 추론 일치 | 통과 |
| offline verdict | reject |

시연마다 목표가 거의 고정되어 다양성 조건(최소 3 clusters)을 충족하지 못했고,
ACT가 상수 기준보다 나빴다. 따라서 연구 산출물만 보존하고 L0 승격도 하지 않았다.
operator 원본의 task 표시는 독립 task 성공 판정이 아니다. ACT가 실제 SIM에서
과제를 수행했는지, owner lease/stale/HOLD가 작동하는지는 아직 검증하지 않았다.
torchcodec fallback과 torchvision video deprecation 경고가 있었지만 프로세스는
exit 0으로 완료했고 가중치 재독출·추론을 별도로 확인했다.

## 재현 산출물

최종 실행은 `X:/DevTemp/rosy-learning-audit-20261004/omx-act-seed42750-v2/`에 있다.
첫 실행은 입력 전체 snapshot 추가 전 버전으로 별도 보존했다. 두 실행의
동일 seed 결과는 같았다. 최종 source SHA와 revision은 다음과 같다.

- act_job.py SHA: `2bc20ec0eef2cda4680cf97991a55f81b1d4a61b96bceba7ccccdb0557b36aa6`
- DatasetManifest: `0fddcf970a3d0b9bcfb72e12293a272c9e7f9227ead95e4e45c1421ac8edb0da`
- PolicyArtifact: `a471a20a22e6e92d0e7e53c6f8cfe0ff9b4f13d69c366b7d446692ee6270d990`
- model.safetensors SHA: `9631bbb0bb936b3e509571a0a9feccc15d5ef0c55a69c3b692ad4175f090647d`
- offline-report.json SHA: `8e66c2d60af15df61e4306e8cb48d899765672ea218f82821d3c87e4fab77eea`

PolicyArtifact는 unregistered 연구 owner와 SIM world binding을 명시하며
camera profile의 미확인 값은 null로 보존한다. 계약 0.1.1은 카메라 rig의
identity/calibration SHA/원본·모델 shape/RGB scale을 기록하고,
camera profile 없는 영상 정책의 L1 이상 승격을 거절한다. 이 검사는 metadata
무결성 검사이며 실행 권한이나 보고서 진위를 보증하지 않는다. D-449는 Proposed다.

## 검증 범위와 다음 단계

영향 범위의 학습 helper·공통 계약·OMX 변환/export·구조 검사는
78 passed/1 skipped였다. skip은 호스트 LeRobot 부재이며 위 native 실행은
별도 설치된 기존 LeRobot 환경에서 실제 reader와 ACT를 실행했다.

문서 배치/harness 검사는 65 passed, 기존 26 warnings였다. generate 완료,
lint 0 errors/26 warnings, staged whitespace 검사 통과.
공통 계약 0.1.1 wheel은 X 복사본에서 빌드·별도 target 설치 후 isolated import했고
runtime dependencies 없음·torch 미로드를 확인했다. wheel SHA는
`f38632e5e62515d0be8c1194ecf63ff7765a76b907ce8f6c8dcc8b58ddaa87bf`다.

다양한 초기 관절/목표·성공/실패 시연을 추가하고 고정 eval을 유지해야 한다.
독립 SIM task 판정, 실행 owner admission/lease/reset/HOLD,
승격 원장·rollback, Pinky 정책 및 Fleet 결과 연결은 전체 목표의 잔여 작업이다.
주행 영상의 사람 라벨 검수와 모델 PC recording-job 전체 실행도 남아 있다.
이 기록으로 장치/현장 수용이나 전체 목표 완료를 선언하지 않는다.
