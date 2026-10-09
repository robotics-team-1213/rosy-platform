## D-596 LED 신원 확인을 켠다 — 서 있는 로봇도, 색마다 동시에, Fleet이 스스로 요청한다

**Status:** Proposed (2026-10-10, 사용자 결정 "LED 색상이나 LED 켜짐으로 찾는 로직도 활성화하는 걸로 해"). SOURCE 변경과 호스트 테스트, 현장 프레임 재생만이다. 사이트 배포와 현장 LED 판정 수용은 이 기록이 하지 않는다.

잇는 결정: [D-472](D-472-rosy-cam-map-and-lamp-identity.md)(LED 점멸 신원, 이 결정이 4항의 "동시에 한 대"와 addendum 5항의 "움직이는 로봇에 한 대씩"을 고친다) · [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(마커 우선, 무마커 blob) · [D-539](D-539-tracking-background-survives-restart.md)·[D-547](D-547-tracking-baked-robot-guess-and-ghost-heal.md)(배경 유지, 배경에 박힌 로봇 추정과 유령 치유) · [D-433](D-433-one-face-process-owns-lcd-buzzer-lamp.md)(rosy-face가 램프 단독 소유) · [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md)(확인 트랙의 쓰임). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- 천장 카메라 신원은 상단 ArUco 마커가 먼저다. 가림(케이블·기둥), 비스듬한 시야, 반사, 두 로봇의 근접으로 마커를 못 읽으면 blob은 익명으로 남는다. 2026-10-10 06:46 현장에서 `rosy_40`은 `MARKER`, `rosy_41`은 `NO_POSE`였다.
- 지금 LED 확인은 쓰이지 못한다.
  - `operations/fleet/fleet/server/identity.py`(이 결정 전): 한 번에 한 요청(`IDENTIFY_BUSY`), 6 s 창과 2 s 판정 유예, 움직이지 않는 로봇은 409 `IDENTIFY_NOT_MOVING`, `auto_request` 기본 false. 현장 2026-10-10 06:48에 서 있는 `rosy_40` 요청은 409 `IDENTIFY_NOT_MOVING`이었다.
  - `operations/vision/rosy_vision/track/led_identity.py`(이 결정 전): `min_off_s` 0.5, `max_gap_s` 0.7. 현장 카메라는 2.5–2.7 fps다(`/api/fleet/tracking` fps 2.7, 직접 받은 프레임 간격 중앙값 0.37 s, 90 % 0.71 s, 최대 0.76 s). 6 s 창 안에 0.7 s를 넘는 간격이 하나만 있어도 `frames_missing`이다.
  - 현장 프레임 재생(`X:\DevTemp\led-identify\field`, 실제 프레임 시각·영상·`rosy_40` 위치에 후면 램프 빛 12×28 px를 그려 넣음, 6 s 창 264개): 이전 값은 6/264 `matched`(나머지 `frames_missing`), 새 값은 264/264. 빛을 그리지 않은 대조 264개는 둘 다 0 `matched`.
- 로봇 쪽은 막히지 않았다. 2026-10-08 배터리 절약으로 두 로봇의 `/etc/rosy/boot-display.env`가 `ROSY_LAMP_ENABLED=false`다(2026-10-10 읽기 확인). `rosy-face`의 식별 점멸은 이 값과 상관없이 램프를 잠시 쓰고 다시 끈다(`deploy/robot/pinky_pro/native/rosy-face.py` `Lamp.available(for_identify=True)`·`Lamp.identify`의 `resume`; `test/test_rosy_face.py::test_identity_pulse_temporarily_uses_a_disabled_normal_lamp`). `rosy-hw-test`의 `run_identify`도 그 값을 보지 않는다.
- 배경 모델은 학습이 끝나면 학습률 0으로 얼어 있다(`background_blob.py` `detect`의 `learningRate=0`). 서 있는 로봇이 배경으로 흡수되는 길은 학습 중 프레임, 장면 변경 뒤의 다시 학습, D-547 유령 치유다.

### Decision

1. **서 있는 로봇도 확인한다.** Fleet은 움직임을 요구하지 않고 로봇에 이동을 명령하지 않는다. Vision은 열린 확인 창이 끝날 때까지 그 source의 배경을 얼린다: 학습 프레임을 받지 않고(학습은 창 뒤로 미룬다), 장면 변경은 그 프레임만 버리고 다시 학습을 시작하지 않으며, 유령을 확정·치유하지 않는다. 배경에 박힌 로봇(D-547 추정)의 자리가 램프 빛으로 전경이 되어도 바닥색이 아니면 그 추정을 그대로 보고하고 빛 blob을 두 번째 로봇으로 세지 않는다.
2. **색마다 동시에.** 한 카메라 source에서 색(파랑·주황)마다 열린 요청 하나, 곧 최대 두 대가 동시에 확인한다. 이미 한 색이 쓰이면 Fleet은 두 번째 로봇에게 남은 색을 이름으로 요청한다. 같은 로봇이 확인 중이거나, 요청한 색이 쓰이는 중이거나, 두 색이 모두 쓰이면 `IDENTIFY_BUSY`다. 로봇이 쓰이는 색으로 답하면 수락하지 않는다. Vision은 열린 요청마다 판정 하나를 보낸다.
3. **Fleet이 스스로 요청한다.** `identity.auto_request` 기본값을 true로 바꾼다. 규칙(`operations/fleet/fleet/server/identity_triggers.py`):
   - `marker_missing`: 마커를 본 로봇의 마커가 `auto_marker_missing_s`(3 s) 넘게 안 보이고, 마지막 마커 자리(없으면 로봇 지도 자세) `auto_near_m`(0.5 m) 안에 익명 blob이 있다.
   - `split`: 두 blob이 겹쳐(`overlap`) 확인 트랙이 풀린 로봇 근처의 익명 blob이 다시 혼자(0.30 m 안에 다른 blob 없음)다.
   - `odom_reset`: 로봇이 보고한 자세가 odom 원점(0.05 m 안)으로 뛰었고(직전 0.3 m 밖) 카메라에 익명 blob이 있다.
   - 로봇마다 `auto_min_interval_s`(30 s)에 한 번. 상태가 신선하고 `safety.estop`이 정확히 false인 로봇만. 확인된 로봇, 확인 중인 로봇, 카메라 source가 보지 않는 로봇은 묻지 않는다.
4. **2–3 fps에서 읽히게.** 판정 `led-identity/2`: 측정한 꺼짐(앞 켜짐의 마지막 프레임부터 뒤 켜짐의 첫 프레임까지)은 램프의 실제 1 s 꺼짐보다 늘 길다. `min_off_s` 0.8 s(3 fps에서 한 프레임 깜빡임은 0.67 s로 거절), `max_off_s` 2.2 s, `max_gap_s` 1.1 s(2 fps에서 한 프레임 빠짐 허용). 점멸이 읽히지 않았어도 창의 모든 프레임에 익명 blob이 정확히 하나이고 그 blob이 꺼짐 프레임 뒤 연속 2 프레임 이상 그 색으로 켜지면 `matched`, `evidence.mode = "steady"`(정색 표시). 램프 패턴(1 s 켬·1 s 끔·1 s 켬)과 6 s 창은 그대로다.
5. **콘솔.** "LED로 찾기"는 서 있는 로봇에도 쓰이고 색은 Fleet이 고른다. 요청 뒤 창이 끝나면 결과(확인됨, 또는 이유)를 기록줄에 보인다. 주의 큐의 `CAMERA_NOT_SEEING`은 익명 blob이 보이면 LED 확인(`action.kind: identify`)을, 보이지 않으면 배경 다시 학습만 권한다.
6. **바뀌지 않는 것.** D-472 addendum 3: 확인 트랙은 D-511 입력과 콘솔 표시 전용이다. D-494 지도 자세 중재, trip, `initialpose`, 경로, 명령에 쓰지 않는다. D-472 5항: E-Stop·고장·주의·운행 상태 표시가 우선하고 `rosy-face`가 거절·중단한다. 로봇의 배터리 절약 기본값(`ROSY_LAMP_ENABLED=false`)은 그대로이고 식별할 때만 켰다가 끈다. API는 v1.181.

7. **자동 요청은 조용히, 주황은 조심해서** (2026-10-10 조정 지시).
   - 자동 요청은 호출음 없이 점멸한다: Fleet이 CORE `POST /host/lamp/identify?quiet=true`로 요청하고 CORE는 `identify_<색>_quiet`를 rosy-hw-test·rosy-face에 넘기며, rosy-face는 이때 `call` 소리를 내지 않는다. 운영자가 누른 "LED로 찾기"는 지금처럼 소리를 낸다. 이 로봇 쪽 변경은 다음 payload부터다. 이전 payload의 CORE는 쿼리를 무시하고 소리를 낸다(본문 스키마는 그대로라 거절은 없다).
   - 마커가 계속 안 보이는 로봇의 자동 요청 간격은 30 s → 2 min → 5 min으로 늘리고, 마커가 다시 보이면 처음으로 돌린다.
   - Fleet은 로봇의 램프 상태를 읽지 못하므로 주의(caution, 주황 1 s 켬·1 s 끔) 여부를 늘 모른다고 본다. 그래서 자동 요청은 파랑만 쓰고(파랑이 바쁘면 기다림), 운영자 요청도 기본은 파랑이며 주황은 파랑이 바쁠 때만 쓴다. 2항의 "자동 두 대 동시"는 이로써 운영자 요청에만 남는다.
   - Vision의 `matched` blob은 요청한 로봇의 마지막 천장 마커 자리(없으면 지도 자세)에서 `auto_near_m`(0.5 m) 안이어야 한다. 아니면 UNKNOWN `far_from_robot`. 예상 자리를 모르는 주황 요청은 UNKNOWN `no_prediction`. 다른 곳의 주의 상태 로봇은 이름을 얻지 못한다.

### 안전

- 로봇 쪽 변경은 7항의 소리 없는 동작 이름(`identify_<색>_quiet`)뿐이다. 점멸 소유, 안전 표시 우선, 요청 수명(`IDENTIFY_REQUEST_MAX_AGE_S` 1 s, `IDENTIFY_MAX_S` 3.5 s), CORE 쿨다운(`HW_TEST_COOLDOWN_S`)은 그대로다.
- 자동 요청은 바퀴·모드·E-Stop·localization을 바꾸지 않는다. E-Stop 중인 로봇에는 보내지 않고, 보내더라도 `rosy-face`가 거절한다.
- D-430 `Safety-Review:`는 자동 점멸이 운행 상태 표시를 잠시(3 s) 대신하는 빈도(로봇마다 30 s에 최대 한 번)에 대해 받는다.

### Consequences

- 마커를 놓친 로봇은 3 s 뒤부터 이름을 되찾을 수 있다. 서 있는 로봇도 같다.
- 자동 요청은 새 payload의 로봇에서 소리가 없다. 이전 payload의 로봇은 `call` 소리(두 번 삑)를 내고, 마커가 오래 가려지면 7항의 늘어나는 간격(최대 5 min)마다 울린다.
- 남은 위험과 열린 일:
  - 현장 LED 가시성은 아직 재지 않았다. 재생은 빛을 그려 넣었다. 서 있는 로봇의 실제 점멸 판정은 이 브랜치가 배포된 뒤 잰다.
  - `caution` 램프는 주황 1 s 켬·1 s 끔이라 주황 확인 점멸과 같다. 7항의 파랑 우선과 예상 자리 제한으로 막는다. 예상 자리 0.5 m 안에 주의 상태의 다른 로봇이 있으면 여전히 헷갈릴 수 있다(그때 두 blob이 0.30 m 안이면 겹침으로 거절).
  - 배경에 박혔는데 D-547 추정에도 잡히지 않은 로봇은 blob이 없어 LED로도 찾지 못한다(현장 2026-10-10의 `rosy_41`). 그때는 로봇을 매트 밖으로 옮긴 뒤 배경을 다시 학습한다.
  - 정색 표시는 점멸보다 약한 증거다. 익명 blob이 하나뿐일 때만 쓴다.
