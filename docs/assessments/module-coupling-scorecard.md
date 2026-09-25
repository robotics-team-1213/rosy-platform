# 모듈 결합도/분리도 평가표 (Scorecard)

작성일: 2026-09-23 / 2차 회차: 2026-09-23 (§8) / 대상: `Rosy OS/src` 20개 패키지
선행 문서: `module-coupling-report.md`(2026-09-19 결합 경로 분석) — 본 문서는 그 결과를 **여러 명이 동시에 일할 수 있는가**라는 관점으로 재정렬한 채점표다.
판정 기준의 ADR: `Rosy OS/docs/adr/D-178-module-maintainability-scorecard.md` (2026-09-23, **Accepted** — 1차 실측 + 2차 회차 완료로 승격) — 축·가중치·컷 게이트·기준선 스냅샷은 거기, 근거와 해석은 여기(§8이 2차 회차).

**이번 평가에 새로 확인한 사실(2026-09-23 재검증)**

- `test/architecture/test_module_structure.py`(D-168) **11 passed** — 미선언 결합·방향 위반·크기 예산이 지금도 게이트로 잡히는 중.
- 비테스트 교차 import 매트릭스 재산출: 코드 수준 미선언 결합 **0건**. 남은 미선언은 launch/설정 수준 4건(게이트에 기록된 예외 목록과 일치).
- `web_common`(tokens.css / core_ui_logic.js)이 공용 1차원으로 정착 — `core_api_web`·`fleet` 선언 의존 + 소비자 계약 테스트 4종으로 고정.
- **정정 1건**: `gz_sim`의 '과잉선언 2건(control, core)'은 import만 세는 산출 스크립트의 **오판** — launch 경유(`get_package_share_directory("control")`, `Node(package="core")`)로 실제 사용한다. 진짜 과잉선언은 `core_api_web`·`core_features`의 미사용 `core_events` 선언 2건으로 교체 반영(§3·§5).
- **2차 회차(§8) 실측 — 점수 불변, 근거 정정 3건**: `core_features` "5.5k 예산 초과"는 표기 오류(실제 예산 내 5,583행/10k), `control` "600행 4건" → **5건**(SIZE_VERDICTS 일치), `core_features` 외부 시험 소유 28 → **29개**(core/test, 시험 3곳 분산) — 전부 근거 표기만 바꾸고 1차 판정을 재확인.

---

## 1. 평가 축 (루브릭)

가중치 합 100. 각 축은 1~5점.

| 축 | 질문 | 가중치 |
|---|---|---|
| **M1 독립 작업성** | 한 명이 **이 모듈만으로** 구현 → 단독 테스트 → 검증까지 끝낼 수 있는가? (외부 모듈 소스 트리나 외부 시험실에 발이 묶이지 않는가) | 25 |
| **M2 역할 명확성** | 패키지명·디렉터리·`AGENTS.md`가 실제 책임과 일치하는가? 단일 책임인가? 크기 예산(파일 600행 / 패키지 10k행) 안에 있는가? | 25 |
| **M3 동시 유지보수성** | 두 사람이 동시에 고쳐도 충돌이 나지 않는가? → (a) 시험이 자기 패키지에 있는가, (b) fan-out·전파 반경이 작은가, (c) 경계를 코드로 고정한 게이트가 있는가 | 20 |
| **M4 공용 모듈 관리** | 공통 코드가 적절한 공용 모듈로만 수렴하는가(복제 없음)? 공용 방향(direction table)을 지키는가? 공용이 커지지 못하게 하는 예산·계약 게이트가 있는가? | 15 |
| **M5 결합 강도·정합** | `package.xml` 선언이 실제 import/launch와 일치하는가? 순환·역방향 결합이 없는가? 결합 유형이 데이터/스탬프 수준인가? | 15 |

### 축별 앵커 (채점 기준점)

