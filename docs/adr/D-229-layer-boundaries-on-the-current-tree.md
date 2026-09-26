## D-229 모듈 경계는 지금 폴더를 따라 한 방향으로만 흐른다

**Status:** Accepted (2026-09-25). 새 영역 루트는 만들지 않는다.
잇는 결정:

- D-2, D-38, D-208: 최종 `cmd_vel` 은 `core` 다. 감지 프로파일은 속도를 내지 않는다.
- D-126: `core_features` 는 `control` 을 import 하지 않는다.
- D-209: 영상 인식은 `control/sensing/perception` 이다. ROS 를 부르지 않는다.
- [D-227](D-227-ownership-names-stay-on-the-current-tree.md), [D-228](D-228-decision-lives-in-core-features.md): 판단은 `core_features/decision` 이다. `src/runtime` 은 없다.

**Context:**

1. **폴더는 나뉘었는데 패키지 입구가 아직 영상을 끌어왔다.** `sensing/__init__.py` 가 `classify_frame` 을 다시 내보내면, 라이다와 차체를 부르는 쪽이 카메라까지 읽는다.
2. **호출부가 옛 패키지 입구를 남아 쓰고 있었다.** `from control.sensing import lane_bev` 는 파일이 `perception/` 으로 옮겨진 뒤 깨진다. 점 경로만 고치면 이 형태는 남는다.
3. **세 층의 산출이 다르다.** 인식은 기하와 신뢰도다. 판단은 허용된 동작 id 다. 추종기는 그 id 가 `FOLLOW` 일 때만 속도를 계산한다. 한 모듈이 이웃의 산출을 만들면 폴더를 나눈 이유가 사라진다.

**Decision:**

1. **방향은 아래가 전부다.**

   | 폴더 | 내는 것 | 부르지 않는 것 |
   |---|---|---|
   | `control/sensing/*.py` | 스캔, 차체, 필터, 도크 태그 | `perception`, `core_features`, `cmd_vel` |
   | `control/sensing/perception` | 영상·차선 증거 | `rclpy`, `core_features`, `line_follow` |
   | `core_features/decision` | 동작 id | `control`, `cv2`, `rclpy`, `line_follow` |
   | `core_features/line_follow` | `FOLLOW` 다음의 속도 식 | `control`, `cv2`, `rclpy`. 판단은 import 한다 |
   | `core_features/command`, `core` 브리지 | 최종 `cmd_vel` | 픽셀 |
   | `core_features/safety` | 속도 상한과 정지 | 판단 제공자가 아니다 |

2. **`sensing` 패키지 입구는 영상을 다시 내보내지 않는다.** 카메라와 차선은 `control.sensing.perception` 으로만 부른다.
3. **관찰 노드만 두 층을 잇는다.** `camera_detect_node`, `line_observer_node`, `road_observer_node` 는 인식 모듈을 불러 사실을 발행한다. 그 노드가 최종 속도를 내지 않는 규칙은 D-208 이다.
4. **이 경계는 시험으로 잠근다.** `test/test_layer_boundaries.py` 가 import 를 본다. 주석 속의 단어는 경계가 아니다.

**Consequences:** 인식 모듈을 `sensing` 루트로 되돌리거나, 판단 모듈이 OpenCV 를 부르면 이 결정을 어긴다. 도크 태그는 카메라 입력이어도 `perception/` 으로 옮기지 않는다 (D-209).

**Validation:** `python -m pytest test/test_layer_boundaries.py src/core/control/test/test_lane_edge.py src/core/control/test/test_camera_ground.py -q`
