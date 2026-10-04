# OMX 모방학습 첫 고리 실행 계획

D-449의 공통 Episode/PolicyArtifact 초안을 실제 보존된 Gazebo 시연에 연결한다.
저장된 완료 시연 3개(15/11/12프레임), 원본과 LeRobot export를 유지한다.
모델 PC 인증과 독립적으로 기존 X의 Python 3.12/LeRobot 0.4.4 CPU venv를 사용한다.

1. 원본 profile과 각 stream SHA를 검증하고 공통 Episode로 변환한다. 완료된
   시연만 입력에 포함하고 episode 단위로 train 2개/eval 1개를 고정한다.
   joint order·limits·camera info·source size·fps·calibration/world binding을 비교한다.
2. LeRobot ACT 구현을 직접 사용한다. RGB resize/scale과 train-only state/action
   정규화를 명시한다. CPU 소형 transformer·chunk 4·VAE off·pretrained weights 없음으로
   연결을 검증한다. 세션 경계를 넘는 action chunk는 만들지 않는다. 정규화·config·
   weights·common DatasetManifest·offline report를 실제 파일 SHA로 묶는다.
3. holdout episode에서 rad MAE·상수 평균 목표 baseline·목표 다양성·joint limits를
   함께 평가한다. 같은 +0.02rad jog만 있어 다양한 과제 학습 수용은 불가능하다.
   평가가 부족하면 연구 artifact와 거절 근거만 남기고 L0 승격/owner 실행을 만들지 않는다.
   camera_profile null은 보존하고 source camera info/rig는 별도 binding으로 기록한다.

ACT 학습·저장·재로딩·offline 추론을 실제 실행한다. 이는 fresh Gazebo 정책 제어,
독립 과제 판정, 실물 owner 수용을 대신하지 않는다. 이후 SIM 환경의 다양한
시연/행동과 independent task evaluator를 확보해 owner 후보 실행을 연결한다.