| 점수 | M1 독립 작업성 | M2 역할 명확성 | M3 동시 유지보수성 | M4 공용 관리 | M5 결합 정합 |
|---|---|---|---|---|---|
| **5** | 자기 시험 보유 + 코드 fan-out 0 + 외부 소스 불필요 | 책임 문서 고정 + 예산 준수 | 자기 시험 소유 + fan-out ≤1 + 경계 게이트 존재 | 도메인 공용 계약으로 수렴 + 0 fan-out + 오염 게이트 있음 | 선언=실제, 순환 0, 데이터/스탬프 결합만 |
| **3** | 시험이 외부 패키지 시험실에 있거나, 런타임이 외부 소스 트리 필요 | 한 패키지 안에 복수 책임 공존 (or 예산 초과 + split 판정 기록) | 시험 홈 공유로 충돌 가능 / fan-out 2 / 전파 반경 ≥3 | 방향 표 예외 기록, 부분 복제, 공용 적용 범위가 어긋남 | 미선언·과잉선언 1~2건, 기록된 역방향 1건 |
| **1** | 미선언 코드 결합으로 단독 검증 불가 | 책임 불명확 + 예산 초과 무기록 | fan-out ≥3 + 시험 미소유 | 공용 자리에 복제, 또는 공용이 상위를 의존 | 순환, 내용(구현) 결합, 게이트 부재 |

---

## 2. 등급 기준점

| 구간 | 등급 | 의미 (여러 명이 일할 때) |
|---|---|---|
| **90–100** | **S** | 즉시 병렬 개발 가능 — 손대지 말고 현상 유지 |
| **75–89** | **A** | 양호 — 계약 테스트만 유지하면 됨, 소규모 정리 |
| **60–74** | **B** | 한 축이 명확히 약함 — 개선 계획이 필요한 상태 |
| **45–59** | **C** | 병렬 작업 시 충돌/깨짐 리스크 — 우선 개선 대상 |
| **0–44** | **D** | 구조적 재설계 대상 |

**채점 공식**: `총점 = Σ(축 점수 × 가중치) ÷ 5` (최대 100)

**컷 게이트 (D-178)**: **M5≤2 또는 M3≤2 → 등급 상한 B**, **M2≤2 → 상한 C**, **S는 M3·M5 ≥ 4 필수**. 점수 구간과 게이트는 **더 낮은 쪽이 이긴다**. 2026-09-23 기준선에서 게이트는 어느 모듈의 등급도 바꾸지 않는다(점수가 이미 게이트 이하) — 게이트의 값은 향후 회귀 방지에 있다(한 축이 무너져도 점수가 높게 나와 S/A를 못 받게).

---

## 3. 측정 지표 (채점의 사실 근거)

비테스트 기준. `자기 시험` = 해당 패키지 `test/test_*.py` 존재.

| 모듈 | py / 테스트 파일 | fan-out | fan-in | 자기 시험 | 예산 초과 (판정) | 구조 게이트 예외 |
|---|---|---|---|---|---|---|
| `contracts/interfaces` | 0 / 1 | 0 | 4(IDL) | O | – | – |
| `hmi/web_common` | 0 / 0 | 0 | 2 | X | – | 시험 예외 1건 |
| `contracts/core_common` | 16 / 1 | 0(+1 launch) | **5** | O | – | **역방향 1건** (`common→core` 설정 공유) |
| `runtime/core_events` | 4 / 0 | 1 | 1 | X | 파일 745행(accept) | 시험 예외 1건 |
| `runtime/core_features` | 37 / 0 | 1 | 2 | X | – | 시험 예외 1건 (29개 core 시험이 대신 소유 — 시험이 3곳에 분산) + **과잉선언 1건** (`core_events`, 어디서도 0회) |
| `runtime/core_api_web` | 25 / 3 | 2 | 1 | O | – | 과잉선언 1건 (`core_events`) |
| `runtime/core` | 21 / **74** | 4 | 0 | O | `ros_bridge.py` 759행 (**split 재개**) | 동적 import 1건(D-126, 테스트 이음새) |
| `runtime/control` | **200** / 164 | 0 | 0(code) | O | **패키지 28,159행 (split, 미일정)** + 600행 5건 (split 2·미일정 / accept 3) | launch 미선언 1건 (`control→imu_bno055`) |
| `site/fleet` | 23 / 27 | 1 | 1 | O | `signals.py` 621(split·미일정), `console.py` 767(accept) | – |
| `sim/gz_sim` | 14 / 9 | 2 | 0 | O | – | launch 경유 `control`·`core`는 **실제 사용**(선언=실제), `navigation` 중복 선언 1건 |
| `runtime/navigation` | 7 / 0 | launch 4 | 1 | X | – | **미선언 2건 + 방향 위반 2건** |
| `hardware/bringup` | 9 / 7 | 0 | 0(code) | O | – | – |
| `hardware/led` | 2 / 4 | IDL | 1 | O | – | – |
| `hardware/imu_bno055` | 1 / 2 | 0 | 0 | O(린터 위주) | – | 인바운드 미선언 1건 |
| `hardware/lamp_control` | 0 / 1 | IDL | 0 | O(린터 1건) | – | – |
| `hardware/sensor_adc` | 0 / 1 | 0 | 0 | O(린터 1건) | – | – |
| `apps/emotion` | 5 / 7 | IDL | 1 | O | – | – |
| `apps/games` | 26 / 17 | 0 | 0 | O | – | – |
| `apps/omx_adapter` | 3 / 3 | 0 | 0 | O | – | – |
| `sim/description` | 2 / 2 | 0 | launch 3 | O | – | – |

