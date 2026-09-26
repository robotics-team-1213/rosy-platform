## D-242 나머지 폴더도 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다

**Status:** Accepted (2026-09-25).

잇는 결정: [D-241](D-241-core-package-directories-use-role-names.md). 같은 규칙이다.
디렉터리는 역할을 말하고, `package.xml` 이름과 파이썬 import 는 유지한다.

**Context:**

1. `features` 는 역할을 말하지 않는다. 그 패키지는 게이트웨이 뒤의 명령·안전·판단·도킹 서비스다.
2. `control` 은 최종 `cmd_vel` 을 소유하지 않는다. 하는 일은 센싱·캘리브레이션·로컬 안전 정책이다.
3. `web_common` 의 common 은 `devices/common` 의 공용 칩과 다른 말이다. 이 패키지는 공용 브라우저 자산이다.
4. `emotion` 은 얼굴 LCD 다. `omx/omx_adapter` 는 계열 이름을 두 번 말한다. `lamp_control` 과 `sensor_adc` 의 control·sensor 접두는 드라이버 역할을 흐린다.

**Decision:**

1. **디렉터리만 바꾼다.**

   | 패키지 이름 | 디렉터리 |
   |---|---|
   | `core_features` | `src/runtime/services` |
   | `control` | `src/runtime/sensing` |
   | `web_common` | `src/hmi/web` |
   | `emotion` | `src/hmi/face` |
   | `omx_adapter` | `src/devices/omx/adapter` |
   | `lamp_control` | `src/devices/pinky_pro/lamp` |
   | `sensor_adc` | `src/devices/pinky_pro/adc` |

2. **그대로 둔다.** `bringup`, `led`, `imu_bno055`, `navigation`, `interfaces`, `description`, `gz_sim`, `fleet`, `games`, `gateway`, `events`, `api_web`, `foundation`. 폴더 이름이 이미 역할이거나 패키지 이름과 같다.
3. **import 와 설치 이름은 유지한다.** `import control`, `import emotion`, `ros2 pkg` 이름은 바꾸지 않는다.

**Consequences:** 구조 시험의 역할 표에 이 일곱을 더한다. 소스 경로를 찾는 시험과 도구는 위 표를 쓴다.

**Validation:** `python -m pytest test/architecture/test_module_structure.py test/architecture/test_target_layout.py src/hmi/face/test/test_info_screen.py src/hmi/web/test/test_ui_token_contracts.py src/devices/omx/adapter/test -q`.
