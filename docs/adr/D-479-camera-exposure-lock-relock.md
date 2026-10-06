## D-479 카메라 AE/AWB 잠금은 한 번이 아니라, 잠긴 노출이 길 위를 못 쓰게 만들면 다시 건다

**Status:** Proposed (2026-10-06; 코드와 호스트 pytest까지. DEVICE 검증은 별도). 잠금 자체를 정한 별도 ADR은 없다. 이 문서가 잠금 결정의 기록 자리를 처음 만든다. 근거는 `camera_controls.py` 모듈 docstring과 `config/camera.yaml`의 주석이다.

잇는 결정:
- D-48: 카메라 worker와 telemetry. 이 결정은 그 계약을 바꾸지 않는다.
- D-476: 차선을 잃을 때의 bridge. `low_light`/`overexposed`는 CORE가 `CAMERA_LINE`을 멈추는 사유다.

### Context

- 카메라 노드는 시작 뒤 `camera_settle_seconds`(2.5 s) 동안 AE/AWB를 켜 두고, 그 값으로 ExposureTime, AnalogueGain, ColourGains를 고정한다. 바닥색 기준이 ISP와 싸우지 않게 하려는 결정이고 근거 측정은 `camera_controls.py`에 있다.
- 잠금은 프로세스 수명에 한 번뿐이었다. 2026-10-06 rosy_26(9dfk)이 01:30 UTC 어두운 곳에서 시작해 exposure=66640us gain=8.000으로 잠겼고, 몇 시간 뒤 보통 실내광에서 길 띠(rows 35-95 %, cols 10-90 %)의 47-71 %가 247 초과로 포화했다(중앙값 225-253). CORE의 camera quality가 `overexposed`를 보고해 `CAMERA_LINE`이 멈췄고 차선 모델이 바닥을 벽으로 읽었다.
- `systemctl restart rosy-camera`가 exposure=54258us gain=2.000으로 다시 잠갔고 포화는 0 %가 됐다(중앙값 103-140). 잠금이 한 번뿐인 것이 구조적 결함이다.
- `visibility_reason`(`camera_visibility.py`)은 지금까지 `line_observer_node`에서만 불렸다. 카메라 노드는 자기 프레임의 노출 사유를 몰랐다.

### Decision

**1. 잠긴 상태에서 사유가 `overexposed` 또는 `low_light`로 `camera_relock_dwell_s` 동안 이어지면 settle -> lock을 다시 돈다.**
- 카메라 노드가 잠금이 확정된 동안 매 프레임 `visibility_reason`을 부르고, 순수 로직 `RelockWatch`(`camera_controls.py`)가 판단한다. `usable`이나 다른 사유가 한 프레임이라도 끼면 dwell을 처음부터 센다. 밝은 프레임 하나로는 다시 걸지 않는다.
- 재잠금 사이는 `camera_relock_min_interval_s` 이상이다. 조건이 계속되면 간격이 지나자마자 한 번 더 건다.
- 파라미터(`config/camera.yaml`, 노드 기본값 동일): `camera_relock_dwell_s: 3.0`(0이면 재잠금 끔), `camera_relock_min_interval_s: 30.0`.

**2. 재잠금 방식은 기존 settle -> lock 순서 그대로다. `AeEnable`/`AwbEnable`은 보내지 않는다.**
- picamera2: `configure()`가 컨트롤을 버리므로 카메라를 멈췄다가 `_start_cam()`으로 다시 연다. 처음 시작과 같은 경로라 AE/AWB가 다시 켜지고 `camera_settle_seconds` 뒤에 `lock_controls`가 새 값을 고정한다.
- V4L2(OpenCV) 경로: 장치 재오픈은 드라이버가 수동 노출을 기억하면 소용없으므로 `unfreeze_v4l2_controls`로 auto exposure/WB를 돌려놓고 같은 settle 대기를 건다.
- 재시작 동안 `/camera/controls`는 `settling`이다. `line_observer_node`의 `require_camera_controls_stable` 게이트가 그동안 `CAMERA_LINE`을 내지 않는다. 새 잠금이 확정되면 바닥 기준과 정책이 다시 부트스트랩된다(`_announce_lock`). 새 값은 `camera controls ...` 로그와 `/camera/controls`에 남는다.

**3. 움직임 신호는 쓰지 않는다.**
- 카메라 노드는 odom이나 cmd_vel을 구독하지 않는다. 구독을 새로 붙이지 않고 dwell과 최소 간격으로 대신한다.
- 재잠금이 걸리는 때는 CORE가 이미 `low_light`/`overexposed`로 `CAMERA_LINE`을 멈춘 때다. 그래서 재시작 공백이 추가로 끊는 것은 없다.

