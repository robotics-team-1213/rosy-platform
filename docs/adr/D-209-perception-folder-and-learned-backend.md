## D-209 인식과 학습 백엔드의 자리

**Status:** Accepted (2026-09-25). 이 문서에서 디렉터리를 만들지 않는다. 자리가 정해진 것이다.
잇는 결정:

- [D-199](D-199-camera-perception-contracts-and-backends.md)(Proposed): 계약은 `perception/evidence`와 `perception/frame`이다. 백엔드는 `rule`, `learned_seg`, `learned_det`다.
- [D-205](D-205-real-lane-mission-transition-order.md)(Proposed): P0–P6 전. 장치 주행은 P3과 P5 합격 뒤다.
- D-66, D-136: `core`는 영상 바이트와 OpenCV를 다루지 않는다.
- D-2, D-38, D-208: 최종 `cmd_vel`은 `core`다. 감지 프로파일은 속도를 내지 않는다.
- D-186, D-207: 학습 패키지를 `src/`에 만들지 않는다. 커밋 영상은 `data/teleop/learning/`이다.

**Context:**

1. **차선 코드가 `control/sensing/`에 다른 기하와 섞여 있다.** 라이다, 차체, 도크 태그와 차선·경로 프로토타입이 한 디렉터리다. 선 추출, 좌우 판단, 추종이 한 덩어리면 학습 모델을 끼울 자리가 없다(D-199).
2. **비디오의 경계는 이미 있다.** 캡처와 도로 판단은 `control`이다. `core`는 `camera/preview/compressed`의 JPEG 한 장만 받고, `road/observation`의 사실만 받는다. `nitros`는 이름이 있으나 연결되지 않았다. 관제는 이미지를 받지 않는다.
3. **VLA는 픽셀에서 바퀴로 가려 한다.** 그 한 덩어리는 D-199의 증거 층과 D-2의 명령 층을 동시에 없앤다.
4. **실물과 시뮬의 카메라가 다르다.** 텔레옵 영상에서 실물 렌즈는 약 8°이고 Gazebo는 25°다. 기본 `line` 모드는 그 영상의 22% 프레임에서 벽을 차선으로 보고 조향한다. 시뮬만 본 학습 모델은 그 오류를 더 크게 베낀다.

**Decision:**

1. **몸통의 인식 코드는 `src/core/control/control/sensing/perception/` 하나다.** ROS를 임포트하지 않는다. 프레임과 `CameraProfile`, 영상 좌표 증거, 바닥 투영, 장면 추적, `backend_rule`, `backend_learned`가 여기 있다. 라이다·차체·도크 태그는 이 디렉터리로 옮기지 않는다. 관찰 노드는 프레임을 넣고 사실만 발행한다.
2. **학습 모델은 `backend_learned`다.** VLA, YOLO, SAM2는 새 패키지가 아니다. 출력은 `perception/evidence`다. `cmd_vel`을 내지 않는다. `perception.backend`가 `rule`이 기본이다. 레지스트리에 없는 `model_revision`이거나 실측과 다른 `CameraProfile` revision이면 인식은 닫힌다. 가중치는 `src/`에 두지 않는다.
3. **`core`와 추종기는 픽셀을 읽지 않는다.** `core_features/vision`은 JPEG 한 장이다. `line_follow`는 `PerceptionFrame`만 읽는다. 관제에는 이미지를 보내지 않는다.
4. **학습과 채점은 로봇 이미지 밖이다.** 재생·채점·정답 라벨은 `tools/perception/`이다. 실물 영상은 `data/teleop/learning/`이다. 만든 학습 세트는 `data/perception/`에 두고 저장소에 넣지 않는다. `src/vla`와 `learning/` 패키지는 만들지 않는다.
5. **장치를 맡기기 전에 실물 재생을 통과한다.** 백엔드를 장치의 `perception.backend`로 고르기 전에, 그 백엔드는 D-205의 텔레옵 재생 게이트를 통과한다. Gazebo 25°만 본 모델은 그 선택이 아니다.

**Consequences:** P1이 디렉터리를 만들기 전에는 차선 코드가 지금 자리에 남는다. 그 전이라도 새 인식 코드는 결정 1의 자리로만 넣고, 결정 4의 패키지는 만들지 않는다. 모델을 Pi CPU에서 돌릴지 Hailo에서 돌릴지는 이 결정이 폴더를 바꾸지 않는다(D-205).

**Validation:** 문서 결정이다. 디렉터리를 만드는 커밋은 D-199 계약 시험과 기존 차선 시험을 통과해야 한다. 빈 디렉터리만 있는 커밋은 이 결정의 증거가 아니다.
