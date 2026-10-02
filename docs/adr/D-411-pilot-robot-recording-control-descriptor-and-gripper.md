## D-411 Pilot 로봇측 학습 녹화·HTTP 수신, 기기가 알리는 조작부 서술자, OMX 그리퍼 전용 목표

**Status:** Proposed (2026-10-02, 사용자 승인 — 설계 A·B·C, 실물 OMX는 시뮬레이션만, 순서 A→B→C). SOURCE·ROS-SIM까지가 이 결정의 수용 범위다. 실기 녹화(DEVICE)는 로봇 공유 규칙에 따라 사용자 확인 후 따로 기록한다.

## 배경과 확인한 차이

- Pilot 주행 화면의 "녹화"(`screens/drive.js`, `web_common/evidence.js`)는 태블릿 브라우저가 2 fps 캔버스를 webm으로 내려받는다. 조작 값(linear/angular)이 없고 로봇에 저장되지 않는다(`storeOnRobot: null`). 모방학습 데이터가 아니다.
- 학습용 bag(`control.recording`, `record_session`)과 PC 수신(`harvest.py`, SSH)은 있으나 Pilot·CORE API가 그 녹화를 켜고 끄거나 내려받을 길이 없다. 녹화 폴더(`/var/lib/rosy/camera/recordings`, `rosy-camera` 0750)는 CORE가 읽을 수 없다.
- 기록되는 `cmd_vel`은 `safety.clip` 이후 최종 명령이다. 운용자 원 입력과 운전 주체(수동/자율)가 남지 않아 사람이 몬 구간을 고를 수 없다.
- Pilot의 조작부는 Pinky 하드코딩 `PROFILE` 하나이고, OMX 시뮬레이션은 시작 시 존재 탐지로 별도 화면을 연다(D-323·D-366의 "기기가 계약으로 드러낸 조작만 보인다"를 일반 구조로 갖추지 못했다).
- OMX 그리퍼는 관절 하나로만 다뤄져 ±0.02 rad 버튼과 0.05 rad 조그 상한에 묶이고, 쥠 상태 readback이 없다.

## 결정

### A. Pinky Pilot 로봇측 녹화와 HTTP 수신

1. **소유:** 녹화 프로세스는 카메라 유닛(`rosy-camera`)의 `pilot_recorder_node`가 소유한다. CORE는 ROS 서비스로 시작/정지를 요청만 한다. 녹화는 증거이며 제어 경로가 읽지 않는다(D-2, D-209). 노드는 기존 `control.recording`(session.json, 쿼터, `bag_command`)을 재사용한다.
2. **내용:** `camera/front/compressed`, `cmd_vel`(최종), `odom`, `scan`, `line/observation`, 그리고 새 증거 토픽 `teleop/intent`(std_msgs/String JSON `rosy.teleop.intent/1`: 원 입력 `linear/angular`, 클립 후 값, `source`, 모드, 수락 여부·거절 코드, 단조 시각). CORE가 `/api/v1/teleop` 수락·거절 때마다 낸다. 녹화 중에만 카메라 노드가 압축 토픽을 낸다(raw 1.7 MB/s는 담지 않는다).
3. **한계:** 1회 최대 10분, 전용 쿼터, 동시 녹화 1개. Pilot 연결이 끊기거나 seat가 바뀌면 CORE가 녹화를 멈춘다. 녹화 시작은 operator 이상.
4. **저장:** `/var/lib/rosy/pilot-recordings` (`2750 rosy-camera:rosy-core`, tmpfiles; `maps`와 같은 setgid 방식). 카메라 유닛에 `ReadWritePaths`, CORE에 `ReadOnlyPaths`를 준다.
5. **수신:** `GET /api/v1/recordings`(목록: id, 시작·끝, 길이, 크기, 토픽, 상태, sha256 manifest), `GET /api/v1/recordings/{id}/archive`(tar 스트림, 무압축 — mcap이 이미 zstd). 수신은 **로봇이 정지해 있을 때만**(MANUAL 입력 없음·자율 모드 아님·녹화 중 아님) 허용한다(D-136 §6). 실패 코드는 `RECORDING_BUSY`·`ROBOT_MOVING`·`RECORDING_NOT_FOUND`.
6. **PC:** `rosy_ml fetch --http`가 위 API로 받고 manifest sha256을 검증한 뒤 `bag_to_video`로 변환하고, 사이드카에서 프레임·`cmd_vel`·`teleop/intent` 짝을 다시 읽어 개수를 확인한다. 저장 위치는 D-379 store를 따른다.
7. **Pilot UI:** 주행 화면에 로봇 녹화 토글(경과 시간·크기), "녹화본" 시트(목록·받기·정지 중에만 받기 가능). 기존 브라우저 녹화는 "화면 녹화"로 이름을 바꿔 둔다.
8. **녹화 시작 판정(2026-10-02 Gazebo 실행 뒤 보강):** 녹화기 상태에 `starting` 을 둔다. rosbag2 를 띄운 뒤 첫 mcap 파일이 생길 때까지(실측 4 s)는 `starting` 이고 경과 시간을 세지 않으며, 그 순간부터 `recording`·`started_at`·길이를 센다. 15 s 안에 파일이 없으면 `writer_start_timeout` 으로 멈춘다. Pilot 은 그동안 "녹화 준비 중…"(멈춤 가능)을 보인다. session `device` 는 호스트 이름이 아니라 로봇(네임스페이스 또는 `device` 파라미터)이다. 세부는 API Ref §5.10.

