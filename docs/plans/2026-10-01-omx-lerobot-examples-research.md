# OMX-AI / LeRobot 공식 예제 조사와 Pilot 개선 근거

조사일: 2026-10-01 (Asia/Seoul). 범위: 공식 ROBOTIS 문서·소스와 Hugging Face LeRobot 문서·소스. 이 문서는 외부 예제 조사이며 Rosy의 새 구현이나 실물 검증을 통과시킨 기록이 아니다.

## 결론

Pilot의 ROS-native Gazebo 경로에서 시연을 기록하고, 별도 작업으로 LeRobotDataset을 생성하는 구성이 적합하다. LeRobot의 기본 OMX USB 드라이버를 Pilot 옆에 실행하면 별도의 모터 writer가 생긴다. 기록·학습 형식은 가져오되 명령 승인은 기존 Rosy owner가 유지해야 한다. 아래 구현 제안은 조사 결과에 대한 Rosy 적용 판단이다.

## 공식 예제의 세 경로

| 경로 | 확인된 역할 | Rosy에 적용할 부분 |
|---|---|---|
| LeRobot `omx_follower` + `omx_leader` | USB/Dynamixel 직접 teleoperation, 선택 카메라 | feature 이름·단위·writer 차이 비교 |
| ROBOTIS `physical_ai_tools` | ROS 상태·leader trajectory·카메라 수집, LeRobot 변환·학습·추론 | 상태와 action 분리, episode·task·변환 단계 |
| ROBOTIS OpenMANIPULATOR | ROS 2 OMX-F Gazebo launch | 현재 Pilot의 ROS action 경로에서 sim 증거 재사용 |

