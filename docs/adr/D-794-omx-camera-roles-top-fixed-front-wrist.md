## D-794 OMX 카메라 역할: `top`은 작업대 고정, `front`는 손목이다 — `wrist` 이름으로 단계 이행하고 학습은 두 카메라를 쓴다

**Status:** Proposed

## Context

2026-10-18 사용자 확인: OMX-AI에는 손목 카메라가 이미 있고, 이름이 `front`인 카메라가 그 손목 카메라다. 2026-10-16 보존 프레임(Fleet `~/rosy-test/omx-camera-hires-033ab57d1/{top,front}/frame.jpg`, 1280×720)을 열어 확인했다.

| 역할 키 | 실제 위치 | 프레임에서 보이는 것 |
|---|---|---|
| `top` | 작업대 위 고정 | 두 팔, 매트 전체, 물체(딸기·흰 공·원통 4개) |
| `front` | follower 그리퍼 바로 위 | 매트 근접 질감, 양쪽 집게 손가락, 손목 구조물 |

이름이 실제 위치와 맞지 않는다. `front`는 Pinky의 전방 카메라(`/api/v1/vision/front`, D-601)와도 같은 단어라, 사람과 에이전트가 "작업대를 앞에서 보는 고정 카메라"로 읽는다. D-792 설계도 처음에 그렇게 읽어 손목 카메라를 고정 카메라로 다룰 뻔했다.

카메라를 쓰는 경로는 둘이다.

| 경로 | 카메라 | 근거 |
|---|---|---|
| 실물: LeRobot 기록과 공식 ACT CLI (D-299, D-770) | 녹화 설정의 모든 카메라. `collection_profile.py`·`camera_readiness.py`·`collection_intake.py`가 `top`과 `front`를 둘 다 요구한다 | `deploy/robot/omx/record_config.py`, `learning/training/omx/native_cycle.py` |
| 시뮬레이션: 공통 Episode와 `act_job.py` (D-787) | `front` 하나, 64×64 | `contracts/learning/src/rosy/contracts/learning/omx.py`가 `simulation=True`·`gazebo_sim`과 `camera.name == "front"`를 요구한다 |

실물 시연은 아직 0회다(`docs/validation/omx-camera-clearance-2026-10-16/result.md`). 이름을 바꾸는 비용이 지금 가장 작다.

## Decision

### 1. 역할의 뜻

- `top`: 작업대에 고정된 장면 카메라. 물체가 작업대 어디에 있는지와 두 팔의 자세를 본다.
- `front`(이행 후 `wrist`): follower 그리퍼에 달린 손목 카메라. 팔과 함께 움직이며 잡기 직전의 근접 상태를 본다.
- 손목 카메라의 촬영 기준 확인은 D-792의 `check_pose`로 한다. 고정 카메라와 같은 방식으로 비교하지 않는다.
- 광각 카메라로 바꾸지 않는다. `top`이 작업대 전체를 이미 덮고, 손목 카메라가 근접을 맡는다. 화각을 넓히면 정책 입력에서 물체·그리퍼 픽셀이 줄고 왜곡 교정(D-633)과 데이터 재수집이 필요하다.

### 2. `front` → `wrist` 이름 이행

한 번에 바꾸지 않는다. OMX 코드는 여러 세션이 동시에 고치고 있고(`omx-native-*`, `sim-il-*` 워크트리), 학습된 정책은 학습 때의 특징 키로만 추론할 수 있다.

