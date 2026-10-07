## D-502 배터리 정지는 SAF-001 E-Stop이다: EMERGENCY로 들어가고 관리자 해제로만 풀린다. 배터리 입력의 결측·낡음은 API에 드러낸다

**Status:** Accepted (2026-10-07, 사용자 지시 "api 나 기타 health 나 이런거에도 제대로 규약으로 해서 기록하고 처리해". 브랜치 `fix/core-battery-health`. 자동 해제는 고르지 않았다. 아래 Decision 3과 Open 1을 본다)

잇는 결정: SRS SAF-001(E-Stop, Administrator 해제)·SAF-005(저배터리 정책) · [D-27](D-27-d-25-halt.md)(Deep 셧다운 센티넬) · [D-192](D-192-hardware-runtime-in-the-image.md) 4항(제품 그래프의 배터리 토픽은 `battery/voltage`뿐, `sensor_adc`/`batt_state`는 벤치 전용) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 경로 변경 통제) · D-82 Law 0(결측은 0%가 아니다)

### Context

1. 2026-10-06 8kcn(`rosy_60`): 팩이 6.2 V까지 떨어졌다(rosy-io bringup 경고 15:21:00 6.20 V, 15:21:56 6.77 V). CORE의 SAF-005 Critical 정책 `RETURN_HOME`은 위치가 확정되지 않아 보낼 수 없었고, 규칙대로 E-Stop(`source: battery_policy`)으로 올라갔다. 정지 자체는 옳았다.
2. 그 뒤 충전으로 `battery/voltage`가 8.63 V가 되었어도 `GET /safety/state`는 `estop: true`였고, `POST /safety/release`는 409 `MODE_CONFLICT "not in EMERGENCY"`였다. 원인: `bridge/battery_policy.py`는 `safety.trigger_estop()`만 부르고 모드를 EMERGENCY로 바꾸지 않았다. API `POST /safety/stop`과 control 정책 경로(`command/manager.py`)는 둘 다 바꾼다. 해제는 EMERGENCY만 받는다(`arbitration.release_emergency`). 결과적으로 CORE를 재시작하는 것 말고는 풀 방법이 없었다.
3. 같은 날 9dfk(`rosy_26`, 현재 main)와 8kcn 모두 `GET /sensors/battery`가 404 "no data yet"였다. `battery` 센서 표본을 쓰는 곳은 `batt_state`(BatteryState) 콜백 하나였는데, D-192 4항에 따라 제품 그래프에는 `batt_state` 발행자가 없다. 정책 경로(`battery/voltage` → `BatteryMonitor`)는 정상이었지만 센서 API에는 끝내 보이지 않았다.
4. SRS SAF-005는 배터리 정지를 어떻게 푸는지 말하지 않는다. SAF-001은 "해제는 Administrator 권한"만 말한다.

### Decision

1. **모든 E-Stop 래치는 EMERGENCY다.** 누가 래치하든(API, control 정책, `battery_policy`, `battery_deep`, 이후의 어떤 경로든) `SafetyManager`의 E-Stop 리스너 하나가 모드 기계를 EMERGENCY로 옮긴다(`core/services.py` `reflect_stop`). `estop: true`인데 모드가 EMERGENCY가 아닌 상태는 없어야 한다.
2. **배터리 정지의 해제 경로는 SAF-001과 같다.** Administrator의 `POST /api/v1/safety/release`. 새 엔드포인트나 배터리 전용 해제는 만들지 않는다.
3. **자동 해제는 하지 않는다(보수적 선택).** 전압이 회복되어도 래치는 그대로다. 근거: (a) 충전 중 전압은 실제 잔량보다 높게 읽힌다(로봇에 전류 센서가 없다, SAF-005). (b) 운동을 다시 허용하는 결정은 사람이 상태를 보고 내린다는 SAF-001의 원칙. 해제 판단을 돕기 위해 `GET /safety/state`의 `battery`에 지금의 근거를 싣는다(4항).
4. **해제는 배터리 정책을 끄지 않는다.** 해제 뒤에도 같은 정책이 그대로 돈다. Deep 단계가 이어지면 다음 표본에서 다시 래치한다(`battery_deep`). Critical은 단계가 바뀔 때만 동작하므로(기존 SAF-005 규칙) 해제 직후 같은 Critical에서는 다시 래치하지 않는다. 그것은 관리자의 판단으로 본다.
   **해제 뒤에는 새 명령 없이 움직이지 않는다.** E-Stop은 대기 중인 배터리 도크 복귀(DNC-006, WARNING에서 무장)를 지우고, 배터리가 OK로 돌아올 때까지 다시 무장하지 않는다(`DockingManager.on_estop`). 해제 직후 로봇을 움직이는 것은 운영자의 새 명령(도킹 명령 포함)뿐이다.
5. **배터리 입력의 결측·낡음은 API에 드러낸다(추가 필드, API Ref v1.120).**
   - `battery/voltage`(Float32) 표본이 `battery` 센서 표본이 된다: `{voltage, received_at, source: "battery/voltage"}`. `batt_state`가 있는 벤치 구성은 그 표본이 덮어쓴다(기존 필드 유지).
   - `GET /api/v1/sensors/battery`는 404 대신 200과 `evidence`(`missing`/`fresh`/`stale`), `sample_age_s`, `stale_after_s`를 싣는다. 판정은 `GET /power/health`의 `battery`와 같은 `BatteryMonitor.health()`다. 표본이 없으면 `voltage`·`received_at`·`source`는 `null`이다(D-82 Law 0: 결측은 0이 아니다). 다른 센서의 404는 그대로다.
   - `GET /api/v1/safety/state`의 `battery`에 `evidence`, `sample_age_s`, `level`(`ok`/`warning`/`critical`/`deep`), `percent`를 더한다.

### Consequences

- 8kcn 같은 상황에서 관리자가 `safety/state`의 `battery.evidence: "fresh"`, `level: "ok"`를 보고 해제할 수 있다. CORE 재시작이 필요 없다.
- 배터리 정지 뒤 로봇은 EMERGENCY다. 상태 스냅샷·대시보드·Fleet이 보는 모드가 래치와 일치한다.
- 이 수정이 배포되기 전의 로봇(payload ≤ 2026.10.07-051)은 여전히 배터리 래치를 API로 풀 수 없다. 그때의 절차는 `rosy-core` 재시작이며, 재시작 직후 전압이 Critical 이하이면 다시 래치한다.
- 호스트 pytest만 확인했다. 장치 수용은 아니다.

### Open

1. 자동 해제(신선한 표본이 임계 + 히스테리시스 위로 N회)는 고르지 않았다. 필요하면 사용자가 정하고 이 ADR을 고친다.
2. `battery-shutdown-request.json` 센티넬은 CORE가 자기가 쓴 것만 지운다. 재시작 전에 남은 파일은 호스트 스크립트가 900 s 신선도 검사로 무시한다(`rosy-lowbatt-shutdown.sh`). 이번 변경은 이 경로를 바꾸지 않았다.