OMX-AI는 OMX-F follower와 OMX-L leader로 구성되며 각각 5 arm DOF + gripper다. OpenMANIPULATOR-X나 OMY와 동일한 모델로 취급하면 안 된다. [ROBOTIS OMX hardware](https://docs.robotis.com/docs/systems/omx/specifications/hardware/)

Hugging Face 공식 OMX 예제는 `lerobot-teleoperate --robot.type=omx_follower --teleop.type=omx_leader`를 사용하고, 카메라 예시는 `front`, OpenCV `/dev/video0`, 640×480, 30 FPS다. 이것은 USB follower를 직접 여는 예제다. [LeRobot OMX guide](https://huggingface.co/docs/lerobot/en/omx)

공식 ROS 저장소에는 `omx_f_follower_ai_gazebo.launch.py`와 `omx_f_gazebo.launch.py`가 실제 존재한다. 전자는 `ros_gz_sim`을 통해 world/model을 구동한다. Gazebo OMX launch의 존재가 LeRobot native OMX driver의 ROS/Gazebo 자동 연결을 의미하지는 않는다. [Pinned Gazebo launch](https://github.com/ROBOTIS-GIT/open_manipulator/blob/d31000d90c679af9c982e73de8b12d777c5ff7dd/open_manipulator_bringup/launch/omx_f_follower_ai_gazebo.launch.py)

## 가장 큰 차이: 관절 이름과 단위

| Rosy ROS 순서 | Native LeRobot 순서 | Native LeRobot 표현 |
|---|---|---|
| `joint1` | `shoulder_pan.pos` | 기본 normalized −100…100 |
| `joint2` | `shoulder_lift.pos` | 기본 normalized −100…100 |
| `joint3` | `elbow_flex.pos` | 기본 normalized −100…100 |
| `joint4` | `wrist_flex.pos` | 기본 normalized −100…100 |
| `joint5` | `wrist_roll.pos` | 기본 normalized −100…100 |
| `gripper_joint_1` | `gripper.pos` | normalized 0…100 |

Native follower는 IDs 11–16을 사용하고, `use_degrees=True`일 때 arm 표현이 degrees로 바뀌지만 gripper는 여전히 0…100이다. `send_action`은 `Goal_Position`을 직접 sync-write한다. `max_relative_target`의 기본값은 `None`이다. [Pinned follower implementation](https://github.com/huggingface/lerobot/blob/e0d50211ef236143ae867228662b7dfaba554f02/src/lerobot/robots/omx_follower/omx_follower.py), [Pinned follower config](https://github.com/huggingface/lerobot/blob/e0d50211ef236143ae867228662b7dfaba554f02/src/lerobot/robots/omx_follower/config_omx_follower.py)

Native leader는 IDs 1–6을 사용하고 arm −100…100, gripper 0…100을 읽는다. leader에 그리퍼 drive inversion·homing offset 설정이 존재하므로 숫자에 단순히 π/180을 곱하는 변환으로 ROS 모델을 맞출 수 없다. [Pinned leader implementation](https://github.com/huggingface/lerobot/blob/e0d50211ef236143ae867228662b7dfaba554f02/src/lerobot/teleoperators/omx_leader/omx_leader.py)

정규화는 calibration `range_min/range_max`를 사용한다. normalized 값은 캘리브레이션 범위에 대한 비율이며 degrees/radians와 동일한 단위가 아니다. 변환에는 각 축의 zero·sign·calibration·실제 기구 범위를 고정해야 한다. [Pinned MotorsBus normalization](https://github.com/huggingface/lerobot/blob/e0d50211ef236143ae867228662b7dfaba554f02/src/lerobot/motors/motors_bus.py)

**적용 판단:** 첫 exporter는 `robot_type=omx_sim_ros`와 여섯 ROS 관절 이름, 전 축 radians를 명시한다. native `omx_follower`라고 표기하거나 native 정책 호환을 주장하지 않는다. gripper radians는 기구 각도이며 normalized 0…100이나 집게 간격 mm가 아니다. native policy 연결은 명시적 mapping 계약과 calibration 증거를 갖춘 별도 작업이다.

## ROBOTIS ROS 데이터 예제에서 가져올 점

Pinned `omx_f_config.yaml`은 `/joint_states`를 follower, `/leader/joint_trajectory`를 leader로 매핑하고, `joint1`…`joint5`, `gripper_joint_1` 순서를 고정한다. 기본 camera alias는 `camera1`, topic은 `/camera1/image_raw/compressed`다. [Pinned OMX ROS config](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/config/omx_f_config.yaml)

Converter는 `JointState.position`과 `JointTrajectory.points[0].positions`를 이름으로 재정렬한다. 이 단계에서 normalized/degrees 변환을 수행하지 않는다. state 누락 축을 건너뛰는 경로가 있어 Rosy는 누락·중복 관절을 명시적으로 거절해야 한다. DataManager는 follower를 `observation.state`, leader를 `action`으로 만든다. [Pinned converter](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/physical_ai_server/data_processing/data_converter.py), [Pinned data manager](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/physical_ai_server/data_processing/data_manager.py)

Communicator는 callback별 최신 메시지를 보관하며 leader topic publisher와 `publish_action`도 제공한다. 이 코드를 통째로 Rosy runtime에 삽입하면 command writer가 늘어날 수 있다. 구독 코드는 BEST_EFFORT/KEEP_LAST depth 1을 사용한다. 따라서 최신 캐시를 한 번 읽었다는 사실만으로 camera/action/state timestamp가 맞았다고 판정하면 안 된다. [Pinned communicator](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/physical_ai_server/communication/communicator.py), [Pinned subscriber](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/physical_ai_server/communication/multi_subscriber.py)

`physical_ai_tools`는 `feature-robotis` LeRobot submodule commit `989f3d05ba47f872d75c587e76838e9cc574857a`를 참조한다. 자체 dataset wrapper는 내부 metadata/writer 함수를 사용한다. 최신 LeRobot v3 exporter에 이 wrapper를 복사하면 호환이 보장되지 않는다. [Pinned submodule definition](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/.gitmodules), [Pinned wrapper](https://github.com/ROBOTIS-GIT/physical_ai_tools/blob/27192daf75fa5f421a3bd1825a50ee63d649dccd/physical_ai_server/physical_ai_server/data_processing/lerobot_dataset_wrapper.py)

## Dataset 구현 기준: stable v0.4.4

초기 호환 시험은 `lerobot==0.4.4`, Git tag commit `8fff0fde7c79f23a93d845d1a50e985de01f8b8a`로 고정한다. 이 tag의 `CODEBASE_VERSION`은 `v3.0`이다. Python ≥3.10, PyTorch·torchvision·datasets·PyAV 의존성이 있고, torchcodec는 Windows와 Linux ARM 계열에서 dependency 대상에서 빠진다. Windows 검증은 PyAV backend를 명시하는 것이 적절하다. 현행 main은 version 0.6.2/Python ≥3.12이므로 `main`과 stable tag를 혼용하지 않는다. [v0.4.4 dependencies](https://github.com/huggingface/lerobot/blob/8fff0fde7c79f23a93d845d1a50e985de01f8b8a/pyproject.toml), [Current main dependencies](https://github.com/huggingface/lerobot/blob/e0d50211ef236143ae867228662b7dfaba554f02/pyproject.toml)

해당 tag에는 `LeRobotDataset.create(repo_id, fps, features, root, robot_type, use_videos, video_backend)` → `add_frame(frame)` → `save_episode()` → `finalize()`가 존재한다. `add_frame`에는 `task`가 필요하며 입력 dict에서 task/timestamp를 pop한다. timestamp 생략 시 `frame_index / fps`가 생성된다. exporter는 새 dict/배열을 사용하고 원본 ROS 시각을 별도 보존한다. `finalize()`로 writer를 닫은 뒤 reader로 다시 열어 shape·관절 순서·값·episode 경계를 확인해야 한다. [Pinned Dataset API](https://github.com/huggingface/lerobot/blob/8fff0fde7c79f23a93d845d1a50e985de01f8b8a/src/lerobot/datasets/lerobot_dataset.py)

LeRobot v3는 Parquet 상태/action, camera별 MP4, feature schema/FPS/stats/episode offsets metadata를 사용한다. JSON/JSONL만 저장한 파일을 LeRobotDataset 완료라고 부르면 안 된다. 공식 문서가 설명하는 schema metadata만으로 Rosy의 명령 승인·ROS goal·sim provenance를 충분히 표현하지 못하므로 다음 항목은 Rosy manifest로 추가한다. [Dataset v3 format](https://huggingface.co/docs/lerobot/en/lerobot-dataset-v3)

## 이번 개선에 필요한 계약과 테스트

다음 목록은 Rosy 설계 제안이며 upstream 필수 필드를 주장하지 않는다.

1. 시연 episode는 task, sim target, 관절 순서·단위, source revision/image ID, 시작/종료 사유를 가진다. simulation 여부를 명시하여 실물 dataset과 혼용하지 않는다.
2. state는 실제 fresh ROS readback을 기록한다. action은 owner가 승인하고 실제 제출한 **절대 목표**를 기록한다. UI 클릭 delta나 desired input을 실행 action으로 대체하지 않는다. 거절된 클릭을 action label로 넣지 않는다.
3. 각 샘플에 source ROS stamp/clock, 수신 monotonic time, state sequence, command ID, ROS goal ID, 제출/완료/취소 상태를 연결한다. ROS clock pause/reset·중복·역행·state gap은 episode 품질 실패로 판정한다.
4. 불규칙한 클릭 간격을 그대로 두고 FPS만 30으로 선언하지 않는다. 고정 cadence sampler 또는 명시적 resampling 정책을 사용하며 retained target과 측정 state를 같은 시점에 묶는다. 안전 TTL은 monotonic wall clock을 유지한다.
5. 기록 owner는 파일 writer 한 개이며 command writer가 아니다. lease expiry/취소/owner HOLD 시 episode를 종료하고 중단 이유를 남긴다. 동시 기록·overwrite·경로 traversal을 거절한다.
6. 카메라가 없다면 state-only dataset으로 표시하고 video feature를 만들지 않는다. 카메라 추가 시 alias→topic→resolution→RGB encoding→timestamp/skew 정책을 고정한다. synthetic 영상은 synthetic으로 표시한다.
7. native USB OMX writer·leader trajectory writer·policy inference writer는 동시에 실행하지 않는다. replay/policy도 Rosy 승인 경로를 거쳐야 한다.

검증은 원본 시연→변환→실제 LeRobotDataset reader 재개방으로 수행한다. 최소 부정 사례는 누락/중복 관절, NaN/Inf, 단위 불명, timestamp 역행, stale state, rejected command, canceled episode, tampered provenance, 동시 writer다. 카메라 없는 smoke는 `use_videos=False`로 충분하지만 영상 동기화·encoding 성공이나 학습 성공을 증명하지 않는다.

공식 IL workflow는 teleoperation→episode 기록·검토→policy 학습→evaluation이며, record 기본 업로드는 `--dataset.push_to_hub=False`로 끌 수 있다. native `lerobot-replay`는 Robot의 `send_action`을 호출하므로 offline 시각 재생과 robot actuation replay를 UI에서 구분해야 한다. 이번 단계는 local recording/export/reader 검증이고, 실물 replay와 정책 추론은 writer·unit·safety 계약 후 별도 gate다. [Official imitation learning workflow](https://huggingface.co/docs/lerobot/en/il_robots), [Pinned replay writer](https://github.com/huggingface/lerobot/blob/8fff0fde7c79f23a93d845d1a50e985de01f8b8a/src/lerobot/scripts/lerobot_replay.py)