> `core` 시험 74개는 `core_common`·`core_features`·`core_events`·`web_common`·`control`의 검증까지 한 자리에서 수행한다 — **시험 소유가 패키지 소유와 어긋나는 지점이 이 평가의 핵심 변수**다.

> hardware 3종(`imu_bno055`·`lamp_control`·`sensor_adc`)은 **기기 전용 ※** — 동일 기준으로 채점하되, M1의 "호스트에서 안 도는 시험"은 결합이 아니라 **테스트 전략(aarch64 전용)의 결과**로 본다. 감점은 유지하되 원인 구분이 필요할 때 ※를 읽는다.

---

## 4. 모듈별 점수표

점수 내림차순. 축 앵커는 §1, 근거 지표는 §3 참조.

| 모듈 | M1 | M2 | M3 | M4 | M5 | **총점** | 등급 | 한 줄 근거 |
|---|---|---|---|---|---|---|---|---|
| `hardware/bringup` | 5 | 5 | 5 | 4 | 5 | **97** | S | fan-out/fan-in 0, 자기 시험 + 저장소 계약 시험 2종 |
| `apps/emotion` | 5 | 5 | 5 | 4 | 5 | **97** | S | 완전 분리. 팔레트만 D-73으로 자체 보유 |
| `contracts/interfaces` | 5 | 5 | 4 | 5 | 5 | **96** | S | IDL 계약만. fan-out 0, 소비자 4개와는 타입 경유 |
| `hardware/led` | 5 | 5 | 4 | 5 | 5 | **96** | S | IDL 경유, 작은 단일 목적 |
| `sim/description` | 5 | 5 | 4 | 5 | 5 | **96** | S | fan-out 0, launch fan-in 3 (전파는 있으나 방향은 허용) |
| `apps/games` | 5 | 5 | 5 | 3 | 5 | **94** | S | ROS 0, 단독 호스트. 단 `web_common` 밖이라 공용 규약 미적용 |
| `apps/omx_adapter` | 5 | 4 | 5 | 4 | 5 | **92** | S | 좁은 경계 어댑터, 기본 비활성, fan-out 0 |
| `hmi/web_common` | 4 | 5 | 4 | 5 | 5 | **91** | S | 0 fan-out 공용 자산 + 소비자 계약 테스트 4종 + 600/10k 예산 |
| `products/pinky_pro` | 5 | 5 | 4 | 3 | 4 | **87** | A | D-196 신규(2026-09-24 잠정): config 전용·자기 시험 보유·fan-out 0. M4 — `deploy/robot/config/profile.*.yaml`이 속도 상한을 부분 복제(`test_nav2_profile_limits`가 일치 고정). M5 — core가 `robot.model`로 동적 조회(선언 없음, D-126과 같은 종류) |
| `contracts/core_common` | 4 | 5 | 4 | 5 | 3 | **85** | A | fan-in 5의 공용 스키마, 그러나 기록된 역방향 1건 |
| `runtime/core_api_web` | 4 | 4 | 4 | 5 | 3 | **80** | A | `deps` 파사드 + v1 직접 import 금지 게이트로 전파 반경 봉쇄, 과잉선언 1건 (`core_events` — 생산 코드 0회) |
| `site/fleet` | 4 | 4 | 4 | 4 | 5 | **83** | A | 자기 시험 27개, `fleet.bench` 공개면으로 gz_sim과 분리 |
| `hardware/lamp_control` | 3 | 5 | 3 | 5 | 5 | **82** | A | IDL 경유 깨끗, 단 aarch64 전용·기능 시험 없음 — **기기 전용 ※** |
| `runtime/core_events` | 3 | 5 | 3 | 4 | 5 | **79** | A | 책임 명확 단일 목적, 단 시험을 `core/test`가 소유 |
| `hardware/sensor_adc` | 3 | 5 | 3 | 4 | 5 | **79** | A | 역할 명확, 단 aarch64 전용 + 린터성 시험만 — **기기 전용 ※** |
| `hardware/imu_bno055` | 3 | 5 | 3 | 4 | 3 | **73** | B | 역할은 명확하나 호스트 검증 불가 + control의 미선언 인바운드 — **기기 전용 ※** |
| `sim/gz_sim` | 3 | 4 | 3 | 4 | 4 | **71** | B | fleet·navigation 설치 없이는 벤치 검증 불가(M1) + fan-out 2, 선언은 launch 경유 포함 실제 사용(과잉선언 아님 — 정정), `navigation` 중복 선언 1건 |
| `runtime/core` | 3 | 3 | 3 | 4 | 4 | **66** | B | fan-out 4 + 시험 74개가 도메인 전체 소유 + 시험 시 control 소스 필요 |
| `runtime/core_features` | 3 | 3 | 2 | 4 | 3 | **59** | **C** | 자기 시험 0(시험이 3곳 분산) + 13개 기능 공존(5.6k행, 예산 내) + 과잉선언 1건 — 고장 통보형 병목 |
| `runtime/control` | 4 | 2 | 3 | 3 | 2 | **57** | **C** | 28,159행(예산 2.8배)·다중 책임·split 미일정 + 미선언 launch 1건 |
| `runtime/navigation` | 3 | 3 | 3 | 3 | 2 | **57** | **C** | 미선언 2건·방향 위반 2건, assembly(`web_*`)가 역할에 혼입 |