### B. 기기가 알리는 조작부 서술자 `rosy.controls/1`

8. 기기는 조작부 목록을 알린다. 각 항목은 `{id, kind, label, ...kind별 필드}`이고 kind는 `base_velocity`(최대 속도, pivot, fine, autonomy), `joint_jog`(관절 이름·한계, 1회 최대 변화, 명령 방식 `bounded_goal`), `gripper`(C 참고)다. Pinky는 CORE `/api/v1/system/capabilities`의 `controls`(adapter manifest `provides: [drive]`에서 유도), OMX 시뮬레이션은 `/api/v1/sim/omx/target`의 `controls`로 낸다.
9. Pilot에서 **드라이버는 전송만**, **위젯은 kind별 하나**다. 화면은 서술자로 위젯을 조립하고, 모르는 kind는 "지원하지 않는 조작부"로 보이고 멈추지 않는다. 서술자가 없는 구 서버는 기존 Pinky 프로필로 대체한다.
10. 팔 조이스틱: 스틱 두 축을 관절 두 개에 맵핑한다(바꿀 수 있다). 누르는 동안 기울기에 비례한 제한 목표(≤ 서술자의 최대 변화)를 **이전 목표가 끝난 뒤에만** 보낸다. 떼면 진행 목표를 취소한다(구현 부록 1로 조정: 떼면 새 목표만 멈춘다). 100 ms 스트림을 팔에 쓰지 않는다(D-390 §2 유지).

### C. OMX 그리퍼

11. 서술자 `gripper`: `{joint, closed, open, unit, presets: {open, half, close}, readback: ["position", "grasp"]}`.
12. 시뮬레이션 API에 그리퍼 전용 절대 목표 `OmxSimGripperGoal{instance_id, seat_id, request_id, position, duration_s(0.2–2.0), state_sequence, expires_at_ms}`를 둔다. 위치는 한계 안이어야 하며 넘으면 거절한다. 같은 단일 owner·seat·HOLD 규칙을 따른다(D-386).
13. readback에 그리퍼 상태 `open|closed|holding|moving|unknown`을 더한다. `holding`은 닫기 목표가 끝났는데 위치가 닫힘에서 허용오차 이상 떨어져 멈춘 경우다.
14. UI는 열기/반/닫기 버튼, 열림 % 슬라이더, 상태 배지를 오른손 영역에 둔다. 시연 기록과 LeRobot export는 그리퍼 action을 별도 열(`action.gripper`)로 남긴다.

## 범위 밖

- 실물 OMX 조종(D-390 §5 유지), 직교좌표 조그(D-404), Pinky 외 실물 기기 활성화.
- 녹화본의 원격 저장소 게시(D-356/D-373 학습 루프 소유).

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 브라우저 녹화 + PC 업로드 | 카메라 ≤2.5 fps, scan·odom·원 입력이 없어 학습 데이터 품질이 낮다. |
| Pilot은 시작/정지만, 수신은 SSH harvest | 운용자 SSH 키가 필요하고 앱에서 받는 요구를 못 채운다. harvest는 PC 도구로 남는다. |
| CORE가 직접 `ros2 bag` 실행 | CORE 유닛에 카메라 상태 쓰기 권한과 장시간 자식 프로세스를 더해 경계를 넓힌다. |
| 그리퍼를 관절 조그로 유지 | 0.05 rad 상한에 묶여 열고 닫는 데 수십 번 눌러야 하고 쥠 판정이 없다. |

