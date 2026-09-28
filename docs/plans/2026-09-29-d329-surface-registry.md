# D-329 표면 레지스트리 실행 계획

**Source decision:** [D-329 표면은 등록으로 계약을 받고, 육안 기준은 저장소에 남는다](../adr/D-329-surface-registry-and-visual-baseline.md) (Proposed)
**Goal:** 표면 계약 적용 범위를 `src/hmi/web/surfaces.yaml` 한 파일로 옮기고, 등록되지 않은 표면이 빨갛게 되는 시험을 넣는다. 끝나면 새 표면이 어떤 계약을 받는지가 세 곳에 손으로 적히지 않고, 빠뜨렸는지도 파일 한 장으로 읽힌다.
**Status:** 실행 계획. D-329의 Decision 1–3만 실행한다. Decision 4의 `matrix.json`은 아래 "범위 밖".

## 범위 밖 (D-329가 미룬 것)

- `matrix.json` 스키마와 회차 간 파일명 규칙 — D-329 Transition 4가 "스키마가 정해진 뒤에 시험을 넣는다"고 못박았다. 스키마가 없을 때 시험을 넣으면 공허해진다.
- 자동 픽셀 회귀 게이트 — D-329 Alternatives에서 기각.
- `src/hmi/pilot` 구현과 등록 — HTML이 처음 생기는 커밋이 등록까지 책임진다 (D-329 Transition 5, D-323 실행 계획의 해당 T-스텝). 등록 없는 HTML은 T5 시험에서 빨갛다.
- 표면의 레이아웃·문구 — `2026-09-29-uiux-craft-improvement-plan.md`의 소유.

## 현재 상태 — 목록이 셋이고 멤버십이 다르다

| 표면 경로 | `test_shared_controls` | `test_surface_typography_focus` | `test_web_dialog` |
|---|:-:|:-:|:-:|
| `src/hmi/dashboard` | O | O | O |
| `src/site/fleet/fleet/server/web` | O | O | O |
| `src/site/games/games/web` | O | O | O |
| `src/runtime/sensing/web/dashboard.html` | O | – | – |
| `src/hmi/web` (라이브러리) | – | O | – |
| `src/sim/gz_sim/scripts/lane_live_view.html` | – | – | – |

- 첫 세 줄은 세 시험의 `SURFACES` 상수에 각각 적혀 있다. 네·다섯 번째는 둘씩만 적혀 있다. **여섯 번째는 어느 목록에도 없다.**
- 차이 자체는 대체로 타당하다 (`web_common`은 계약의 원본이고, 진단 페이지는 PARKED다). 문제는 **차이의 이유가 적혀 있지 않다**는 것이다.
- `src/`의 추적 HTML은 8개다. `dashboard/surface.html`·`dashboard/styleguide.html`·`web/template.html`은 등록된 폴더 안에 있어 그대로 덮이고, 남는 것이 `lane_live_view.html` 하나다.

## T1 — 레지스트리와 로더

**파일:** `src/hmi/web/surfaces.yaml` (새), `src/hmi/web/test/surface_registry.py` (새)

레지스트리 스키마 — D-262 `test_web_budgets.VERDICTS`가 이미 쓰는 방식(전부를 훑되 예외는 이유와 함께 적는다)을 적용 범위로 확장한다.

```yaml
# D-329 표면 레지스트리 — 표면 계약 적용 범위의 단일 출처.
# 표면을 더하거나 빠는 커밋은 이 파일을 같은 커밋에서 고친다.
# 코드를 담지 않는다: D-92 "어휘만 공유", D-75 무번들러.
surfaces:
  - id: console                    # 고유
    path: src/hmi/dashboard        # 저장소 상대. 파일 또는 폴더. 존재해야 한다
    surface: robot                 # robot | site | sim | dev
    audience: 운용자·장비 운용 (D-153 §7 — /dashboard·/console·/setup·/device)
    grammar: spatial               # web_common/ui.js GRAMMARS 안에서만. 생략 가능
    contracts: [shared_controls, typography_focus, dialog]
    baseline: docs/validation/uiux-surfaces-2026-09-26/captures/console-operate-fresh-1366x768.png
```

필드 규칙 (로더가 검사하고, T2 시험이 전부를 대조한다).

| 필드 | 규칙 |
|---|---|
| `id` | 필수, 고유 |
| `path` | 필수, 저장소 상대, 존재할 것 (폴더 또는 단일 파일) |
| `surface` | 필수, `robot`\|`site`\|`sim`\|`dev` |
| `audience` | 필수, 한 줄 |
| `grammar` | 선택. 있으면 `web_common/ui.js`의 `GRAMMARS`(spatial·exception·focal·procedure)여야 한다 |
| `contracts` | 필수. `shared_controls`·`typography_focus`·`dialog`의 부분 집합. 빈 목록 허용 |
| `contract_reason` | **세 계약을 다 받지 않을 때 필수** — 왜 빠졌는지 한 문장 |
| `baseline` | 선택. 있으면 추적된 저장소 파일이어야 한다 |
| `baseline_reason` | **`baseline`이 없을 때 필수** — 왜 기준선이 없는지 한 문장 |

