## D-199 카메라 인식은 두 층의 고정 계약과 교체 가능한 백엔드로 나눈다 — 규칙 기반으로 시작하고 학습 모델은 같은 자리에 끼운다

**Status:** Proposed (2026-09-24). 설계 [2026-09-24-perception-architecture-design.md](../plans/2026-09-24-perception-architecture-design.md)는
사용자 검토 대기다. 잇는 결정:

- D-66, D-136: CORE는 영상 바이트와 OpenCV를 다루지 않는다.
- D-137: YOLO는 자문역이다. `DetectionEvidence`와 `ModelRegistry`가 보조 검출 계약이다.
- D-143: 차선 관측(`line/observation`)은 증거다.
- D-162: 장면 문맥은 프로필 revision이 맞지 않으면 닫힌다.

**Context:**

1. **시뮬레이션에서도 인식이 약하다.** 2026-09-23 Gazebo route_ab 순회에서 CORE가 받은 인식은 BOTH 12% · ONE 73% ·
   MEMORY 16%였다. 원인은 둘이다.
   - `lane_bev.py`의 좌우 배정이 기억을 반대쪽 선에 붙여 라벨이 뒤바뀐다.
   - 왼쪽 선을 혼자 새로 잡는 경로가 없다.
2. **실물 카메라는 시뮬과 다르다.** 수동 주행 영상(`data/teleop/learning/`)에서 추정한 값이다.
   - 기울기 약 8°(Gazebo 25°), 좌우 화각 59°(fx 약 281.6), 렌즈 높이 약 67 mm
   - 흰 벽이 테이프보다 밝은 프레임이 67%다. 바닥은 카펫이다.
   - 매트 비율이 CAD와 약 10% 다르다. 실측값은 대기 중이다.
3. **현재 인식은 실물 영상에서 주행할 수 없다.** 7개 영상 4981프레임을 실물 프로필로 재생했다
   ([기준선](../validation/perception-real-video/2026-09-24/baseline.md), REAL VIDEO REPLAY, host only; DEVICE: NOT RUN).
   - `centre` 모드: BOTH 13% · ONE 36% · MEMORY 14% · STOP 37%
   - 장치 기본 `line` 모드는 22%의 프레임에서 벽 픽셀로 조향했다.
   - 벽을 BOTH, 신뢰도 1.00으로 보고한 프레임이 있다.
   - `road.py`는 89.5%의 프레임에서 정지선을 보고한다.
   - 주요 실패: 흰 벽이 고정 문턱 180을 넘는다. 169–201의 실물 테이프가 문턱 180에서 조각난다. 59° 화각과 8° 기울기에서는
     근거리에 차선 쌍이 들어오지 않는다.
4. **학습 모델을 끼울 자리가 없다.** 선 추출, 좌우 판단, 추종이 한 덩어리다. 저장소에는 모델이 없고 D-137의 보조
   검출 계약만 있다.
5. **사용자 결정(2026-09-24).**
   - 인식 대상은 차선과 장면 요소(코너, 교차로 분기, 횡단보도, 정지선, 주차 마커)다.
   - 먼저 인식하고 표시한다. 주행 반영은 단계별로 한다.
   - 지금은 규칙 기반이다. 나중에 학습 모델(YOLO, SAM2 등)을 같은 자리에 끼울 수 있어야 한다.
   - 학습 데이터는 Gazebo 참값으로 자동 라벨링해 모은다.
   - 실물 카메라는 거의 수평이 맞다. 시뮬을 실물에 맞춘다.
   - 트랙 치수는 사용자가 잰 실물 매트를 따른다.

**Decision:**

