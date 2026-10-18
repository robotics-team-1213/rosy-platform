## D-440 기기별 전원 정책 — 제품이 기기를 선언하고, 한 벤치 스위치 뒤에서 모드별로 끄거나 줄인다

**Status:** Proposed (2026-10-04 사용자 요청·결정 반영 초안, 2026-10-13 현재 main 구조로 다시 옮김). 정책은 벤치 스위치 `power.device_policy.enabled: false`로 꺼져 있다. 켜는 결정은 `docs/deployment/power-bench-verification.md` §8 통과 뒤 별도 커밋으로 한다. 호스트 pytest만 있고 실기에서 기기를 재우거나 깨운 증거는 없다.

**Connects:** D-24(개정과 함께), D-25, D-27, D-2, D-38, D-429, D-430, D-442, D-196, D-397, D-540.

> 번호 메모: 2026-10-04에 `feat/device-power-policy`가 이 번호를 썼고 main에는 `adr_gaps`로만 남아 있었다. D-442·D-443의 번호 메모가 말하는 "D-440(per-device power policy)"이 이 문서다.

### Context

- D-24의 `PowerManager`는 ACTIVE/IDLE/STANDBY를 정하고, 실기(9dfk)에서 STANDBY까지 갔다. 그러나 모드에 반응하는 기기는 ADC 노드와 얼굴 화면뿐이었다. LiDAR 정지는 `lidar.standby_stop`(기본 false)으로만 있었고, 카메라·인식은 모드를 몰랐다.
- 기기마다 끌 수 있는지, 깨운 뒤 얼마 뒤 믿을 수 있는지가 다르다. 그 사실은 제품(로봇 패키지)이 안다. CORE 기본값에 기기 이름을 박으면 OMX 같은 다른 제품에 틀린 정책이 간다.
- 끈 기기가 다시 준비되기 전에 바퀴가 움직이면 안 된다(LiDAR 스핀업 약 2 s). 깨우는 명령이 기기에 닿지 않았을 때도 마찬가지다.
- 사용자는 운영 중 Fleet에서 로봇을 재우고 깨울 수 있기를 원한다(2026-10-04).

### Decision