**초기 항목 여섯 개는 위 표의 멤버십을 그대로 옮긴다** — 이 단계에서 어떤 표면의 판정도 달라지지 않는다.

| id | path | surface | grammar | contracts |
|---|---|---|---|---|
| `console` | `src/hmi/dashboard` | robot | spatial | 셋 다 |
| `fleet-console` | `src/site/fleet/fleet/server/web` | site | exception | 셋 다 |
| `game-board` | `src/site/games/games/web` | site | focal | 셋 다 |
| `control-diagnostic` | `src/runtime/sensing/web/dashboard.html` | robot | procedure | `shared_controls`만 |
| `web-common` | `src/hmi/web` | robot | spatial | `typography_focus`만 |
| `lane-live-view` | `src/sim/gz_sim/scripts/lane_live_view.html` | sim | – | 없음 |

`contract_reason`과 `baseline`은 이렇게 채운다.

- `control-diagnostic` — 타이포·확인 계약은 이 표면에 도입된 적이 없다 (D-150 한 파일·한 IIFE 고정, PARKED D-266). 빈 셀을 이유 없는 구멍으로 남기지 않는 것이 이 항목의 목적이다. `baseline_reason`: 저장소에 추적된 캡처가 없고 회차 G2 대상에서 빠져 있다.
- `web-common` — `tokens.css`·`components.css`·`ui.js`가 계약의 원본이라 소비자 재도색·복제 검사의 대상이 아니다 (`test_shared_controls`는 COMMON 파일을 직접 읽는다). `baseline_reason`: 렌더링되는 화면이 아니다.
- `lane-live-view` — 제품 셸·토큰·확인 문법의 대상이 아니다. 라인 예산과 판정은 `test_web_budgets`의 D-262 `VERDICTS`가 맡는다. `baseline_reason`: 제품 표면이 아니다.
- `console`·`fleet-console`·`game-board` — `baseline`은 2026-09-26 회차의 추적 PNG 하나씩 (`console-operate-fresh-1366x768.png`, `fleet-normal-1920x1080.png`, `games-play-1280x800.png`). 세 계약을 다 받으므로 `contract_reason`이 필요 없다.

**로더** `surface_registry.py`는 의존성 없이 동작한다: `load(root) -> list[dict]`, `for_contract(root, name) -> list[Path]`, `discover_html(root) -> list[Path]`. `git`이 없거나 `.git`이 없으면 `pytest.skip` — `test/architecture/test_document_placement.py`의 `_git()`과 같은 처리다.

`discover_html`이 **파일시스템 `rglob`이 아니라 `git ls-files -c -o --exclude-standard -- src`**를 쓰는 것이 이 계획의 핵심이다. `rglob`은 `.gitignore`된 Android 빌드 산출물(`src/site/overhead/android/app/build/**/index.html`)을 집어온다 — 사실 지금 `test_a_browser_page_starts_from_the_shell`이 바로 그 지점에서 로컬에 빨갛다. 반대로 `git ls-files`만 쓰면 아직 `git add`하지 않은 새 표면이 빠진다. `-c -o --exclude-standard`는 둘 다를 잡는다.

## T2 — 등록되지 않은 표면은 실패한다

**파일:** `src/hmi/web/test/test_surface_registry.py` (새)

1. `discover_html`의 모든 HTML이 등록된 `path` 아래(또는 그 파일과 같으면) 있다 — 아니면 빨강. 지금 이 시험은 `lane_live_view.html` 하나로 빨갛게 들어와야 한다.
2. 등록된 `path`가 모두 존재한다.
3. `id` 고유, `surface`·`contracts` 값이 폐집합 안, `grammar`가 `ui.js` `GRAMMARS` 안.
4. 세 계약을 다 받지 않는 항목에 `contract_reason`이 있고, `baseline`이 없는 항목에 `baseline_reason`이 있다.
5. `baseline`이 주어지면 그 파일이 추적 파일이다.
6. 계약 시험 셋이 **레지스트리에 없는 상수로 표면 목록을 다시 적지 않는다** — `SURFACES = (` 같은 리터럴 정의가 세 시험 파일에 남아 있으면 빨강.

**변이 확인 (D-329 Decision 3이 요구하는 것 — 없으면 시험으로 채택하지 않는다).** 각각 한 번씩 실제로 수행하고 그 기록을 `docs/logs.md`에 남긴다.

