## D-231 소스 영역은 층으로 나눈다 — 디렉터리만 옮기고 패키지 이름은 그대로 둔다

**Status:** Accepted (2026-09-25). 목표 트리를 정한다. 폴더는 아직 옮기지 않았다.
이동은 아래 "이동 묶음" 조건이 갖춰진 뒤 한 번에 한다.

대체하는 것:
- [D-168](D-168-ros-package-structure-standard.md)의 영역 목록(`core`, `devices`, `products`, `face`, `navigation`, `sim`, `site`). 패키지 안의 모양 규칙은 그대로다.
- [D-227](D-227-ownership-names-stay-on-the-current-tree.md) 결정 1의 "새 영역 루트를 만들지 않는다". D-227의 나머지(명령 문, 안전, 학습 자리, 이름 규칙)는 그대로다.
- [D-207](D-207-one-owner-per-product-and-device-kind.md) 결정 5의 `signal/`·`dock/` 루트 위치. 펌웨어가 `src/` 밖이라는 규칙은 그대로다.

잇는 결정: D-2·D-38(최종 `cmd_vel`은 `core`), D-196·D-207(제품은 장치의 조합이고 설정만 가진다),
[D-228](D-228-decision-lives-in-core-features.md)·[D-229](D-229-layer-boundaries-on-the-current-tree.md)(판단과 층 방향), D-186(스크립트·수집·설치의 주인), D-191(폴더 이동은 이미지 릴리스 사이).

**Context:**

1. **`src/core/` 한 영역에 세 층이 섞여 있다.** 계약(`interfaces`, `core_common`), 실행(`core`, `core_features`, `control`), 화면(`core_api_web`, `web_common`)이 같은 폴더다. 폴더 이름만 보고는 누가 누구를 불러도 되는지 알 수 없다.
2. **2026-09-25 소유자가 목표 트리를 냈다.** `contracts / runtime / devices / products / hmi / site / sim`, `firmware/`, `test/architecture/`, `docs/architecture/` 이다. 층 분리는 D-229의 방향 표와 같은 말이다.
3. **패키지 이름을 바꾸는 비용은 층의 이득과 따로 논다.** `core_features`는 206개 파일, `core_common`은 207개 파일이 이름으로 부르고, `ros2 run core` 형태가 32곳이며, 장치에 깔린 systemd 유닛과 이미지도 이 이름이다. colcon은 패키지를 디렉터리 위치가 아니라 `package.xml`로 찾는다. 그래서 디렉터리를 옮겨도 패키지 이름·import·launch·유닛은 바뀌지 않고, 고칠 곳은 경로 참조뿐이다.
4. **목표 트리의 몇 자리는 안전 규칙과 부딪힌다.** 아래 결정 4에 적었다.

**Decision:**

1. **목표 영역과 자리.** 패키지 이름은 하나도 바꾸지 않는다. 옮기는 것은 디렉터리다.

   | 목표 | 패키지 (지금 자리 → 목표 자리) |
   |---|---|
   | `src/contracts/` 계약: 메시지, 스키마, 도메인 값 | `core/interfaces` → `contracts/interfaces`, `core/core_common` → `contracts/core_common` |
   | `src/runtime/` 로봇 실행과 최종 권한 | `core/core`, `core/core_features`, `core/core_events`, `core/control`, `core/core_api_web` → `runtime/<같은 이름>`, `navigation/navigation` → `runtime/navigation` |
   | `src/devices/<계열>/` 하드웨어 진실 | `bringup`, `sensor_adc`, `lamp_control`, `led` → `devices/pinky_pro/<같은 이름>`, `imu_bno055` → `devices/common/imu_bno055`, `products/omx_adapter` → `devices/omx/omx_adapter` |
   | `src/products/` 제품 조합(설정만) | D-196의 `robots/pinky_pro` → `products/pinky_pro`, OMX 설정 → `products/omx`. 코드와 launch를 두지 않는다 |
   | `src/hmi/` 로봇 로컬 화면 | `face/emotion` → `hmi/emotion`, `core/web_common` → `hmi/web_common` |
   | `src/site/` 사이트 쪽 | `fleet`, `games` 그대로 |
   | `src/sim/` | `description`, `gz_sim` 그대로 |
   | `firmware/` (colcon 밖) | `dock/` → `firmware/dock/`, `signal/` → `firmware/signal/` |
   | `test/architecture/` | 구조·경계·배치 시험(`test_module_structure.py`, `test_layer_boundaries.py`, `test_folder_layout.py`, `test_document_placement.py`, `test_target_layout.py`) |
   | `docs/architecture/` | `docs/concept/` 의 번호 문서 |

   `core_api_web`은 로봇 API라서 `runtime`이다. 그 안의 정적 화면 자산을 `hmi`로 떼는 일은 이 결정이 아니다.

   **장치는 계열로 묶는다(2026-09-25 소유자 결정, D-196 원안).** `devices/pinky_pro/`는 Pinky 보드에만 붙는 패키지, `devices/common/`은 여러 차체가 쓰는 칩, `devices/omx/`는 팔이다. 두 번째 로봇이 생기면 무엇이 Pinky 전용인지 폴더만 보고 안다. 패키지 디렉터리 이름은 그대로라 D-207 결정 2(종류 이름은 두 번째 구현 전에 바꾸지 않는다)와 부딪히지 않는다. URDF(`sim/description`)는 제품 조립(D-196 P6) 때 옮기고, 이 묶음에서는 `sim`에 둔다. 계열 폴더로 한 단계 깊어지는 것은 장치 패키지뿐이므로, `parents[N]`으로 저장소 루트를 찾는 시험을 고칠 곳도 장치 패키지뿐이다.
