# 램프 운용 모드 표시 설계 — D-380 (2026-09-30)

한눈에: Pinky의 램프·LCD는 D-260의 다섯 건강 상태(부팅/실패/주의/준비-못움직임/준비)만 말하고, 운용 모드(MANUAL/NAVIGATION/DOCKING/EMERGENCY)는 대시보드에만 존재했다. 이 설계는 모드를 물리 표시로 끌어온다. 결정 기록은 `docs/adr/D-380-lamp-mode-patterns-from-core-status-inputs.md`.

## 데이터 흐름

```
CORE StateManager.snapshot().mode        (RobotMode: IDLE/MANUAL/NAVIGATION/DOCKING/EMERGENCY)
  └─ 10 s마다 api/v1/host.py status_inputs() → /run/rosy/status-inputs.json (+robot_mode)
       └─ rosy-boot-status (root) 검증·복사 → /run/rosy-boot/boot-status.json (+robot_mode)
            └─ rosy-boot-display (rosy-display) 1 s 폴링
                 ├─ robot_state.lamp_pattern(state, mode) → lamp_pattern 헬퍼 (패턴 교체, 무음)
                 └─ robot_state.mode_suffix(mode) → LCD 상태줄 "Ready - NAVIGATION"
```

- CORE가 죽으면 핸드오버가 60초 안에 무효가 되어(D-260 M1 규칙) 모드 표시도 사라진다 — 건강 패턴만 남는다.
- 모르는 모드 문자열은 경보 임계·장치 행과 달리 나머지를 버리지 않고 없음이 된다(ADR 참조).

## 표시 우선순위 (규칙표가 소유)

| 우선 | 조건 | 램프 패턴 | 색·리듬 |
|---|---|---|---|
| 1 | 부팅 실패 (FAILED) | `failed` | 빨강 1 Hz |
| 2 | EMERGENCY (e-stop) | `emergency` | 빨강 4 Hz — 실패의 4배 속도 |
| 3 | 주의 (배터리 경보·장치 무응답·SETUP) | `caution` | 주황 0.5 Hz |
| 4 | 부팅 중 (CORE_READY 전) | `booting` | 파랑 호흡 2 s |
| 5 | DOCKING | `docking` | 마젠타 1 Hz |
| 6 | NAVIGATION | `navigating` | 청록 호흡 4 s |
| 7 | MANUAL | `manual` | 흰색 호흡 3 s |
| 8 | IDLE / 준비 | `ready` | 초록 3 s 후 소등 |

부저는 변함 없이 건강 상태 전환에만(준비 1회·실패 3회·주의 저음 2회). 모드 전환은 조용하다.

## 바뀐 파일

| 파일 | 역할 |
|---|---|
| `src/contracts/foundation/core_common/robot_state.py` | `ROBOT_MODES`, `OPERATING_MODES`, `MODE_LAMP`, `valid_robot_mode()`, `mode_suffix()`, `lamp_pattern()`; `evaluate()`가 `robot_mode`를 검증해 결과에 실음 |
| `src/runtime/api_web/core_api_web/api/v1/host.py` | `status_inputs()`에 `robot_mode` 추가 (덕타이핑 `_robot_mode()`) |
| `deploy/robot/pinky_pro/native/rosy-boot-status.py` | 핸드오버 검증·`status_record`에 `robot_mode` 추가 |
| `deploy/robot/pinky_pro/native/rosy-boot-display.py` | `read_view`·`_state_view`·`BootDisplay.lamp_pattern_for`/`step()` — 패턴 교체는 매 폴링, 무음 |
| `src/products/pinky_pro/lamp/src/lamp_pattern.c` | 패턴 4종 + `known()` + usage |

## 검증

- 호스트: `test_robot_state.py`(우선순위 전 표), `test_host_status_summary.py`(핸드오버 키·검증), `test_boot_status_indicator.py`(레코드), `test_boot_display.py`(패턴 선택·무음 전환·LCD 접미·C 이름 동기). 변이 증명 4종.
- 기기(별도 DEVICE 단계): hardware 모드에서 모드별 패턴 확인, CORE 정지 60 s 후 모드 표시 소멸, EMERGENCY에서 실패 빨강과 속도 구분 확인.

## 뒤따를 일 (이 설계에 없음)

- NAVIGATION 세부 상태(PLANNING/BLOCKED 등)의 물리 표시 — `NavigationState`까지 넘기면 되지만 우선 RobotMode만.
- 부저의 EMERGENCY 진입음 — 모드 전환 무음 원칙과 충돌하므로 제품 정책이 먼저.
- 대시보드 요약줄에 모드 병기 — 대시보드는 이미 `state.mode`를 따로 보여준다.