**분포**: S 8개 · A 6개 · B 3개 · C 3개 · D 0개 / **전체 평균 81.5 (A)** (A 평균 81.3) — 2026-09-23 20개 기준. `products/pinky_pro`(2026-09-24, D-196 신설)는 잠정 행이며 분포·평균에 넣지 않았다(다음 회차 재채점)
**도메인 롤업**: `hardware` 85.4 · `apps` 85.0 · `sim` 83.5 · `site` 83.0 · `core` 79.4 · `navigation` 57.0 (C)

---

## 5. 축별로 본 해석

**M1 독립 작업성 — 평균 4.0, 가장 큰 구조적 취약점은 "시험 소유 분산"**
소형 모듈(`games`, `emotion`, `omx_adapter`, `bringup`)은 fan-out 0 + 자기 시험 보유로 만점에 가깝다. 반면 `core_features`(자기 시험 0)·`core_events`(0)·`web_common`(0)·`navigation`(0)은 **자기 코드를 남의 시험실에서 검증**한다. `core_features`는 28개 `core/test` 파일이 그 내용을 알고 있어, features를 고치려면 사실상 `runtime/core/test`를 같이 열어야 한다.

**M2 역할 명확성 — 예산 초과 2건이 전부 리스크 상위**
`control`(28,159행, 예약된 split 계획 미일정)과 `core`(ros_bridge 759행, split 판정이 **재개**)가 여기서 가장 낮다. `core_features`는 하위 모듈마다 `AGENTS.md`가 있어 문서적 명확성은 있으나, **한 패키지 안에 13개 기능이 공존**한다. `navigation`은 launch assembly(`web_nav2`/`web_slam`이 core까지 띄움)가 자기 역할 안에 들어와 있다.

