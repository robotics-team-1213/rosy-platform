# Pinky 녹화 속도 모델 비교

`comparison_job.py`는 원본 MCAP 검증을 직접 실행한 뒤 녹화 2세션에서 학습하고
독립 1세션에서 평가한다. 같은 Dataset/Episode/session 이름 또는 원본 MCAP 해시가
겹치면 거부한다. 세션별 무작위 프레임 분리를 사용하지 않는다.

```text
python learning/training/pinky/comparison_job.py
  --train <immutable-dataset-a> <immutable-dataset-b>
  --eval <immutable-dataset-c> --out <new-directory-on-X>
  --steps 40 --seed 42760 --stride 4
```

별도 Python 3.12 CPU 환경의 torch 2.7.1, numpy 2.2.6, OpenCV 4.12.0.88과
`learning/curation/pinky/requirements-raw.txt`를 사용한다. 계약 wheel이나 로봇에는
이 의존성을 설치하지 않는다. 새 출력만 허용하며 실패 상태와 부분 산출물을 남긴다.

상수 train 평균·zero 기준과 8×6 RGB ridge(고정 penalty 10), 64×48 작은 CNN을
같은 평가 프레임으로 비교한다. train-only action 평균/std, 선택 원본 frame index,
누락 cmd 수, source revision/MCAP hashes, 실제 모델 파일·재로딩 추론·단위별 MAE를
보존한다. 전체·moving·stop 각각 m/s와 rad/s를 보고하며 두 단위를 평균하지 않는다.
moving 기준은 기록된 |v| > 0.01m/s 또는 |w| > 0.05rad/s다. 실제 움직임 판정은 아니다.

목표는 expert intent가 아닌 기록된 CORE 최종 출력이다. 카메라 보정/identity,
pixel provenance, owner 집행, 독립 과제 결과는 확인되지 않았다. calibration SHA를
만들지 않으며 모든 비교 결과는 `research_only`다.
고정 eval을 보고 seed/steps/모델을 튜닝하지 않는다. policy qualification·READY·승격·
로봇 명령이나 Fleet 결과를 만들지 않는다. 출력 경로·device 정보는 private evidence다.

`artifact_export.py <comparison-run> <new-output-on-X> --model tiny_cnn|rgb_ridge`는
같은 모델의 공통 연구 PolicyArtifact를 내보낸다. 파일 목록과 dataset closure,
원본 평가 target·train-only 정규화·metrics를 재검산하고 원본 MCAP도 직접 검증한다.
저장된 모델을 실제 eval 영상에 다시 실행해 예전 예측 NPZ와 비교한다.
예전 pass 보고서나 해시를 다시 맞춘 다른 weights로 검증을 우회할 수 없다.
복사한 파일의 원본 SHA도 재검사한다. 새 raw-reverification 보고서는 산출물에 포함된다.

artifact의 CameraProfile/calibration은 null이며 identity는 declared front topic이다.
device profile은 보존한 source YAML 해시와 명목 limits(±0.20m/s·±0.80rad/s),
controller/envelope는 unregistered 연구 binding이다. period125ms·observation250ms·
action125ms budgets도 연구 선언이며 runtime 집행 측정값이 아니다.
정책 인터페이스는 base_velocity_candidate이고 학습 target은 기록된 CORE 최종 속도다.
등록/거절 증거는 유지하지만 이 선언만으로 cmd_vel·stale/HOLD 집행을 켜지 않는다.
