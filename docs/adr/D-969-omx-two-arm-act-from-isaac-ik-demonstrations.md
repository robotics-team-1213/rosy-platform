## D-969 OMX 두 팔 적층의 첫 학습 정책은 Isaac 정답 IK 시연으로 학습한 ACT 두 팔이다

**Status:** Accepted (2026-11-03, 사용자 결정: "이제 학습된 모델들을 사용할 시간", "로봇암 2개 쓰는걸 … 학습된 모델로 이제 나와야하는데 파이프라인을 시작해야해", 첫 모델 선택 「ACT 두 팔 먼저」, "계획잡고 하고 adr에도 정확하게 기록해서 해"). 구조와 순서의 결정이다. 녹화·내보내기·학습·평가 코드와 학습 결과, 실물 수용은 이 결정 시점에 **없다**.

잇는 결정: [D-947](D-947-omx-palletizing-sim-models-and-claim-scope.md)(시뮬레이터 역할·주장 범위, 이 결정이 학습 범위를 넓힌다) · [D-864](D-864-d854-units-trajectory-and-simulator-roles.md)(Isaac은 학습 데이터, SmolVLA 첫 VLA) · [D-911](D-911-omx-native-reviewed-operating-envelope.md)(실물 작업 범위) · [D-858](D-858-omx-real-device-path-device-core-absorption.md)(실물 팔 경로)

### Context

- 2026-11-03까지 두 팔 컨테이너 적층은 Isaac에서 **정답 위치를 아는 IK 스크립트**로만 돌았다(배 판, 조 v2.1, 16 g, seed 42 9/9). 학습 정책은 없다. 예전 BC v0·rl3 놓기 보정은 옛 손가락과 15 mm 놓기 높이를 배워 재사용할 수 없다(D-947).
- D-947은 학습을 「같은 카메라 추정 오차 → 새 그리퍼 시연으로 놓기 보정 재학습」으로 좁게 두었다. 사용자는 두 팔 적층 동작 자체를 학습 모델로 내기로 했다.
- 같은 날 시뮬레이션 카메라를 실물 top·side와 맞췄다(돌기 평균 1.1 px, [셀 실측 기록](../validation/omx-cell-survey-2026-11-03/result.md)). 실물과 같은 시점의 영상을 학습 입력으로 쓸 수 있다.
- 저장소에 있는 것(main 2026-11-03):
  - 두 팔 ACT 학습 경로 `learning/training/omx/experiment_native.py` → `native_cycle.py`(공식 ACT CLI). 입력은 `arm_a` 다음 `arm_b`, 팔마다 여섯 관절(`native_review.JOINTS`), 몸 관절 `normalized_-100_100`, 그리퍼 `normalized_0_100`. `source_mode`는 `leader_native` 또는 `scripted_teacher`.
  - LeRobot 0.4.4 내보내기 `learning/curation/omx/lerobot_export.py`(한 팔 reach용 `sim_batch_export.py`).
  - 실물 녹화 `deploy/robot/omx/record_session.py`는 LeRobot 데이터셋을 쓴다.
- 없는 것:
  - Isaac 두 팔 시연 녹화. `container_recording.py`는 관찰 카메라와 arm 0의 관절 5개만 남긴다.
  - Isaac 실행 → 두 팔 데이터셋 내보내기.
  - 학습 정책을 Isaac에서 폐루프로 돌리는 실행기.

### Decision

1. **첫 모델은 ACT 두 팔이다.**
   - 입력: 두 팔 상태 12개와 top·side 실물 시점 영상(640×480)이다.
   - 출력: 두 팔 관절 목표 12개(chunk)다.
   - 같은 데이터셋을 뒤에 SmolVLA(D-864)에 다시 쓴다. SmolVLA는 이 결정에 들어 있지 않다.
2. **시연은 Isaac 정답 IK 교사가 만든다** (`source_mode='scripted_teacher'`).
   - 교사는 D-947 범위에서 9/9를 통과한 케이스만 쓴다.
   - 실패한 시행은 데이터셋에 넣지 않고 보고서에 남긴다.
3. **단위는 실물 팔과 같다.**
   - 몸 관절은 `normalized_-100_100`, 그리퍼는 `normalized_0_100`이다.
   - 팔 순서는 `arm_a`(fixture arm 0, y −), `arm_b`(arm 1)다.
   - 그래서 시뮬레이션으로 학습한 정책을 실물 `bi_omx_follower` 경로에 그대로 넣을 수 있다.
   - 이는 D-864(Proposed)의 SIM 데이터셋 공통 단위 `ros_joint_rad`와 다르다. 이 정책에서는 기존 두 팔 학습 경로가 받는 실물 단위가 우선이다.
   - 몸 관절 변환은 실물 배치가 쓰는 `grasp_planner.norm_to_rad`의 역이다.
   - 시뮬레이션 손가락 각을 그리퍼 0~100으로 옮기는 대응은 아직 재지 않았다. 처음에는 조 v2.1 메시의 닫힘·열림 각을 0과 100에 둔 선형 대응을 쓰고, `assumed`로 표시한다.