**M3 동시 유지보수성 — 병렬 작업의 병목은 `runtime/core/test` 한 디렉터리**
충돌 면적은 코드 import가 아니라 **시험 디렉터리**에서 나온다. `core/test` 74개 파일이 core·core_common·core_events·core_features·web_common·control(테스트 이음새)의 검증을 겸한다. 최소 4개 모듈을 동시에 고치는 두 사람이면 여기서 만난다.
반대로 `core_api_web`(deps 파사드 + `test_v1_import_boundary`), `fleet`(`fleet.bench` 공개면 + 구조 테스트), `gz_sim`(D-148 고정)은 **변경 전파를 코드로 봉쇄한 사례**다 — 이 패턴이 M3 만점의 기준이다.

**M4 공용 모듈 관리 — 세 층이 명확히 자리 잡았다**
계약 스키마 `core_common`(fan-in 5), 서비스 타입 `interfaces`, 디자인 토큰 `web_common`. 세 곳 모두 fan-out 0이고, 공용을 깨면 깨지는 계약 테스트(`test_package_contract`, `test_ui_token_contracts`, `test_console_palette`, `test_palette_gates`)가 소비자 쪽에 걸려 있다. 이질점 2개: `games`/`emotion`은 공용 토큰을 쓰지 않고 자체 팔레트를 갖는데(규칙상 허용, D-73) → **공용 UI 규약의 적용 범위가 "웹 콘솔 2곳"에 한정**된 상태다.

**M5 결합 강도·정합 — 코드 0건, 남은 것은 launch/설정 4건**
비테스트 코드 import 기준 미선언은 0건이며 구조 게이트가 유지 중이다. 남은 예외: `core_common→core`(설정 파일 위치), `navigation→control`, `control→imu_bno055`, `navigation→core`. 전부 **launch/설정 경유**라 게이트가 `get_package_share_directory` 리터럴만 읽는 사각지대에 있다(게이트 주석에 "honest holes"로 자인됨).

**정정(2026-09-23)**: 초판의 `gz_sim` "과잉선언 2건"은 import만 세는 산출 스크립트의 오판이었다 — `launch/semantic_road_dashboard.launch.py`의 `get_package_share_directory("control")`(월드·맵 번들이 control 소유)와 `gz_multi.launch.py`의 `Node(package="core")`로 **실제 사용**한다. 반대로 진짜 과잉선언은 `core_api_web`·`core_features`가 선언만 하고 생산·시험이 한 번도 안 쓰는 `core_events` 2건이며, 앵커대로 **M5=3**이다.

---

## 6. 우선 개선 과제 (점수와 직접 연결)

| 순위 | 과제 | 올라가는 축 | 기대 점수 변화 |
|---|---|---|---|
| 1 | `control` 패키지 분할 실행 (`docs/plans/2026-09-22-control-package-split-design.md`, 미일정) | M2 (+2), M5 (+1) | `control` 57 → 70+ (B) |
| 2 | 시험 소유를 패키지로 되돌리기: `core_features`/`core_events`/`web_common`에 자기 `test/` 신설(현행 예외 목록을 줄이는 방향) | M1 (+1~2), M3 (+1~2) | 해당 3개 모듈 59~91 → +10~15, `core/test` 충돌면 축소 |
| 3 | `navigation`의 `web_*` assembly 분리 + launch 미선언 2건 해소 | M2 (+1), M5 (+2) | `navigation` 57 → 70+ |
| 4 | 미사용 선언 제거: `core_api_web`·`core_features`의 `core_events` 선언(생산 코드 0회) + `gz_sim` `navigation` 중복 선언 정리 | M5 (+1~2) | `core_features` 59 → 64~69, `core_api_web` 80 → 83, `gz_sim` 71 → 74 |
| 5 | `core` `ros_bridge.py` split 판정 이행(재개 상태) | M2 (+1) | `core` 66 → 71 |
| 6 | launch/설정 경유 결합을 게이트가 읽도록 스캐너 확장(현재 리터럴만 인식) | M5 (전 모듈) | 사각지대 제거 |

---

## 7. 이 평가표의 한계