## 수용 기준과 증거 경계

- **SOURCE:** 녹화 상태기계(시작·정지·한계·연결 끊김·쿼터), 수신 게이트(움직임·녹화 중), manifest sha256, tar 경로 탈출 차단, `teleop/intent` 스키마, 서술자 스키마와 Pinky 유도, 위젯 조립·미지 kind, 팔 조이스틱 순차 목표·떼면 취소(구현 부록 1로 조정), 그리퍼 목표 한계·`holding` 판정, Pilot 브라우저 회귀.
- **ROS-SIM:** Gazebo Pinky에서 Pilot 주행 녹화 → 정지 → HTTP 수신 → `bag_to_video` → 프레임·action 짝 재독출. OMX Gazebo에서 그리퍼 열기/닫기/쥠과 시연 기록 export.
- **DEVICE:** 사용자 확인 후 실기 녹화·수신을 별도 기록한다. 이 결정만으로 승격하지 않는다.

**관련 결정:** [D-2](D-2-cmd-vel.md), [D-136](D-136-.md), [D-323](D-323-rosy-pilot-teleop-app.md), [D-356](D-356-perception-learning-loop-and-model-delivery.md), [D-366](D-366-pilot-multidevice-roadmap.md), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md), [D-379](D-379-learning-data-pipeline-auto-labels-local-store.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md).

## 구현 부록 (2026-10-02)

1. **떼면 취소 → 떼면 새 목표만 멈춤(결정 10 조정).** OMX `ArmCommandOwner.cancel()` 은 소유자를 HOLD 로 건다(`omx_adapter/command_owner.py` `_enter_hold("cancel_requested")`). 풀려면 `recover(operator_confirmed=True)` 가 필요한데 Pilot SIM API 에는 recover 경로가 없어, 손을 뗄 때마다 취소하면 첫 손 떼기 뒤 팔이 다시 움직이지 못한다. 그래서 조이스틱은 손을 떼면 다음 목표 발행을 즉시 끊고, 이미 나간 목표(≤ `max_step_rad`, 길이 `duration_s`)는 끝까지 둔다. 명시적 "진행 중 명령 취소" 버튼(HOLD 를 거는 비상 경로)은 남긴다. 목표는 여전히 하나씩, 이전 목표가 종결 상태가 된 뒤에만 보내며 100 ms 스트림은 쓰지 않는다(D-390 §2).
2. **두 축 동시 기울임은 우세 축 하나.** 목표 하나는 관절 하나(`OmxSimJog.joint`)라 더 크게 기운 축의 관절만 보낸다. 크기는 데드존(0.15) 너머 기울기에 비례해 `max_step_rad` 까지.
3. **CORE capabilities 의 `provides`.** 켜진 adapter manifest 의 `provides` 에서 유도하고, manifest 가 없으면 `teleop` 플래그에서 `drive` 를 유도한다. `teleop` 이 보류되면 `drive` 는 빠진다.
4. **CORE "seat".** 녹화 가드의 seat 는 녹화를 시작한 토큰의 `/ws/state` 링크이며, 다른 토큰의 teleop 이 수락되면 seat 변경으로 본다.
5. **`autonomy` 의 뜻.** CORE 는 line-follow 서비스를 가질 때 `["line"]` 을 낸다. 쉬는 동안 차선을 따라갈 수 있음을 보이는 정직한 런타임 신호가 없어(차선 관측은 모드를 켠 뒤에만 들어온다) "제공함"으로 정의하고, 시작 가능 여부는 `PUT /line-follow/mode`·`GET /line-follow` 가 판정한다(API Ref §9.1).
6. **Pilot 소비 규칙.** `controls` 필드가 없으면 구 서버로 보고 기존 Pinky 프로필(SIM 은 기존 0.02 rad 관절·그리퍼 조그)로 대체한다. 빈 `items` 는 "지금 조작부 없음"으로 보이고 대체하지 않는다. 모르는 kind 는 "지원하지 않는 조작부 · 이름"으로 보이고 화면은 계속 동작한다.