| # | 변이 | 기대 |
|---|---|---|
| M1 | `lane-live-view` 항목을 지운다 | 빨강 → 항목을 되돌리면 초록 |
| M2 | `src/hmi/pilot/index.html`를 **`git add` 없이** 만든다 | 빨강 → 지우면 초록 |
| M3 | `console`의 `path`를 없는 폴더로 바꾼다 | 빨강 → 되돌리면 초록 |
| M4 | `game-board`에서 `dialog`를 빼고 `contract_reason`도 지운다 | 빨강 → 되돌리면 초록 |
| M5 | M2에서 `git add`한 뒤에도 항목이 없으면 | 여전히 빨강 (`-o`가 아닌 `-c`만 쓰면 M2가 통과하므로 **M2가 곧 로더 스코프의 증거다**) |

## T3 — 세 시험이 레지스트리에서 읽는다

**파일:** `src/hmi/web/test/test_shared_controls.py`, `src/hmi/web/test/test_surface_typography_focus_contracts.py`, `test/test_web_dialog_contract.py`

- 각 파일의 `SURFACES` 상수를 `surface_registry.for_contract(<계약명>)` 호출로 바꾼다.
- `test_shared_controls`는 파일과 폴더를 섞어 받는다 (`runtime/sensing/web/dashboard.html`). 로더는 등록 `path`를 그대로 내주므로 이 형태가 그대로 유지된다.
- 루트 `test/test_web_dialog_contract.py`는 `test/conftest.py`가 `deploy/...`를 `sys.path`에 얹는 것과 같은 방식으로 `src/hmi/web/test`를 얹어 로더를 임포트한다.
- **판정이 달라지지 않아야 한다.** 이전/이후 결과 비교를 T6에서 잡는다.

## T4 — 셸 점검도 추적 파일 한정으로

**파일:** `src/hmi/web/test/test_shared_controls.py::test_a_browser_page_starts_from_the_shell`

`ROOT.rglob("*.html")`을 `discover_html`로 바꾼다. 파일명 필터(`index.html`·`dashboard.html`)는 그대로다. 이 한 줄로 로컬과 CI의 조건이 같아진다 — 지금은 로컬만 빨갛고 CI는 초록이다.

## T5 — 회귀 범위 확인

```bash
python -m pytest src/hmi/web/test -q
python -m pytest test/test_web_dialog_contract.py test/architecture/test_document_placement.py -q
python -m pytest src/hmi/dashboard/test -q
python -m pytest src/site/fleet/test src/site/games/test -q
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q
```

**완료 판정** — 아래는 이 계획과 무관한 기존 실패이고, 이 계획이 건드리지 않았다는 것을 확인하는 쪽으로 잡는다.

| 항목 | 이 계획 전 (로컬) | 이 계획 후 기대 |
|---|---|---|
| `src/hmi/web/test` failed | 4 | **3** — Android 산출물 1건이 T4로 초록이 되고, 남는 셋(`styles.css` `.vision-corner-overlay` 포커스 토큰, `.vision-corner-modes` `ui-button` 재도색, `system.js:50` 버튼 변수)은 그대로다 |
| `test/architecture/test_document_placement.py` | 1 failed (`PRODUCT.md`) | 1 failed 그대로 — 루트 `PRODUCT.md`가 `ROOT_FILES`에 없다 (`27e6da33`의 몫) |
| harness lint | 0 error | 0 error |
| `test_harness_contracts.py` | 78 passed | 78 passed |

## 산출물

| 파일 | 변화 |
|---|---|
| `src/hmi/web/surfaces.yaml` | 신규 — 표면 계약 적용 범위의 단일 출처 |
| `src/hmi/web/test/surface_registry.py` | 신규 — 로더 + 추적 파일 HTML 발견 |
| `src/hmi/web/test/test_surface_registry.py` | 신규 — 등록 누락·필드 규칙·상수 재정의 검사 |
| `src/hmi/web/test/test_shared_controls.py` | `SURFACES` 상수 제거, 셸 점검 추적 파일 한정 |
| `src/hmi/web/test/test_surface_typography_focus_contracts.py` | `SURFACES` 상수 제거 |
| `test/test_web_dialog_contract.py` | `SURFACES` 상수 제거 |
| `docs/logs.md` | 항목 1개 + 변이 확인 5건의 기록 |

## 끝나고

- D-329를 Proposed에서 Accepted로 올릴 때는 T2의 변이 확인 기록을 근거로 삼는다.
- `src/hmi/pilot`의 HTML이 처음 생기는 커밋은 이 레지스트리에 등록을 함께 넣는다 (D-330이 아니라 D-323 실행 계획의 해당 T-스텝).
- `matrix.json` 스키마와 회차 간 파일명 규칙은 다음 회차에서 정하고, 정해진 뒤에 시험을 넣는다.