- 축 점수는 앵커(§1)에 고정한 **주관 채점**이다. 근거 지표(§3)는 재현 가능하지만, 같은 지표라도 앵커 해석에 따라 ±1점은 움직인다.
- 매트릭스는 Python import 기준이라 **C++ `#include`·launch 포함은 `test_module_structure.py` 결과에만 반영**했다.
- `control`의 인바운드 결합(핵심 시험 **5개 파일**이 control 내부 **7개 모듈**을 안다 — 2차 회차 전역 AST 재확인)은 패키지 fan-out 표에는 안 보이므로 §3 주석으로만 표기했다.
- 산출 스크립트(`coupling_matrix.py`)는 **Python import만 세어 launch 경유 참조를 놓친다** — `gz_sim` 과잉선언 오판이 그 결과였다. D-168 스캐너(share/node 리터럴 인식)와 대조해 정정했으므로, 재산출 시 launch·`package://` 참조까지 포함하도록 확장할 것.
- 재산출 방법: `X:\DevTemp\opencode\coupling_matrix.py`(비테스트 import 매트릭스) + `python -m pytest "Rosy OS/test/architecture/test_module_structure.py"`.
- 2차 회차 산출(`X:\DevTemp\opencode\round2.py`)은 **.py import만** 파싱한다 — `navigation`의 launch **XML 15개**(assembly `web_*` 포함)는 파일·라인만 집계했고, launch 참조 판정의 권위는 D-168 스캐너(`WORKSPACE_REF_PATTERNS`·`LAUNCH_EXEC_PATTERNS`)에 있다.

---

## 8. 2차 회차 (2026-09-23): C/B 4개 내부 모듈 분해와 병렬 작업 충돌 지점

D-178 Decision 5·착지 조건의 회차. 1차가 패키지를 재었다면 이번에는 **패키지 내부**를 재서 "두 사람이 이 패키지에서 동시에 일하면 어디서 부딪히는가"를 파일 단위로 뽑았다.
방법: 파일 단위 AST 분해(`X:\DevTemp\opencode\round2.py` → `round2.json` — import는 파일 내 위치 무관 집계, 행 수 splitlines, `control`의 map 번들은 데이터라 제외) + D-168 스캐너(SIZE_VERDICTS·KNOWN_* 예외 목록) 교차 대조. 파일 수는 산출 기준이라 §3과 필터 차이로 ±2 있다.

**결과부터**: 네 패키지 점수는 **모두 변동 없음** — `control` 57 · `core_features` 59 · `navigation` 57 · `gz_sim` 71. 2차 실측이 1차 판정을 재확인했고, 대신 **근거 표기 정정 3건**이 잡혔다(§8.0). D-178 기준선은 이 회차로 갱신 후 Accepted.

### 8.0 회차 정정 (근거만 바꾸고 점수는 불변)

| # | 위치 | 초판 | 정정 | 근거 |
|---|---|---|---|---|
| 1 | §4·ADR 기준선 `core_features` 비고 | "5.5k 예산 초과" | **예산 내** + 13개 기능 공존 | D-168 `PACKAGE_BUDGET=10_000`, 실측 38 py·5,583행. M2=3은 "예산 초과"가 아니라 **한 패키지 안 13개 기능 공존** 앵커로 유지 → 59 불변 |
| 2 | §3 `control` | "600행 4건" | **5건** (split 2·미일정 / accept 3) | SIZE_VERDICTS: startup_calibration 965·calib_node 641 = split / safety/node 795·lane 611·lane_bev 611 = accept |
| 3 | §3 `core_features` | "28개 core 시험이 대신 소유" | **29개** (그 외 fleet 1·루트 1 = 총 31) | 전역 AST 스캔(import 위치 무관). 시험이 **3곳에 분산** — M3=2 근거는 오히려 강화 |

### 8.1 `runtime/control` (57, C) — 내부 군집 / 358 py·42,260행

