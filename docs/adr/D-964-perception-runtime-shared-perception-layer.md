## D-964 차선 판정·학습 모델 실행 코드를 공유 계층 perception_runtime으로 나눈다

**Status:** Accepted (2026-11-03, 사용자 결정 「공유 추론 계층 신설」). 구조 결정이다. Pinky 이미지 빌드와 실물 기동 확인은 이 결정 시점에 **미수용**이다(아래 「수용 조건」).

잇는 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md)(플랫폼 part와 import 규칙) · [D-356](D-356-perception-learning-loop-and-model-delivery.md)(학습 차선 인식) · [D-630](D-630-remaining-platform-semantic-holders.md)(control 원천 holder)

### Context

학습 도구 `learning/{curation,evaluation,registry,training}/perception`은 로봇과 같은 차선 판정·모델 실행으로 평가·변환·배포해야 한다. 그래서 `control.sensing.perception.*`, `control.recording`을 직접 import했고, `test/architecture/test_platform_parts.py`는 이를 `learning -> middleware/perception` 예외 4개로 얼려 두었다. 이 의존은 의도된 재사용이지만, 예외로 남으면 middleware 쪽 변경이 학습 도구를 조용히 깨도 계층 규칙이 막지 못한다.

학습 도구가 쓰는 모듈의 import 닫힘은 28개 모듈·6,491줄이고 `rclpy`·middleware 의존이 없다. 외부 의존은 `core_common`(contracts), numpy, OpenCV, `onnxruntime`·`ncnn`·`mcap`(지연 import)뿐이다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 예외를 규칙의 정식 허용(learning → middleware/perception)으로 바꾼다 | 코드는 그대로이고 middleware 전체가 학습 쪽에 열린다. 채택하지 않는다 |
| `manifest.py`만 `contracts/learning`으로 옮긴다 | 결합은 줄지만 runner·detector·lane_mask·차선 판정 때문에 예외 4개가 그대로 남는다. 채택하지 않는다 |
| **닫힌 28개 모듈을 새 integrations part `integrations/perception`(ROS 패키지 `perception_runtime`)으로 옮기고 middleware·learning이 그 part만 import** | 예외 4개가 사라지고, 공유 범위가 import 닫힘으로 정해진다. **채택** |

### Decision

1. `integrations/perception`은 ament_python 라이브러리 패키지 `perception_runtime`이다. `perception_runtime.recording`, `perception_runtime.keep_odom_veto`, `perception_runtime.perception.*`, `perception_runtime.perception.learned.*`를 둔다. 모듈 본문은 옮기기만 하고 import 경로만 바꾼다.
2. `perception_runtime`은 `contracts`와 외부 라이브러리만 import한다. `control`·`rclpy`·다른 middleware를 import하지 않는다. 명령 topic을 발행하지 않는다.
3. `tools/harness/platform_parts.yaml` `import_rules`의 `middleware.integrations`와 `learning.integrations`에 `perception`을 더한다. 다른 허용은 바꾸지 않는다. `KNOWN_VIOLATIONS`의 learning → middleware/perception 4행을 지운다.
4. 로봇 노드·카메라 worker·drivable 조향, 학습 도우미 중 `shadow`·`status`·`paint_worker`·`paint_motion`·`expected_path`는 `control`에 남는다(학습 도구가 쓰지 않고, drivable은 다른 작업이 진행 중이다).
5. `control/package.xml`은 `perception_runtime`을 exec_depend한다. Pinky 이미지는 `--packages-select`·`required-ros-packages.txt`에 이를 더하고, native payload는 colcon root 전체를 빌드하므로 따로 등록하지 않는다. 모델 PC 서명 코드 배치(`deploy/site/model_code_layout.py`)는 `integrations/perception/`을 코드·import 경로에 더한다.
6. 소스 체크아웃에서는 `control/__init__.py`가 `integrations/perception`을 `sys.path`에 더한다(설치본에는 colcon이 따로 설치하므로 영향 없음). 학습·도구 스크립트는 `middleware/perception` 옆에 `integrations/perception` 경로를 둔다.

### D-427·D-429·D-430과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | part 목록과 동일 part 규칙은 그대로다. integrations에 새 종류 `perception`을 더하고 middleware·learning의 허용 목록에 넣는다. 예외 4개를 없애므로 전체 허용 간선은 줄어든다 |
| D-429 | concern은 `control`, capability는 `vision_ai`로 원래 holder와 같다. api root 규칙은 바뀌지 않는다 |
| D-430 | safety 경로·최종 `cmd_vel` 단일 발행자 규칙은 바뀌지 않는다. `test/test_module_separation.py`의 최종 topic 금지 검사는 `integrations/perception`도 control 트리로 계속 본다 |

### 수용 조건

- 원격 시험 PC에서 `test/architecture`, `middleware/perception/test`, `integrations/perception/test`, `test/learning`, `learning/*/perception` 시험 통과(착지 기록).
- Pinky 이미지 빌드에서 `perception_runtime`이 설치되고 `control` 노드가 import되는지 확인(미실행).
- 실물 Pinky에서 차선 유지·학습 그림자 노드 기동 확인(미실행).