1. **계약은 두 층이다.**
   - `perception/evidence`(`rosy.perception.evidence/1`): 영상 좌표 증거. D-137 `DetectionEvidence`를 넓혀 masks,
     polylines, detections를 담는다. 클래스는 닫힌 목록이다. 모르는 클래스와 `ModelRegistry`에 없는
     `model_revision`은 버린다. 0.3 s보다 오래된 증거는 무효다.
   - `perception/frame`(`rosy.perception.frame/1`): 로봇 기준 바닥 좌표의 `PerceptionFrame`. 좌우·가운데 경계,
     장면 요소, `floor_valid_to_m`, 위험 표시를 담는다. 모든 소비자(추종기, 오버레이, 채점기, 데이터셋)는 이것만 읽는다.
2. **백엔드는 교체할 수 있다.** `rule`, `learned_seg`, `learned_det`가 같은 `perception/evidence`를 채운다. 선택은
   설정 `perception.backend`다. 여럿을 합치는 `fused`는 선택 사항이다.
3. **공통 층은 하나다.** `GroundProjector`(영상→바닥, 수평선 위와 유효 거리 밖은 버림)와 `SceneTracker`(좌우 일관
   배정, 경계 곡선, 장면 요소, 기억과 등급 사다리)는 control 안의 ROS-free 코드 하나에만 둔다. 백엔드는 이 층을
   다시 구현하지 않는다.
4. **프레임 소스와 카메라 프로필.** `FrameSource`(ROS 이미지, 녹화 영상)가 `Frame`을 넘기고, 소스마다
   `CameraProfile`을 revision과 함께 가진다. 모르는 프로필이나 revision이면 인식은 닫힌다(fail closed).
5. **도구.** 녹화 영상 재생기(ROS 없이, Windows 호스트에서도)와 `GroundTruthLabeler` + 채점기 + 데이터셋 기록기를 둔다.
   큰 데이터는 D-186에 따라 저장소 밖에 둔다.
6. **Gazebo 세계는 실물에 맞춰 다시 만든다.** 카메라는 측정한 실물 값으로, 트랙은 실측 매트 치수로, 벽과 바닥은
   실물 재질로 만든다. 세계 revision을 올린다.
7. **기존 출력은 파생 출력으로 남는다.** `line/observation`, `road/observation`, `dock/observation`은
   `PerceptionFrame`에서 파생해 계속 발행한다. CORE의 입력은 바뀌지 않는다.
8. **불변 조건.**
   - CORE만 `/cmd_vel`을 발행한다.
   - CORE는 영상 바이트와 OpenCV를 다루지 않는다(D-66, D-136).
   - control은 증거만 발행한다.

**Consequences:**

- 25° 세계에서 받은 이전 시뮬 합격(교차로, 순회, 주차)은 장치 증거가 아니다. 새 세계에서 다시 받는다.
- 장치 주행 전에 필요한 것이 셋이다. 벽 밑선 아래 바닥만 보는 마스크, 적응형 문턱, 한 줄 시작 경로다.
- control 패키지 분할(크기 판정 32,106줄, `split`)은 설계 P1–P3 안에서 실행한다. 인식 코드가 새 모듈 경계로
  옮겨지는 시점과 맞춘다.
- 계약이 고정되면 모델 담당자는 `perception/evidence`만 맞추면 된다. 재생기와 채점기로 규칙 기반과 나란히 비교한다.
- 실측값(차선 간격, 선 폭, 렌즈 높이 등)이 오기 전에는 P0를 닫을 수 없다. 프로필과 세계는 추정값으로 남는다.
- `line/observation`에 등급(`basis`)을 더할지는 따로 정한다. 정하면 API·프로토콜 문서의 변경이다.

**References:** 설계 [2026-09-24-perception-architecture-design.md](../plans/2026-09-24-perception-architecture-design.md),
[실물 영상 기준선](../validation/perception-real-video/2026-09-24/baseline.md), D-66, D-136, D-137, D-143, D-162, D-186.

**See also:** [D-205](D-205-real-lane-mission-transition-order.md) — 다음 단계의 실행 순서와 게이트, 인계 절차.