| 군집 | 파일 | 행 | 최대 파일 (행) | 성격 |
|---|---|---|---|---|
| `test/` | 162 | 15,246 | test_planning (727) | 자기 시험 `test_*` 160 — 시험 소유는 있음 |
| 루트(노드·주제) | 30 | 6,543 | startup_calibration_node (965 ※split) | ROS 노드 + 순수 주제 |
| `control.control` | 50 | 5,041 | recover (355) | 내부 순수 라이브러리 — test fan-in **85건(최다)** |
| `control.sensing` | 33 | 4,984 | lane (611 ※accept) | 라이다/BEV 감지 |
| `tools/` | 45 | 4,552 | driver (477) | Gazebo·감사 도구 |
| `control.wander` | 8 | 2,389 | node (595) | 이동 로직 |
| `control.safety` | 8 | 1,608 | node (795 ※accept) | 안전 게이트 |
| `control.planning` | 10 | 1,417 | goals (578) | 목표·경로 |
| `launch/` + `setup.py` | 12 | 480 | robot.launch (86) | 조립·등록 |

※ = D-168 크기 판정. 코드 외부 fan-out **0** — 워크스페이스 어떤 모듈도 import하지 않는다.

**충돌 지점**

1. **단일 조립 파일**: `setup.py` console_scripts 14건 + `launch/` 11개 — 노드 추가·개명은 언제나 이 두 파일에서 모든 노드 작업자가 부딪힌다.
2. **`test/` fan-in**: `test→control.control` 85건 · `→control.sensing` 55건 · `→control.planning` 26건 — sensing/planning 수정은 시험 여러 파일 동시 수정면, `test_planning.py` 727행이 최대 접점.
3. **fan-in 1위 = `control.sensing`** (시험 55 + tools 9 + 노드 7 = 71건) — 자기 안에서도 세 영역에 걸친 유일한 군집.
4. **패키지 밖 = core/test 5파일·7모듈 고정**: `control.control.{actuation,command_gate,lidar_guard,obstacle_risk}` · `control.sensing.observation` · `control.calibration_storage` · `control.sensor_provider` (D-126 이음새) — 이 7모듈을 고치면 core 시험실 5파일이 동시에 깨진다.

**해석**: 충돌 전부가 **패키지 내부**(외부 fan-out 0) → D-171 split 실행 시 (a) 노드+launch (b) 내부 라이브러리 (c) sensing (d) planning (e) safety+wander (f) tools **여섯 스트림**이 각자 이미 존재하는 자기 시험과 함께 갈라진다. `core/test` 5파일·7모듈이 유일한 외부 접점 — split 미일정이 병렬성을 막는 유일한 요인이라는 뜻(§6 과제 1의 독립 증거).

### 8.2 `runtime/core_features` (59, C) — 13기능 / 38 py·5,583행 (**예산 내**)

| 특징 | 수치 | 의미 |
|---|---|---|
| 자기 시험 | **0** | 시험 3곳 분산: `core/test` **29** · `fleet/test` 1 (geometry) · 루트 `test/` 1 (dock_contract) |
| 외부 fan-out | **`core_common` 단일** (10개 기능이 공유) | fan-out은 작지만 **동시성 넓이**는 큼: core_common 변경 = 10개 기능 동시 영향 |
| 기능 간 교차 import | **swarm→navigation 2건 · command→safety 1건뿐** | 나머지 11개 기능은 자기 안만 — 코드 결합은 기능 단위로 이미 분리 |
| 최대 기능 | docking 6파일 1,131 (manager 511) | 내부 fan-in 5, 기능 안에서만 |
| 600행 파일 | 0 (safety/manager 정확히 500) | 파일 예산 안 |

**충돌 지점**: 코드가 아니라 **`runtime/core/test` 한 디렉터리**가 병목 — command·safety·state·navigation이 **각각 6개** core 시험 파일에 의해 검증된다. features에서 두 명이 기능별로 일해도 시험은 core 작업자와 같은 폴더에서 만난다(전체 core 시험 74개 중 일부). D-168 `KNOWN_WITHOUT_OWN_TESTS` 예외 1건이 이 구조를 허용 중.
**해석**: 코드 패러다임은 이미 분리(13기능 × 자기 모듈), 실패하는 것은 **시험 소유**뿐 → §6 과제 2(자기 `test/` 신설)가 M1·M3를 동시에 올린다는 파일 단위 확인. fan-out 1·교차 3건이라 시험 이전 비용도 작다.

### 8.3 `runtime/navigation` (57, C) — 모듈 6·513행 + launch 16파일·744행

