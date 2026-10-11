# 관측 파일 산출·readback 구현 계획

Branch: `feat/perception-fitness-pipeline`. 계약: D-673.

기존 불변 store, D-667 snapshot parser와 D-670 관측 함수를 재사용한다. 새 evaluation 모듈은 파일 입력을 결속하고 JSON artifact를 산출·다시 읽는다. CLI는 기존 fitness와 같은 로봇 설정 이전 dispatch를 사용한다.

1. 합성 원본 영상과 fake model로 무정답 산출·계보·hash roundtrip, 의미 및 파일 mutation·보류·overwrite 거절 시험을 추가하고 원격 RED를 확인한다.
2. `road_observation_replay.py`와 `rosy_ml observe`를 구현한다. 입력/모델을 추론 전후 확인하고 255/crop/None을 보존한다. readback 실패를 성공으로 처리하지 않는다.
3. 원격 관련 GREEN/known failures 및 실제 ONNX 합성 실행, 독립 소스 검토, 최신 main 통합을 확인한 뒤 local main에 병합한다. receipt는 X:에 둔다.

영향은 evaluation 모듈·시험·AGENTS, CLI와 관련 시험, ADR/Log다. 기존 paired fitness는 변경하지 않고 내부 snapshot parser를 재사용한다. 다른 필드·ROS consumer·전송 서비스·drive 권한은 추가하지 않는다. 실제 독립 정답·모델 학습·물리 보정·장치 전달 증거는 별도다.