1. **제품이 기기를 선언한다.** 로봇 패키지 `core.yaml`의 `power.device_policy.devices.<기기>`에 `idle`·`standby`(각 `on`·`reduced`·`off`), `wake_ready_s`, `required_for_motion`을 적는다. 선언되지 않은 기기는 모든 모드에서 켜져 있다. Pinky Pro(`middleware/devices/pinky/profile/config/core.yaml`)는 `lidar`(STANDBY off, 2.0 s, 주행 필수)·`camera`(STANDBY off, 3.0 s)·`perception`(IDLE reduced, STANDBY off, 0.5 s)을 선언한다. OMX는 아무것도 선언하지 않는다. `reduced` 인식은 네 틱에 한 번 분류한다(`perception/nodes/camera_power_gate.py`의 `REDUCED_EVERY`, 틱의 주인인 노드 쪽 값이다). 2.0 s는 PWR-005의 추정값이고 3.0 s는 `camera_settle_seconds` 2.5 s에 첫 프레임을 더한 값이다. 둘 다 벤치 §8에서 실측으로 고친다.
2. **한 벤치 스위치.** `power.device_policy.enabled`(기본 false)가 꺼져 있으면 모든 기기는 켜진 채이고 아무 명령도 나가지 않는다. 기기 항목의 `enabled: true|false`가 그 기기에 한해 스위치를 덮는다(로봇별 오버레이에서 한 기기만 시험할 때). 두 스위치는 YAML 불리언만 받는다. 옛 `power.lidar.standby_stop: true`는 lidar 항목의 기기별 스위치로 읽는다. 블록이 잘못 적혀 있으면 CORE는 오류를 남기고 정책을 끈 채(모든 기기 켜짐) 뜬다. 절전 옵션의 오타로 API·E-Stop·배터리 감시가 내려가면 안 되기 때문이다.
3. **시간은 프로필 하나, 로봇별 덮어쓰기.** `idle_after_s`·`standby_after_s`·`wake_ready_s`는 기본값(`rosy_default.yaml`)과 로봇 패키지가 정하고, 로봇 한 대는 CORE 오버레이(`~/.rosy/rosy.yaml`, 로봇에서는 `/var/lib/rosy/core/.rosy/rosy.yaml`)로 덮는다. 새 설정 층을 만들지 않는다.
4. **정책과 적용을 나눈다.** `core_features.power`(ROS 무의존)는 기기별 수준과 준비와 `motion_ready`를 낸다. 적용은 기기마다 `DevicePowerPort` 하나다(`middleware/core/gateway/core/bridge/device_power.py`). LiDAR는 `start_motor`/`stop_motor` 서비스, 카메라·인식은 latched `power/devices` JSON 보드를 `camera_detect_node`(`CameraPowerMixin`)가 따른다. 수준이 바뀔 때만 보내고, 닿지 않으면 latch 없이 다음 틱에 다시 보낸다.
5. **주행 준비 게이트와 확인.** 최종 `cmd_vel` 주기(`cmd_vel_cycle`)는 `motion_ready`가 정확히 `True`가 아니면(False, 다른 값, 예외) 고른 값 대신 0을 낸다. 게이트는 값을 0으로 누를 수만 있다. E-Stop·워치독·먹서 선택(`select_output`), 50 Hz 발행, 발행 뒤 SAF-002 알림 순서는 바뀌지 않는다. D-442가 말하는 준비 HOLD의 하나이고, 값은 여전히 `GuardedMotion`과 `PinkyTwistPort`를 거쳐 나간다.
   - 꺼졌다 켜진 기기는 **`wake_ready_s`가 지나고, 깨운 뒤 확인 보고가 온 뒤에만** 준비된다. 시간만으로는 준비되지 않는다. LiDAR의 확인은 CORE가 받은 스캔이고(`power/device_ready` 토픽으로는 확인하지 않는다), 카메라·인식의 확인은 노드가 워밍업 뒤 `power/device_ready`에 내는 `{device, ready}`다.
   - 켜는 명령이 실제로 나간 시각부터 `wake_ready_s`를 다시 세고, 그 전에 온 보고는 버린다. 꺼져 있는 동안 온 보고도 버린다.
   - 정책이 움직이는 기기는 CORE가 뜰 때도 확인을 기다린다. CORE가 절전 중에 다시 떴다면 기기가 꺼져 있을 수 있어서, 브리지는 그 기기의 수준을 한 번 다시 보낸다. 정책이 움직이지 않는 기기는 예전처럼 처음부터 준비된 것으로 본다.
   - 옛 `power.lidar.standby_stop: true` 로봇도 정책이 움직이는 기기를 가진 로봇이다. CORE가 뜰 때마다 `start_motor`를 한 번 받고, 첫 스캔과 `spinup_s` 전에는 바퀴가 0이다. 이미 도는 LiDAR가 그 호출을 무해하게 받는지는 벤치 §8에서 본다. 이 값을 켠 YAML은 저장소에 없다.
   - 받아들여진 명령은 D-24 개정의 `on_command`로 로봇을 깨우고, 준비가 끝나면 움직인다.
6. **Fleet은 CORE 전원 API만 부른다.** 콘솔은 로봇 카드에 전원 모드를 보이고(깨운 뒤 준비 중이면 `준비 중`), `POST /api/fleet/robots/{robot_id}/power {action: sleep|wake}`를 로봇의 `/api/v1/power/mode`(STANDBY)·`/api/v1/power/wake`로 그대로 보낸다. 이름 있는 운영자만 부른다(D-540 9). IDLE이 아닌 로봇을 재우지 못하는 인터록은 CORE가 판정한다.
7. **바퀴 토크 해제는 이 ADR 밖이다.** STANDBY에서 모터 드라이버(Pinky 바퀴, OMX 팔) 토크를 끄는 일은 정지 유지·자세 유지·재기동 안전을 따로 따져야 하므로 후속 ADR로 다룬다.

### D-427·D-429·D-430·D-442와의 관계