- **조립 단일 지점**: `hardware.launch.py` 222행이 모듈 4개(site_map·params_rewrite·footprint_profile·profile_limits)를 전부 import. launch/는 **16파일**(.py 1 + .xml 15)이고 그중 `web_nav2`·`web_slam`(+ gz 대응)은 **core까지 띄우는 assembly** — D-168 `KNOWN_DIRECTION`의 navigation→control·navigation→core 2건이 정확히 여기서 나온다.
- **시험 소유 0, 시험 위치 = 루트 `test/` 5파일** (params_rewrite 4 · profile_limits 2 · frame_prefix 2 · site_map 1 · footprint 1) — deploy·nav2 대역 시험과 **공유 디렉터리**라 외부 작업자와 충돌면이 겹친다.
- 코드 fan-out 0, py 735행 — **작다**.

**충돌 지점 = launch 두 겹**: (1) 모듈을 삼키는 `hardware.launch.py`, (2) 역할 밖 assembly `web_*`. 두 파일이 고장나면 작업이 전부 여기로 모인다.
**해석**: 네 패키지 중 **split 비용이 가장 작다** — assembly 분리 + 자기 `test/` 신설이면 조립면과 시험면이 동시에 갈라진다. §6 과제 3(57→70+)의 실행 단위가 확정된다.

### 8.4 `sim/gz_sim` (71, B) — 14 py·3,651 + 시험 9·1,241 (총 23 py·4,892행)

| 군집 | 파일 | 행 | 최대 |
|---|---|---|---|
| `scripts/` | 7 | 1,898 | map_v2_runner (474) |
| `launch/` | 7 | 1,753 | gz_multi.launch (582 — 600행 예산 **근접**) |
| `test/` | 9 | 1,241 | map_v2_traversal (256) |

- fan-in **0** · 자기 시험 9 · 외부가 gz_sim을 시험하는 곳 **0** → 내부 충돌면이 네 중 최소(71 B와 일관: B 사유는 내부가 아니라 **inbound**).
- **충돌 지점 = 설치·벤치의 공유 의존**: launch이 `navigation` import · scripts가 `fleet` import (fan-out 2). gz_sim과 navigation/fleet을 **동시에** 고치는 두 사람이 colcon 빌드·벤치에서 만나는 구조 — 결합은 얕으나 검사할 게이트(D-148)가 있어 M3=3.
- 시험이 launch/scripts를 흉내 내는 **통합 시험 성격**(traversal 256행 등) → launch 한 줄이 시험 9개 재실행을 끌고 온다.

### 8.5 충돌 지점 한 장 요약 (병렬 배정용)

| 패키지 | 1순위 충돌 지점 | 누가 만남 | 해소 (§6 대응) |
|---|---|---|---|
| `control` | `setup.py`·`launch/` 단일 조립 + `test/` fan-in(85/55/26) + core/test 5파일·7모듈 | 노드 작업자 전원 / sensing·planning 수정자 / core 작업자 | 과제 1 **split** |
| `core_features` | `runtime/core/test` 한 디렉터리에 13기능 시험 29개 | features 작업자 ↔ core 작업자 상면 | 과제 2 **자기 시험 신설** |
| `navigation` | assembly `web_*` + `hardware.launch.py` + 루트 `test/` 공유 | launch 작업자 ↔ core·deploy 작업자 | 과제 3 **assembly 분리 + 시험 소유** |
| `gz_sim` | 설치·벤치 공유 의존(navigation·fleet) + 통합 시험 재실행면 | sim ↔ navigation·fleet 작업자 | 과제 6 **게이트 스캐너 확장** |

**총평**: 코드 fan-out(1차 지표)은 이미 0에 가까운데, 병렬 작업을 실제로 막는 것은 **① 단일 조립 파일(setup·launch) ② 남의 시험실(`core/test`·루트 `test/`) ③ fan-in 핫스팟(test→sensing 55건)** 세 종뿐이다. 셋 다 §6 과제 1·2·3과 같은 지점을 가리킨다 — 개선 순위는 이 회차로 **파일 단위까지 확정**됐고, D-178 기준선은 점수를 유지한 채 정정만 반영해 갱신한다.