**4. 저조도 램프 보조(lamp assist)는 건드리지 않는다.**

### Consequences

- 어두운 곳에서 켜졌다가 밝은 곳으로 옮겨진 로봇이 서비스 재시작 없이 복구한다.
- 정말 어두운 곳에서는 `low_light`가 계속된다. 그 경우 30 s마다 settle 공백(약 3 s)이 한 번 생긴다. AE가 같은 값을 다시 고를 뿐이다. 이 비용이 거슬리면 간격을 늘린다.
- 길 띠가 95 % 미만으로 포화한 경우(47-71 %)는 `visibility_reason`이 `usable`이라 재잠금 대상이 아니다. 임계값 `0.95`는 이 결정에서 바꾸지 않는다. 2026-10-06 관측이 그 구간에서도 차선을 망쳤다면 임계값 조정은 별도 결정이다.
- 재시작 뒤 picamera2가 다시 열리지 않으면 카메라 노드는 `_cam=None`으로 `blocked=True`를 낸다. 처음 시작 실패와 같은 상태이며 프로세스 재시작이 복구다.

### Validation / Transition

- SOURCE: `test_camera_controls.py`(RelockWatch: dwell, 단일 프레임, 사유 두 가지, 최소 간격, 0이면 끔), `test_camera_detect_region_range.py`(가짜 카메라 노드: 지속 시 정확히 한 번 재시작, 한 프레임은 무시, 잠금 전에는 무시). 호스트 pytest이며 장치 증거가 아니다.
- DEVICE(미완): 실제 picamera2에서 `Picamera2()` close 뒤 재오픈이 안정적인지, 어두운 시작 -> 밝은 곳 이동에서 dwell 안에 재잠금과 `usable` 복귀가 되는지, 재잠금 시간(`settling` 구간 길이)과 CPU, 반복 재잠금에서 장치 누수가 없는지, V4L2 `AUTO_EXPOSURE` 값 3.0이 실제 카메라에서 받아들여지는지.

### Addendum

(추가만 한다. 이 결정을 고칠 때는 아래에 날짜와 함께 덧붙인다.)

**2026-10-06 (같은 날 추가, 결정 1의 트리거 보강):** 처음 트리거는 `visibility_reason`이 `overexposed`/`low_light`일 때만 걸었다. 실제 사고는 그 기준 아래였다. rosy_26의 길 띠(rows 35-95 %, cols 10-90 %)는 247 초과 포화가 47-71 %, 중앙값 225-253이었고, `visibility_reason`은 이를 `usable`로 본다(`overexposed`는 95 % 초과). 그런데 차선 모델은 바닥을 벽으로 읽었다. 그래서 `RelockWatch`의 "나쁨"을 다음 중 하나로 넓힌다. 같은 dwell(3 s)과 최소 간격(30 s)을 그대로 쓴다.
- `visibility_reason`이 `overexposed` 또는 `low_light` (기존).
- 길 띠의 포화 비율(>247)이 `camera_relock_clip_fraction`(기본 0.30) 이상.
- 길 띠 중앙값이 `camera_relock_bright_median`(기본 235) 이상.

`visibility_reason`과 CAMERA_LINE의 95 % 유효 기준은 바꾸지 않는다. 길 띠 통계는 `camera_visibility.road_clip_stats`가 같은 행/열 범위에서 읽는다. 파라미터는 `config/camera.yaml`과 노드 기본값(`RELOCK_CLIP_FRACTION`, `RELOCK_BRIGHT_MEDIAN`)에 있다.

사고 수치(2026-10-06, rosy_26/9dfk): 01:30 UTC 어두운 곳에서 시작해 exposure=66640us gain=8.000으로 잠김 -> 실내광에서 길 띠 포화 47-71 %, 중앙값 225-253 -> `systemctl restart rosy-camera` 뒤 exposure=54258us gain=2.000으로 다시 잠김 -> 포화 0 %, 중앙값 103-140.

DEVICE(미완): 0.30과 235는 이 한 건의 구간(47-71 %, 225-253 대 0 %, 103-140)에서 정했다. 정상 밝은 장면(흰 선이 많은 길, 밝은 바닥)에서 오탐 재잠금이 없는지 실기 프레임으로 확인해야 한다. 소스 요약의 "Consequences" 중 95 % 미만 포화가 대상이 아니라는 문장은 이 보강으로 대체된다.