| ADR | 관계 |
|---|---|
| D-427 (이동 규칙) | 새 최상위 폴더 없음. 새 파일은 기존 패키지 안(`core_features/power`, `core/bridge`, `core_api_web/api`, `perception/nodes`, `fleet/server`)에만 둔다 |
| D-429·D-442 (DeviceControlPort) | 다른 포트다. DeviceControlPort(`PinkyTwistPort`)는 단일 writer의 **동작 출력** 포트이고, DevicePowerPort는 센서 기기의 **전원 수준** 포트다. 전원 포트는 동작 출력을 쓰지 않으며 cmd_vel writer가 될 수 없다. 전원 정책이 바퀴에 닿는 길은 `motion_ready` 하나이고 0으로 누르기만 한다 |
| D-430 (safety 분리) | `core_features.power`는 command·safety를 import하지 않는다(시험이 확인). safety 태그 파일 `core/bridge/cmd_vel.py`와 `core/system/power.py`의 변경은 독립 리뷰와 `Safety-Review:` trailer를 받았다. `power/manager.py`·`power/devices.py`·`bridge/device_power.py`를 safety 태그에 넣을지는 열려 있다(후속 4) |
| D-400 (안전 정책) | 바뀌지 않는다. 꺼진 LiDAR는 스캔을 내지 않고 꺼진 카메라는 `camera/blocked`를 true로 낸다. 낡은 스캔·프레임을 "비어 있음"으로 읽는 경로를 더하지 않는다 |

### Consequences

- 스위치가 꺼진 지금은 동작이 바뀌지 않는다. 상태에 `devices[]`·`motion_ready`가 더해지고, 이벤트 `power.device_changed`가 생긴다.
- 스위치를 켜면 STANDBY에서 LiDAR 모터와 카메라 캡처가 멈추고, IDLE에서 인식이 1/4로 준다. 깨운 직후 약 2 s 동안, 그리고 CORE가 뜬 뒤 첫 스캔과 2 s가 지나기 전까지 바퀴는 0이다. 깨우는 명령이 닿지 않거나 LiDAR가 스캔을 내지 않으면 바퀴는 계속 0이다(`GET /api/v1/power`의 `motion_ready: false`).
- 확인은 래치다. 확인한 뒤 죽은 LiDAR를 이 게이트가 다시 잡지는 않는다. 그 일은 기존 스캔 신선도 검사(라인 추종 몸체 정지, D-400)의 몫이다.
- 카메라는 꺼졌다 켜지면 잠금·워밍업을 다시 하므로 그동안 `camera/blocked`가 true다. 라인 추종은 그동안 서 있다. 카메라는 주행 필수 기기가 아니므로 LiDAR가 먼저 준비되면 게이트는 풀린다. 카메라에 기대는 주행은 기존 프레임 신선도 규칙이 붙든다.
- 절전 인터록은 로봇 모드 IDLE이다. CORE는 모드를 상태 틱에서 전원 정책에 넘기므로, 모드가 바뀐 직후 한 틱 사이에 STANDBY로 내려갈 수 있다. 그 사이 주행 필수 기기는 `off`라서 바퀴는 0이고, 손해는 LiDAR가 한 번 섰다 도는 것이다.
- Nav2가 스캔 단절을 어떻게 받는지, 실제 스핀업·카메라 준비 시간이 선언값과 맞는지는 벤치(§8)에서만 알 수 있다.

### 후속

1. 벤치 §8 통과 → `power.device_policy.enabled: true` 커밋(독립 리뷰).
2. **토크 해제 ADR:** STANDBY 바퀴·팔 토크 off, 재기동 순서, 경사·팔 자세 유지.
3. 다른 제품(OMX) 기기 선언.
4. `power/manager.py`·`power/devices.py`·`bridge/device_power.py`의 safety 태그 여부(D-430 매니페스트 결정).
5. 게이트가 바퀴를 붙든 이유를 운영자 화면에 문장으로 보이기(지금은 `motion_ready`와 Fleet 카드의 `준비 중`).

**References:** [D-24](D-24-.md), [D-25](D-25-standby-pi-5.md), [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-430](D-430-safety-as-a-separate-concern.md), [D-442](D-442-motion-intent-and-device-control-port.md), [벤치 절차](../deployment/power-bench-verification.md)