| 단계 | 하는 일 | 끝난 기준 |
|---|---|---|
| A (이 ADR) | 뜻을 고정한다. 화면·문서는 `front(손목)`으로 적는다. `CONCEPTS.md`에 용어를 둔다 | lint |
| B | 읽는 쪽이 `front`와 `wrist`를 같은 손목 역할로 받는다. 별칭 표는 `contracts/learning/.../omx.py`의 `WRIST`·`WRIST_ALIASES`·`camera_role`·`camera_roles` 한 곳이다. 읽는 쪽은 받은 이름을 `WRIST`(지금은 `front`)로 정규화하고, 내보내기·학습·추론의 이미지 키는 기록·학습된 카메라 이름에서 만든다. 장치 이미지 쪽(`deploy/robot/omx`, `middleware/devices/omx` 어댑터 사본)과 실행 대조(`omx_policy.py` 카메라 바인딩)는 학습 계약 wheel 버전 고정(0.1.12)을 함께 올려야 하므로 C로 넘긴다 | 계약·환경·intake·내보내기 시험이 두 이름을 모두 받는다 |
| C | 쓰는 쪽(녹화 설정, collection profile, ROS 토픽, LeRobot 특징 키 `observation.images.wrist`)과 B에서 넘긴 장치 쪽 읽기·실행 대조를 한 착지에서 바꾸고 `WRIST`를 `"wrist"`로 뒤집는다. 학습 계약 wheel 버전과 고정값을 같이 올린다. OMX 워크트리 담당과 착지 순서를 먼저 맞춘다 | 새 녹화·새 데이터셋이 `wrist`를 쓴다 |
| D | 승격 원장에 `front` 키를 쓰는 데이터셋·정책이 남지 않으면 별칭을 지운다 | 원장 조회 0건 |

- 정책은 학습 때의 카메라 키로 추론한다. 단계 B의 정책 설치는 별칭으로 키를 맞추되, 정책 산출물의 `cameras` 기록은 바꾸지 않는다.
- Pinky의 `front`(전방 카메라)는 이 ADR의 대상이 아니다.

### 3. 학습 입력은 두 카메라

- 실물 경로는 이미 `top`과 손목을 둘 다 기록하고 쓴다. 녹화 설정에서 한쪽을 빼려면 이유를 기록해야 한다.
- 시뮬레이션 경로(D-787)는 지금 손목 하나만 쓴다. Gazebo 월드에 실물 `top`과 같은 자리의 고정 카메라가 생기면 공통 Episode 계약과 `act_job.py`가 두 카메라를 받도록 넓힌다. 그 전의 시뮬레이션 정책은 "손목 단일 카메라"로 표시하고, 두 카메라 실물 정책과 성능을 비교하지 않는다.
- 이 항목의 구현은 D-787 담당 워크트리가 소유한다. 이 ADR은 방향과 비교 규칙만 정한다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 경계를 바꾸지 않는다. 별칭 표는 `contracts/learning`에, 녹화 쪽 이름은 `deploy/robot/omx`에 둔다. |
| D-429 | 장치 제어 포트를 바꾸지 않는다. 카메라 이름은 관측 장치의 이름이다. |
| D-430 | safety 경로를 바꾸지 않는다. |
| D-273·D-282 | 상부 RGB와 손목 RGB 구성을 그대로 따른다. 이름만 위치에 맞춘다. |
| D-299·D-770 | 실물 LeRobot 기록 경로가 두 카메라를 쓰는 현재 동작을 유지한다. |
| D-449 | 정책 산출물의 `cameras` 기록을 바꾸지 않는다. 단계 B의 별칭은 읽기에만 쓴다. |
| D-787 | 시뮬레이션 단일 카메라 정책의 표시와 비교 규칙을 더한다. 시뮬레이션 월드 구현은 D-787 쪽 일이다. |
| D-792 | 손목 카메라는 `check_pose`로 확인한다. 화면은 `front — 손목`으로 표시한다. |

## Consequences

- 사람과 에이전트가 `front`를 고정 전방 카메라로 잘못 읽는 일이 줄어든다.
- 단계 B·C 사이에는 두 이름이 같이 존재한다. 별칭 표 한 곳만 보면 되도록 다른 곳에 이름 비교를 흩뿌리지 않는다.
- 시뮬레이션과 실물의 정책 성능을 바로 비교할 수 없다는 사실이 기록에 남는다.

## Validation

- 단계 A: `python tools/harness/rosy_harness.py lint`
- 단계 B 이후: 각 단계 커밋이 정한 계약·내보내기·학습·정책 설치 시험

## References

D-273, D-282, D-299, D-427, D-429, D-430, D-449, D-601, D-633, D-770, D-787, D-792
