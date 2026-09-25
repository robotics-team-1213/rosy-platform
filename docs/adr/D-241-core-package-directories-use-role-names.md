## D-241 core 계열 폴더는 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다

**Status:** Accepted (2026-09-25).

잇는 결정: [D-231](D-231-layered-source-roots-keep-package-names.md)의 자리.
패키지 이름을 유지한다는 그 결정의 문장은 그대로다. 이 결정은 그 패키지의 **디렉터리**만 역할로 읽히게 한다.

**Context:**

1. D-231 이후에도 폴더가 `core`, `core_events`, `core_features`, `core_api_web`, `core_common` 이라서, 층으로 나눠 둔 패키지가 옛 `src/core` 묶음처럼 보인다.
2. `ros2 run core`, `import core`, `import core_common`, systemd 의 `install/lib/core/core` 는 이미 장치에 깔린 이름이다. 폴더를 역할로 바꿔도 이 이름은 바꾸지 않는다.

**Decision:**

1. **디렉터리만 역할 이름이다.** `package.xml` 의 `<name>` 과 파이썬 패키지 디렉터리(`core/`, `core_common/`, `core_events/`, `core_features/`, `core_api_web/`)는 유지한다.

   | 패키지 이름 | 디렉터리 |
   |---|---|
   | `core` | `src/runtime/gateway` |
   | `core_events` | `src/runtime/events` |
   | `core_features` | `src/runtime/features` |
   | `core_api_web` | `src/runtime/api_web` |
   | `core_common` | `src/contracts/foundation` |

2. **설치 이름과 import 는 그대로다.** `ros2 run core core`, `from core_common...`, `from core_features...` 는 바꾸지 않는다.
3. **다른 패키지는 이 규칙에 넣지 않는다.** `control`, `navigation`, `interfaces` 는 폴더 이름이 이미 패키지 이름과 같다.

**Consequences:**

- 구조 시험은 이 다섯 패키지만 폴더 이름과 패키지 이름이 달라도 통과한다.
- 소스 경로를 찾는 시험과 도구는 위 표를 쓴다.

**Validation:** `python -m pytest test/architecture/test_module_structure.py test/architecture/test_target_layout.py src/runtime/gateway/test/test_core_logic.py src/contracts/foundation/test -q`.
