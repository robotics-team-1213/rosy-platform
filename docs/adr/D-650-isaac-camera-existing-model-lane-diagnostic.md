## D-650 Isaac 카메라 차선 진단은 기존 인식 모델과 CORE 차선 추종을 재사용한다

**Status:** Accepted (2026-10-11, 사용자 카메라 차선·기존 모델·강화학습 연결 요청; 구현·실행·운영 승인은 별도)

### Context

D-638의 성공한 한 대 진단은 odom·맵 경로를 사용했다. 사용자는 카메라 차선 인식과 기존 line_follow에 학습을 붙이고 이미 만든 인식 모델도 함께 사용하도록 지정했다. 현재 완주 영상이나 저장 Q 표를 카메라 인식 기반 수용으로 바꿔 부를 수 없다.

### Decision

1. 별도 한 대 native headless 진단에서만 실제 전방 카메라 RGBA를 BGR로 변환해 기존 `LaneSegModel`에 넣는다. 기존 crop·정규화·manifest·파일 SHA·warm-up 검사를 재사용하고 revision과 모델 SHA를 고정한다. 실제 장치 pointer·운영 기본값·intake 판정은 바꾸지 않는다. TEST/candidate 모델의 실험 사용은 승격이 아니다.
2. 기존 drivable/차선·횡단보도 출력과 `LearnedPaintWorker`, `LaneKeeper`, `DrivableSteer`의 keep 처리 및 `LineFollowManager`를 연결한다. 보이는 흰 화소 전체나 맵 정답 경로로 모델 관측을 대체하지 않는다. 모델 추론 실패·무효 영상·오래되거나 역행하는 frame은 진단에서 정지하며 규칙 fallback을 학습 모델 성공으로 집계하지 않는다.
3. 강화학습은 카메라 error·confidence bin으로 yaw gain을 고른다. gain은 simulation 전용 구성에서 기존 manager tick **이전**에 제한된 `steering_gain`에 적용한다. body sweep·authority·crosswalk gate 이후 명령에 gain을 곱하지 않는다. CORE 최종 슬롯·`cmd_vel_cycle`, epoch·TTL·명령 제한·reset 전 실제 정지를 유지한다. 제품 manager와 외부 API에는 새 설정 경로를 만들지 않는다.
4. 새 정책은 관측 schema와 인식 모델 revision/SHA를 함께 저장하고 평가 시 대조한다. D-638의 경로 관측 Q 표는 카메라 정책으로 복원하지 않는다. 실측 pose는 reward·순서별 완주·충돌·stop 판정과 기존 odom 보조에만 사용한다. 맵·경로 지시가 조향에 사용되면 별도로 기록하고 카메라만의 주행이라고 부르지 않는다.
5. 실제 camera 입력·raw 추론/관측·전후 명령·물리 pose·학습 업데이트·고정 정책·native 영상·종료를 남긴다. 소스/원격 단위 시험·native 주행·정식 intake·운영/실물 수용은 독립이다. model의 wall role 유무와 흰 벽/차선 오인을 직접 확인한다.
6. 처음에는 학습 없는 한 대 카메라 baseline을 검증한다. 차선 상실·low light·stale·불명 통행권의 zero를 원격 시험한 뒤 bounded Isaac과 학습을 순서대로 실행한다. IR/LiDAR/Fleet/신호/횡단보도 안전 연결이 빠진 단계는 해당 수용을 주장하지 않는다. 두 대 목표는 기존 별도 Fleet 계획의 gate를 따라 이어간다.

### Consequences

기존 모델과 실제 조향 소스를 시험할 수 있다. 실사 학습 모델의 Isaac 영상 적합성은 미확인이며 camera baseline 실패를 경로 추종으로 우회해 성공시키지 않는다. D-606 Isaac Lab·ROS-SIM HOLD와 D-638 기존 결과는 유지한다.

**Related:** D-205, D-356, D-408, D-517, D-573, D-588, D-597, D-606, D-638.