4. **에피소드는 컨테이너 하나다.**
   - 컨테이너 하나의 벨트 집기부터 정렬, 적층 놓기, 홈 복귀까지가 한 에피소드다.
   - 한 시행(9개)은 에피소드 9개가 된다.
   - 쉬는 팔도 상태에 포함된다. 두 팔이 함께 기록된다.
5. **녹화는 옵트인이다.**
   - fixture 키 하나로 켠다. 기존 케이스의 보고서·영상·판정은 바뀌지 않는다.
   - 기록 주기는 10 Hz다. 기존 녹화와 같은 `every_control_ticks=12`이고, 물리 120 Hz에 맞춘다.
6. **순서**는 아래와 같다. 각 단계는 앞 단계의 확인 기준을 넘긴 뒤에 시작한다.
   1. Isaac 시연 녹화
   2. LeRobot 두 팔 데이터셋 내보내기(`experiment_native`가 읽음)
   3. 데이터 생산
      - seed, 벨트 투입 흔들기, 놓기 오프셋을 바꾼다.
      - 첫 목표는 20시행, 에피소드 180개다.
      - 야간 재부팅 90분 보호 안에서 돌린다.
   4. 모델 PC에서 ACT 학습
   5. Isaac 폐루프 평가: 같은 seed에서 IK 결과와 놓기 수·D-947 판정을 비교한다.
   6. 실물 arm_b 단독(D-911 범위)과 실물 녹화 섞기
   **보강 (2026-11-03, 같은 날):** 학습은 두 경로로 나눈다.
   - **연기 시험:** 앱용 `experiment_train.py`는 ACT를 연기 시험용으로 작게 만든다(chunk 4, 폭 64, 층 1, 64×64 영상, 사전학습 백본 없음). 이 경로는 파이프라인이 끝까지 도는지만 본다. 데이터는 `isaac_demo_export.py`의 `.npz` 출력이다.
   - **실제 학습:** 같은 시연을 `isaac_demo_export.py --lerobot`로 LeRobot 0.4.4 데이터셋(`bi_omx_follower`, 320×240)으로 내보낸다. 그다음 공식 `lerobot-train` ACT 기본 설정으로 학습한다.
   - 모델 PC 학습 환경은 `requirements-lerobot-export.txt`와 같은 버전 고정이고, torch만 CUDA(cu128)로 바꾼다.

7. **주장 범위.**
   - 5단계 통과는 「Isaac에서 이 케이스·seed로 학습 정책이 놓았다」까지만 뜻한다.
   - 실물 수용은 6단계와 D-911을 따른다.
   - 학습 정책은 실물 팔 경로(D-858 owner, D-911 가드)를 우회하지 않는다.

### Consequences

- D-947의 학습 범위가 넓어진다. D-947의 추정 오차와 놓기 보정 단계는 그대로 남는다. 그 산출물은 이 정책의 평가 조건(추정 오차를 넣은 투입)으로도 쓴다.
- 시뮬레이션 데이터가 실물 단위로 만들어지므로 그리퍼 대응이 중요해진다. 실물 그리퍼 0~100과 조 간격의 측정이 사람 몫으로 생긴다(캘리퍼나 실물 관측).
- 팔 받침이 CAD 값인 케이스로 데이터를 만들면, 실물(실측 받침)과 기하가 어긋난다. 실측 받침 케이스가 9/9를 넘기면 그 케이스를 데이터 생산 기본으로 바꾼다.
- 데이터 생산은 GPU 한 자리(D-958)를 오래 쓴다. 다른 GPU 작업과 시간을 나눈다.

### Alternatives

- **SmolVLA 먼저(D-864):** 텍스트 지시가 되지만, 두 팔 학습 작업이 저장소에 없고 추론 지연(p99 208 ms)이 남아 있다. ACT 뒤에 같은 데이터로 한다.
- **놓기 보정 BC만(D-947 3단계):** 가장 작지만 두 팔 동작은 계속 IK다. 사용자 요구(두 팔 동작을 학습 모델로)를 채우지 못한다.
- **SIM 데이터를 `ros_joint_rad`로:** D-864 방향이지만 기존 두 팔 ACT 경로와 실물 녹화가 실물 단위라 변환 계층이 하나 더 생긴다.