2. **패키지 이름 규칙은 D-227 결정 2 그대로다.** 기존 이름은 유지하고, `rosy_*`·`pinky_*` 접두는 다시 쓰지 않는다(D-147).
3. **제품 폴더는 설정만 가진다.** 매니페스트, 차체 숫자, 능력, URDF 조합이다. CORE가 설치 경로에서 찾도록 `package.xml`과 `CMakeLists.txt`만 가진 설정 패키지(D-196 `pinky_pro`)는 된다. launch와 코드는 `runtime`과 `devices`가 갖는다. Pinky 고유 코드는 `devices/`에만 있고, 여러 제품이 쓰는 실행 코드에 제품 이름을 붙이지 않는다.
4. **목표 트리에서 받지 않는 자리.**
   - **`runtime/rosy_pinky_pro`(인식·주행·행동)** — 공유 실행 코드를 한 제품 이름에 묶는다. 두 번째 차체에서 복사가 생긴다. 결정 3으로 대신한다.
   - **`rosy_decision/providers/remote`** — 원격 AI가 로봇 명령 경로에 들어간다. 판단은 `core_features/decision`(D-228)이고, 원격 모델은 증거나 `/do` 의도만 낸다. 네트워크나 GPU PC가 죽어도 로봇 안의 규칙이 멈춘다.
   - **`src/site/rosy_ai_worker`** — ROS 패키지가 아닌 GPU 서버를 colcon 작업공간에 넣는다. 코드가 생기면 저장소 루트 `services/ai_worker/`에 두고, 그 전엔 폴더를 만들지 않는다. 재생과 라벨은 `tools/perception/`이다(D-209).
   - **새 액션·메시지(`FollowLane`, `PickObject`, `DecisionResult` 등)** — 폴더가 아니라 로봇 API 계약의 변경이다. 계약 ADR로 따로 연다.
   - **빈 골격 폴더** — 코드가 들어오는 커밋에서만 만든다.
   - **`data/episodes`, `data/datasets`** — D-186의 `data/teleop`·`data/drive`가 그대로다. 에피소드 형식이 정해지면 그 ADR에서 연다.
   - **`deploy/targets·provisioning·release` 재배치** — D-186 결정 6의 별도 변경이다.

**이동 묶음(Transition):** 단계별 실행은 [2026-09-25-d231-layered-move.md](../plans/2026-09-25-d231-layered-move.md)다.

- **조건.** 다른 세션이 `src/`를 옮기거나 크게 고치는 중이 아니다. 이미지 릴리스 사이다(D-191). `refactor/multi-robot-structure`(D-196)를 같은 묶음에서 `main`에 머지하고, 그 `robots/pinky_pro`는 `products/pinky_pro`로 바로 들어간다.
- **방법.** 목표 영역 하나당 커밋 하나. 각 커밋은 `git mv`와 그 경로를 참조하는 살아 있는 파일(ci.yml, Dockerfile, `.dockerignore`, deploy 스크립트, `tools/harness/harness.yaml`, 시험, README·AGENTS)을 함께 고친다. 기록 문서(`logs.md`, 날짜 붙은 plans, ADR 본문)의 옛 경로는 고치지 않는다(D-226).
- **시험 전환.** `test_module_structure.py`의 `DOMAINS`를 새 영역으로 바꾼다. `test/test_target_layout.py`의 `MOVED`를 `True`로 바꾸면 모든 패키지가 목표 자리에 있어야 통과한다.
- **확인.** 전체 host pytest, harness lint, colcon build(WSL ROS box), 이미지 빌드 1회. 장치 인수는 기존 게이트로 따로 본다.

**Alternatives:**
- 붙여준 트리를 그대로(`rosy_*` 개명, 제품 이름 런타임, `src` 안 AI 워커). 층의 이득은 같고, 수백 파일과 설치된 장치 유닛을 고쳐야 하며, 결정 4의 안전 문제가 남는다.
- 지금 영역 유지(D-227 원안). 계약·실행·화면이 한 폴더에 섞인 채로 남는다.
- 패키지마다 이동 시점을 따로. 경로 참조를 여러 번 고치고, 그 사이 트리가 두 규칙을 동시에 가진다.

**Consequences:**
- 새 패키지는 목표 영역에 만든다. 지금 영역에 만들면 `test/test_target_layout.py`가 실패한다.
- 이동 전까지 `test_target_layout.py`는 모든 패키지가 지금 자리나 목표 자리 중 한 곳에 있고, 표에 없는 패키지가 없으며, 결정 4의 금지 자리가 없는지만 본다.
- D-227의 여섯 이름 표는 목표 영역 이름으로 읽는다: Foundation=`contracts`, Robot Runtime=`runtime`+`devices`, Experience=`hmi`+사이트 콘솔.

**Validation:** `python -m pytest test/test_target_layout.py -q`. 이동 묶음 뒤에는 위 "확인" 목록.

**References:** [D-168](D-168-ros-package-structure-standard.md), [D-207](D-207-one-owner-per-product-and-device-kind.md), [D-226](D-226-document-placement-and-publication-criteria.md), [D-227](D-227-ownership-names-stay-on-the-current-tree.md), [D-228](D-228-decision-lives-in-core-features.md), [D-229](D-229-layer-boundaries-on-the-current-tree.md), [폴더 지도](../plans/2026-09-25-folder-map.md).
