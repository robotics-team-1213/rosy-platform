# D-427 B 단계 소스 이전 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan wave by wave.

**Status:** PLAN (2026-10-03). 아직 아무 파일도 옮기지 않았다. 기준 main `541a30fa7`. 각 wave를 시작할 때 HEAD, 매니페스트, 진행 중 브랜치를 다시 센다. 아래 숫자는 이 기준의 `git ls-files` 결과다.

**Goal:** [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md) §6 "이후(B)"를 실행한다. `tools/harness/platform_parts.yaml`의 각 root를 `path`에서 `d427_target`으로 옮긴다. 순서는 §6을 따른다: learning → contracts → operations → middleware, Pinky CORE는 마지막.

**Move table:** 매니페스트가 이동 표다. 이 문서는 표를 다시 적지 않는다. wave 묶음, 소비자, 선행 조건, 검증만 적는다. wave 0에서 매니페스트에 `wave` 필드를 넣은 뒤에는 다음 명령으로 현재 표를 출력한다.

```bash
python -c "import yaml;[print(r.get('wave','-'),r['path'],'->',r['d427_target']) for r in yaml.safe_load(open('tools/harness/platform_parts.yaml',encoding='utf-8'))['roots'] if r['path']!=r['d427_target']]"
```

## 범위와 비목표

| 범위 | 비목표 |
|---|---|
| source root 이동(`git mv`)과 같은 커밋의 살아 있는 소비자 수정 | 패키지 이름, ROS 패키지·노드·토픽·서비스 이름, API 경로, 공개 wire 변경(D-231, D-427 §6) |
| 매니페스트 `path` 갱신, `KNOWN_VIOLATIONS` 축소 | 런타임 동작 변경. 이동 커밋은 동작이 같아야 한다 |
| colcon 탐색 root, wheel 빌드 목록, Docker `COPY` 원본 경로, harness module path, 현재 AGENTS·README | 설치 경로·장치 경로·컨테이너 내부 경로(`/opt/rosy/...`, `<release>/deploy/...`) 변경 |
| wave 2의 계약 타입 추출(re-export로 기존 import 유지) | Episode·DatasetManifest·PolicyArtifact의 스키마 설계(D-427 후속 2의 별도 설계) |
| | 장치 수용(DEVICE/FIELD). 이동 출구는 SOURCE·ARTIFACT 동등성까지다 |
| | 역사 문서 수정(D-226). `docs/adr`, `docs/plans`, `docs/validation`, `logs.md`, `progress.md`의 과거 항목은 옛 경로를 그대로 둔다 |

출구 이름은 [D-310 계획](2026-09-27-product-source-layout-migration.md)과 같다. `SOURCE_CANDIDATE`(host·harness·colcon), `ARTIFACT_EQUIVALENT`(이미지·payload 설치 내용 비교), `DEVICE_ACCEPTED`(이 계획 밖).

## 이전 이동에서 가져온 규칙

`docs/solutions/workflow-issues/`의 교훈을 각 커밋의 점검 항목으로 쓴다.

1. **세 가지 경로를 구분한다** ([blanket-path-rewrite](../solutions/workflow-issues/blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md)). 저장소 경로만 고친다. 설치·release 경로(`/opt/rosy/src/site/fleet/`, `/opt/rosy/apps/gateway/src`, `<release>/deploy/robot/native/`)는 장치 계약이므로 고치지 않는다. 트리 전체 `sed`는 금지한다. 소비자 목록을 만들고 파일별로 고친다.
2. **identity hash 입력은 바이트를 바꾸지 않는다** ([payload-runtime-id](../solutions/workflow-issues/payload-runtime-id-hashes-comments-too-2026-10-01.md)). `deploy/robot/pinky_pro/image/device-python-requirements.txt`의 주석 경로가 낡아도 그대로 둔다. `test/test_python_runtime_id.py`가 지킨다.
3. **경로 범위 시험이 넓어지지 않았는지 본다** ([folder-move-widens](../solutions/workflow-issues/folder-move-widens-path-scoped-contract-tests-2026-09-25.md)). "X 아래 전부"로 범위를 잡은 시험은 이동 뒤 다른 패키지를 끌어들일 수 있다. 이동 전후 검사 대상 파일 수를 비교한다.
4. **`parents[N]`는 깊이가 바뀐다.** 저장소 root를 찾는 `parents[N]`가 이동 대상 root에 464개, `test/`에 187개 있다(wave별 수는 각 wave의 소비자 항목). 시험 코드는 N을 고친다. 설치되어 실행되는 코드가 checkout 경로를 계산하면 고치지 말고 결함으로 보고한다([installed-layout-import](../solutions/workflow-issues/installed-layout-import-passes-repo-tests-2026-09-22.md)).
5. **공유 index에서는 자기 경로만 stage한다** ([peers-share-one-git-index](../solutions/workflow-issues/peers-share-one-git-index-never-amend-stage-only-your-line-2026-09-26.md), [parallel-session-sweeps](../solutions/workflow-issues/parallel-session-sweeps-shared-tree-2026-09-29.md)). 모든 wave는 `.worktrees/` worktree에서 한다. `git add -A`, amend, bare `git stash`는 쓰지 않는다.
6. **커밋을 검증한다** ([verify-what-you-ship](../solutions/workflow-issues/verify-what-you-ship-the-working-tree-is-not-the-commit.md)). 게이트는 커밋한 SHA의 깨끗한 checkout에서 돈다.
7. **시험이 코드와 같은 문자열을 반복하면 sed 앞에서 동어반복이 된다.** 경로를 확인하는 시험은 문자열 비교 대신 존재 여부를 보거나 생산자(매니페스트, payload builder)에서 경로를 얻는다.

## 현재 구조에서 확인한 사실

- ROS 패키지 27개가 모두 `src/` 아래에 있다. CI는 `cd src && colcon build`, native payload는 `colcon build --base-paths src`와 `colcon list --base-paths src`(inventory)를 쓴다. 따라서 **ROS 패키지 하나를 `src/` 밖으로 옮기면 CI 빌드와 native payload inventory에서 그 패키지가 조용히 사라진다.** native payload는 장치 전용이 아닌 `isaac_sim`, `fleet`, `rosy_cell`, `rosy_vision`, `games`까지 `src/` 전체를 빌드한다. wave 0에서 탐색 root를 먼저 바꾸는 이유다.
- `deploy/robot/pinky_pro/image/resolve-required-source-paths.py`는 한 개의 `source_root`만 `rglob`한다.
- 매니페스트의 `d427_target` 몇 개는 여러 패키지가 같은 폴더를 가리킨다. `middleware/core` ← gateway·services·events·api_web(ROS 패키지 4개), `middleware/apps/device/pinky` ← bringup·profile, `middleware/apps/device/omx` ← adapter·profile·`apps/agent`. 패키지 폴더는 중첩될 수 없다(D-310 `profile/` 교훈). wave 0에서 leaf 경로로 나눈다.
- 매니페스트가 하위 폴더를 다른 파트로 떼어 둔 root가 있다. `src/runtime/sensing`(recorder·map 자산·sim 도구), `src/sim/gz_sim/{launch,scripts}`, `src/site/fleet/fleet/server/web`, `modules/execution/src/rosy/execution/{local,api,site}`, `src/products/omx/adapter`의 `lerobot_export.py`. 이 하위 폴더들은 한 패키지의 설치물 안에 있다. 떼어 내면 설치 내용이 바뀌므로 단순 이동이 아니다.
- `KNOWN_VIOLATIONS`와 `PACKAGE_DIR_ROOTS`는 root `path`를 key로 쓴다. 이대로 두면 이동 커밋마다 key도 고쳐야 한다.
- 사이트 PC 설치 경로가 하나 저장소 경로에 묶여 있다. `deploy/site/rosy-model-watch.service`는 `/opt/rosy/model-watch/src/tools/perception/model/watch.py`를 실행한다. 이 경로의 `src`는 사이트 PC의 소스 사본이다. 사본을 새 구조로 갱신하면 unit도 다시 설치해야 한다.

## Wave 표

숫자 = 해당 root가 직접 소유한 tracked 파일 수(하위 root 제외). 겹치는 브랜치(각 wave 절)는 `git branch --no-merged main` 중 그 root의 파일을 바꾸는 브랜치이고, 괄호 숫자는 그 root에서 바뀐 파일 수다.

| Wave | 브랜치 | root (files) | 합계 | 이미지 영향 | 줄일 위반 |
|---|---|---|---|---|---|
| 0 | `refactor/d427-w0-mechanism` | 이동 없음 | 0 | native payload 스크립트만(inventory 동일 증명) | 0 |
| 1 | `refactor/d427-w1-learning` | `tools/perception`(62) + `tools/perception/prototype`(23), `src/sim/isaac_sim`(37), `omx_adapter/lerobot_export.py`+시험(2), `data`(11, Q3) | 124(+11) | IO·native에서 `omx_adapter.lerobot_export` 모듈 하나 빠짐 | 1 (`omx adapter → external:lerobot`) |
| 2 | `refactor/d427-w2-contracts` | 기존 root 이동 없음. 새 `contracts/` wheel과 타입 추출 | 새 파일 ~10 | 없음 | 3 (execution api→skills api, palletizing→skills api, execution api→local) |
| 3a | `refactor/d427-w3a-ops-modules` | `modules/world`(3), `modules/processes/palletizing`(16), `apps/gateway`(4), execution `api`(2)+`site`(3)+metadata(1) | 29 | Fleet 사이트 이미지 `COPY` | 0 |
| 3b | `refactor/d427-w3b-site-apps` | `src/site/vision`(46), `src/site/games`(56), `src/site/cell`(32), `src/site/cam`(109) | 243 | Vision 사이트 이미지, native inventory(패키지 이름 동일) | 0 |
| 3c | `refactor/d427-w3c-fleet` | `src/site/fleet`(231) + `fleet/server/web`(24, 패키지 안에 그대로) | 255 | Fleet 사이트 이미지, native inventory | 0 |
| 4a | `refactor/d427-w4a-mw-modules` | `modules/skills/api`(3), `modules/skills/manipulation`(3), execution `local`(2), `apps/agent`(6), `firmware/dock`(8), `firmware/signal`(15) | 37 | 없음 | 0 |
| 4b | `refactor/d427-w4b-ui` | `src/hmi/web_common`(53), `src/hmi/dashboard`(73), `src/hmi/pilot`(49), `src/hmi/face`(34) | 209 | CORE·IO·native, Fleet 이미지(`web-common`) | 0 |
| 4c | `refactor/d427-w4c-device` | `src/drivers/imu_bno055`(20), `src/products/pinky_pro/{adc,lamp,led,bringup,profile}`(96), `src/products/omx/{adapter,profile}`(82), `src/sim/description`(38), `src/sim/gz_sim` 전체(86), `src/runtime/navigation`(49) | 371 | IO·native | 0 |
| 4d | `refactor/d427-w4d-core` | `src/contracts/foundation`(69), `src/contracts/interfaces`(12), `src/runtime/{gateway,services,events,api_web}`(340) | 421 | CORE·IO·native, Fleet·Vision 이미지(`core_common`) | 0 |
| 4e | `refactor/d427-w4e-sensing` | `src/runtime/sensing`(605) | 605 | IO·native, Fleet 이미지(map 자산 `COPY`) | 0 |
| 5 | `refactor/d427-w5-cleanup` | 빈 `src/`, `modules/`, `apps/` 삭제, `legacy` 필드 정리 | — | 없음 | 0 |

이동 후에도 남는 위반 5건은 이 계획이 없애지 않는다. `apps/agent → palletizing`, `integrations/robots/omx → {skills/api, skills/manipulation, omx adapter}`(3건), `tools/perception → sensing`. wave 2 뒤 마지막 건은 import 수가 줄지만 edge는 남는다(Q5, Q7). 이동 커밋은 key 이름만 바꾸며 집합 크기를 늘리지 않는다.

`profiles/`(2), `integrations/robots/omx`(4)는 이미 목표 위치에 있다. 최상위 `modules/`·`apps/`·`integrations/`·`profiles/`의 49파일 중 43파일(`modules` 33, `apps` 10)은 3a·4a에서 파트 안으로 옮긴다.

## Wave 0: 이동 장치 결정 (파일 이동 없음)

**선행:** 없음. 이 wave가 main에 들어가기 전에는 어떤 이동도 시작하지 않는다.

1. **leaf 목표.** 여러 패키지가 같은 목표를 가리키는 root의 `d427_target`을 패키지 하나당 폴더 하나로 나눈다.
   - `middleware/core/{gateway,services,events,api_web}`, `middleware/core/navigation`은 그대로.
   - `middleware/apps/device/pinky/{bringup,profile,description}`.
   - `middleware/apps/device/omx/{adapter,profile,agent}`.
   - `modules/execution` 메타데이터는 Q4 결정에 따른다.
   - 시험 `test_package_targets_are_leaf_unique`: `package.xml`이나 `pyproject.toml`이 있는 root의 목표끼리 같거나 서로의 하위이면 실패한다. 단, 목표가 다른 패키지 목표의 **컨테이너**인 경우는 허용한다(`middleware/core`는 패키지가 아니므로).
2. **wave 필드.** 각 root에 `wave: 1|3a|…|4e` 또는 `wave: none`(이미 목표 위치)을 넣는다. 시험: 이동하지 않은 root는 모두 wave를 가진다.
3. **안정 key.** `KNOWN_VIOLATIONS`와 `PACKAGE_DIR_ROOTS`의 key를 `path`에서 `d427_target`으로 바꾼다. 그러면 이동 커밋은 매니페스트의 `path`만 바꾼다. `_edges`는 `importer["d427_target"]`을 key로 낸다. leaf 목표가 유일해지는 1번 뒤에 한다.
4. **이동 완료 판정.** root는 `path == d427_target`이면 이동이 끝난 것이다. 이동 커밋은 옛 경로를 `legacy: <old path>`로 남긴다. 새 시험 `test_moved_roots_leave_nothing_behind`:
   - `legacy` 아래에 tracked 파일이 없다. 이동 뒤 rebase된 브랜치가 옛 경로에 새 파일을 만들면 여기서 잡힌다.
   - 살아 있는 소비자에 옛 **저장소 상대** 경로가 없다. 대상은 `.github/`, `deploy/`, `tools/`, `test/`, 파트 root 아래의 비-Markdown 파일과 `.dockerignore`, `*.dockerignore`, `.gitattributes`, 현재 `AGENTS.md`·`README.md`다. 정규식은 `(?<![\w/.-])<legacy>(?=[/"'\s:)]|$)`이다. 앞에 `/`가 붙은 설치 경로(`/opt/rosy/src/...`, `/repo/src/...`는 아래 예외)는 제외된다.
   - 제외: `docs/adr/`, `docs/plans/`, `docs/validation/`, 모든 `logs.md`·`progress.md`(D-226), 그리고 바이트 고정 파일 목록 `FROZEN_BYTES = {"deploy/robot/pinky_pro/image/device-python-requirements.txt"}`.
   - `/repo/src/...`(OMX 컨테이너가 저장소를 `/repo`에 mount) 문자열은 저장소 경로이므로 따로 검사한다. `deploy/robot/omx/*.sh`의 `PYTHONPATH="/repo/src/..."`가 여기 해당한다.
   - 변이 증명: 옛 경로 문자열 하나를 `deploy/`에 다시 넣으면 실패하는지 확인하고 되돌린다.
5. **colcon 탐색 root를 한 곳에서.** 매니페스트에 `colcon_roots: [src]`를 넣는다. 다음 소비자가 이 목록을 읽거나 같은 값을 쓰도록 바꾼다. 시험이 일치를 확인한다.
   - `.github/workflows/ci.yml`: `cd src && colcon build`를 저장소 root에서 `colcon build --base-paths <roots>`로. flake8·pytest 단계의 `cd src` 상대 경로도 저장소 상대로.
   - `deploy/robot/pinky_pro/image/build-native-payload.sh`: `rosdep --from-paths`, `colcon build/list --base-paths`. `test/test_image_customization_contract.py`의 문자열 단정은 매니페스트에서 기대값을 만들도록 바꾼다.
   - `resolve-required-source-paths.py`: 여러 root를 받는다. 중복 이름 거부는 root 전체에 걸쳐 유지한다.
   - `tools/build_wsl.sh`, `tools/sync_*.sh`.
   - 시험 `test_ros_package_names_are_frozen`: 모든 `colcon_roots`에서 찾은 `package.xml` 이름 집합이 현재 27개 집합과 같고, 각 이름이 정확히 한 경로에 있다. `COLCON_IGNORE`가 있는 `src/site/cam`은 집합에 포함하되 colcon 탐색 대상에서 빠지는 사실을 기록한다. `test_target_layout.py`의 `SRC` 기준 `TARGET` 표는 이 시험과 매니페스트로 대체한다. 패키지 이름 보존 단정은 옮겨 온다.
6. **증거.** 값이 `[src]`이므로 inventory는 같아야 한다. WSL Ubuntu에서 `colcon list --base-paths src --names-only` 전후 비교, 그리고 ARM64 `build-native-payload.yml` 1회로 `rosy-packages.txt`가 이전 release와 같음을 확인한다. 이 증명 뒤로는 각 wave가 WSL `colcon list` 비교만으로 inventory 동등성을 보이고, payload 실빌드는 image wave(4b–4e)와 release 전에만 한다.

**검증:** `python -m pytest test/architecture -q`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_image_customization_contract.py test/test_native_ros_payload.py test/test_python_runtime_id.py -q`, WSL colcon list 비교, ARM64 payload 1회.
**롤백:** 커밋 단위 `git revert`. 동작 변경이 없다.

## 각 이동 커밋의 공통 절차

한 커밋은 한 영역(아래 wave 안의 한 줄)이다. 커밋 하나가 녹색이어야 하고 `git revert` 하나로 되돌아가야 한다.

1. 소비자 목록을 만든다. 옛 경로를 `ROOT`라 할 때:
   ```bash
   git grep -n -F "ROOT" -- . ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!**/logs.md' ':!**/progress.md'
   git grep -n -E "parents\[[0-9]\]|sys\.path\.(insert|append)|PYTHONPATH" -- ROOT test tools deploy
   ```
   결과를 저장소 경로, 설치 경로, 바이트 고정 파일로 나눈 목록을 `X:/DevTemp/rosy-d427/<wave>/consumers.txt`에 남긴다.
2. `git mv ROOT TARGET`. 옮긴 파일 안의 수정은 `parents[N]` 깊이와 저장소 상대 경로로 제한한다. 그래야 rename 유사도가 높게 유지되어 peer 브랜치 rebase가 rename을 따라간다.
3. 같은 커밋에서 고친다: 매니페스트 `path`와 `legacy`, `tools/harness/harness.yaml`의 module `path`·`tests`·`functional`, `.github/workflows/ci.yml`(wheel 목록·flake8·pytest 경로·path filter, `android.yml`), Dockerfile `COPY` 원본(목적지는 그대로), `.dockerignore`·`deploy/site/*.dockerignore` 허용 목록, `.gitattributes`, `deploy/` 스크립트의 저장소 경로, 시험의 경로 상수, `test/architecture/test_platform_dependency_boundaries.py`의 경로 표, `AGENTS.md`(저장소·폴더 지도, 루트 `AGENTS.md`의 pytest 줄), 현재 README.
4. `python tools/harness/rosy_harness.py generate` 후 lint.
5. 게이트(아래 wave별)를 돌리고 커밋한다. 메시지: `refactor(d427): move <root> to <target>`.

## Wave 1: learning

**선행:**
- wave 0이 main에 있다.
- `integrate/commit-merge-20261003`(오늘, `tools/perception` 20파일·omx adapter 20파일)과 `feat/d423-object-range-detection`(`tools/perception` 16파일)이 착지하거나 rebase 계획을 정했다. `feat/rosy-cell-c3-gazebo`(omx adapter 12파일)는 lerobot_export 커밋 전에 확인한다.
- 이미지 창: 1c는 IO·native 설치 내용에서 모듈 하나가 빠지므로 release 사이에 한다(D-191). 1a·1b는 이미지 밖이다(1b의 `isaac_sim`은 payload inventory에 들어 있다. wave 0의 root 목록에 `learning`을 추가하면 이름 집합이 같다).

| 커밋 | 이동 | 소비자 |
|---|---|---|
| 1a | `tools/perception` → `learning/training/perception`(내부 구조 유지, Q7), `tools/perception/prototype` → `tools/perception_prototype` | `parents[N]` 38, sys.path 47(`HERE.parents[2] / "src" / "runtime" / "sensing"` 등. 4d·4e 전까지 sensing 경로는 옛 위치다), `deploy/site/rosy-model-watch.service`·`install-model-watch.sh`(사이트 PC `src` 사본 기준 경로: 갱신 후 재설치 안내를 `deploy/site/README.md`에), `src/runtime/sensing/control/recording.py` 주석, `test/test_learned_perception_pinky_runbook.py`, `test_module_structure.py`, 매니페스트 `test_every_tools_subfolder_has_its_own_root` |
| 1b | `src/sim/isaac_sim` → `learning/envs/isaac`, `colcon_roots`에 `learning` 추가 | `prepare_urdf.py`의 `parents[1] / "description"`(형제 `src/sim/description`에 의존. 4c까지 옛 경로를 저장소 root 기준으로 계산), 시험 `parents[2]`, `harness.yaml` isaac_sim module, `test/test_pinky_release_impact.py`, `src/products/omx/adapter/config/omx_f_kinematics.yaml` 주석, `src/AGENTS.md`의 pytest 줄 |
| 1c | `omx_adapter/lerobot_export.py`와 `test/test_lerobot_export.py` → `learning/curation/omx/`(새 root, part learning) | `from .demonstration import validate_episode`를 `omx_adapter.demonstration` 절대 import로(learning이 middleware를 import하게 되므로 새 위반이 생긴다. Q6 참고), `deploy/robot/omx/README.md`의 `python -m omx_adapter.lerobot_export` 실행법, `KNOWN_VIOLATIONS`에서 `external:lerobot` 삭제 |
| 1d | `data` → Q3 결정. 기본 권고는 이동하지 않음 | 이동한다면 `data/perception`·`data/teleop/learning` 기본값을 쓰는 `tools/perception/*` 12곳, `tools/calibration/*` 3곳, `tools/lane_replay.py`, `tools/run_data.py`, `.gitignore`, `deploy/site/model-watch.yaml.example`, `deploy/site/README.md` |

**게이트:** `python -m pytest learning/training/perception/test -q`(옛 `tools/perception/test` 28파일), `python -m pytest learning/envs/isaac/test -q`, `python -m pytest src/products/omx/adapter/test -q`, `python -m pytest learning/curation/omx -q`, `python -m pytest test/architecture -q`, harness lint, WSL `colcon list` 이름 집합 동일. 1c는 IO 이미지 빌드 1회로 `omx_adapter`의 설치 모듈 차이가 `lerobot_export` 하나뿐임을 확인한다.

## Wave 2: contracts

**선행:** wave 1. D-427 후속 2(Episode·DatasetManifest·PolicyArtifact 설계)는 2b의 선행이다. 2a는 기존 타입을 옮기기만 하므로 그것을 기다리지 않는다. `feat/rosy-cell-c3-gazebo`(palletizing 6파일) 상태를 확인한다.

- **2a 타입 추출.** `rosy.skills.api.SkillInvocation`과 `rosy.execution.local.receipts`의 `AttemptIdentity`·`ReceiptBinding`을 새 wheel `contracts/skill`(import `rosy.contracts.skill`, part contracts)로 옮긴다. 원래 모듈은 같은 객체를 re-export해서 기존 import와 pickle/JSON 형식이 그대로다. `execution/api/plan.py`와 `palletizing/plan_bundle.py`는 새 이름을 import한다. CI wheel 목록에 추가한다. 위반 3건이 빠진다(Q5).
- **2b 학습 계약 자리.** 후속 2의 설계가 정한 타입을 `contracts/learning`(import `rosy.contracts.learning`)에 둔다. 녹화 변환기(`rosy.recording.session/1`, D-411 Pilot 녹화, `rosy.omx-demonstration.v1` → Episode profile)는 `learning/curation/`에 둔다. `control.sensing.perception.learned.manifest`의 `rosy.perception.model/1` 스키마는 PolicyArtifact의 인식 profile로 옮기고 `control`은 re-export한다. 이것으로 `tools/perception → sensing` edge의 import가 줄지만, 재생 게이트가 장치 알고리즘(`lane_mask`, `runner`, `lane_keep`, `road_state`)을 그대로 돌려야 하므로 edge는 남는다(Q7).

**게이트:** wheel 빌드와 X: venv 설치 검사(D-413 Task 2 절차), `python -m pytest test/architecture -q`, 관련 소비자 suite(`modules/*` 시험, `test/test_platform_*`), harness lint. 이미지 영향 없음.

## Wave 3: operations

**공통 선행:** wave 2a(3a의 execution 분리가 그것에 의존). 사이트 이미지 wave는 사이트 배포 사이에 한다.

### 3a 작은 wheel

`modules/world` → `operations/world`, `modules/processes/palletizing` → `operations/processes/palletizing`, `apps/gateway` → `operations/apps/fleet`, execution `api`·`site` → `operations/execution/{api,site}`(Q4).

- 소비자: `ci.yml` wheel 경로 목록, `deploy/site/Dockerfile.fleet`의 `COPY apps/gateway/src/`(목적지 `/opt/rosy/apps/gateway/src/`와 `PYTHONPATH`는 설치 경로이므로 그대로), `profiles/installations/*.yaml`, `test_platform_dependency_boundaries.py`, `test/test_platform_*`.
- 게이트: wheel 빌드·설치 검사, Fleet 사이트 이미지 빌드와 `rosy-site-gateway` fake lifespan, architecture, lint.
- 겹치는 브랜치: `feat/rosy-cell-c3-gazebo`(palletizing).

### 3b 사이트 앱

`src/site/vision` → `operations/vision`, `src/site/games` → `operations/apps/games`, `src/site/cell` → `operations/processes/cell`, `src/site/cam` → `operations/ui/cam`. 영역마다 한 커밋. `colcon_roots`에 `operations`를 추가한다.

- 소비자: `deploy/site/Dockerfile.vision` `COPY` 원본 4줄, `Dockerfile.vision.dockerignore`, `.github/workflows/android.yml`(cam Gradle 경로), cam `COLCON_IGNORE`, `test/architecture/test_app_identity.py`, D-425 Task 10의 cam 항목(이 커밋이 그 이동을 대신하며 목적지만 다르다).
- 게이트: 영역별 pytest(`operations/vision/test`, `operations/apps/games/test`, `operations/processes/cell/test`), Vision 이미지 빌드, cam 단위시험·APK assemble, WSL `colcon list`·`colcon build --packages-select rosy_vision games rosy_cell`.
- 겹치는 브랜치: `feat/overhead-markerless-tracking`(vision 18), `feat/rosy-cell-c3-gazebo`(cell 10).

### 3c Fleet

`src/site/fleet` → `operations/fleet`, 패키지 전체. `fleet/server/web` root는 패키지 안에 남아 경로가 `operations/fleet/fleet/server/web`이 된다. `operations/ui/console`로 떼어 내는 일은 D-425 Task 9(설치 wrapper 유지)이며, D-425 Task 6(설치·정적 서빙 계약)이 먼저다.

- 소비자: `Dockerfile.fleet`의 `COPY src/site/fleet/`(목적지 `/opt/rosy/src/site/fleet/` 유지), `deploy/robot/omx/probe_fleet_ros_vendor_sim.sh`의 `/repo/src/site/fleet` PYTHONPATH, `parents[N]` 32, sys.path 5, 루트 `AGENTS.md` pytest 줄, `src/site/fleet` 하위 AGENTS.
- 게이트: `python -m pytest operations/fleet/test -q`(기준 1336 passed/7 skipped), Fleet 브라우저 suite(기존 실패 목록과 비교), Fleet 이미지 빌드, architecture, lint, WSL colcon.
- 겹치는 브랜치(가장 많다): `feat/overhead-markerless-tracking`(17+web 10), `feat/d355-goal-evidence-verifier`(15), `feat/d414-fleet-cancel-all`(14+4), `refactor/d362-p0-1-fleet-app-routes`(10), `fix/d407-console-link-and-event-fields`(9), `docs/d416-pinky-device-actions`(9), `integrate/commit-merge-20261003`(8+13), `feat/camera-preview-rectification`(6), 9/28 UI 브랜치 4개(web 1–3).

## Wave 4: middleware

**공통 선행:** wave 3. 4b–4e는 Pinky 이미지 입력이므로 release가 나간 직후 시작해서 다음 release cut 전에 끝낸다(D-191). 시작 전에 release를 맡은 peer 세션에 알린다. auto-update(D-412)는 release된 payload만 적용하므로 main 이동 자체는 로봇에 닿지 않는다.

### 4a 작은 middleware root

`modules/skills/{api,manipulation}` → `middleware/skills/*`, execution `local` → `middleware/execution/local`(Q4), `apps/agent` → `middleware/apps/device/omx/agent`, `firmware/{dock,signal}` → `middleware/firmware/*`. 끝나면 최상위 `modules/`·`apps/`가 빈다.

- 소비자: `ci.yml` wheel 목록, `profiles/installations/omx_cell_sim.yaml`, `test_platform_dependency_boundaries.py`의 root tuple `("modules", "integrations", "apps", "profiles")`, firmware 시험 3개.
- 게이트: wheel 설치 검사, `omx_cell_sim` 프로파일 fake lifecycle, architecture, lint.

### 4b UI (D-425 Tasks 7·8·10의 목적지 변경)

`src/hmi/web_common` → `shared/web`, `dashboard` → `middleware/ui/robot`, `pilot` → `middleware/ui/pilot`, `face` → `middleware/ui/face`. 패키지별 한 커밋. D-425 Task 6이 먼저다. 기존 ament wrapper(`package.xml`·`CMakeLists.txt`)는 패키지와 함께 옮기며 설치 share 경로(`share/web_common`, `share/dashboard`, `share/pilot`)는 같다. `colcon_roots`에 `middleware`·`shared`를 추가한다.

- 소비자: Pinky `Dockerfile` CORE·IO stage `COPY`(`src/hmi/*` 5줄), `.dockerignore`, `Dockerfile.fleet`의 `COPY src/hmi/web_common/`(목적지 `/opt/rosy/web-common/` 유지), `deploy/robot/pinky_pro/release/{build_payload_release.py,arm64_release_builder.py}`, `tools/sync_rosy*.sh`, `parents[N]` 64, CORE fallback 경로 상수.
- 게이트: 각 패키지 시험, Robot/Pilot/Fleet 브라우저 suite, WSL `colcon build --packages-up-to core pinky_pro web_common dashboard pilot` + `ros2 pkg prefix`, CORE·IO 이미지 빌드와 ament index 비교, ARM64 payload 1회(inventory·share 비교).
- 겹치는 브랜치: `integrate/commit-merge-20261003`(pilot 28, web_common 7), `refactor/d362-p1-dashboard-split`(11), `feat/d423-object-range-detection`(pilot 8), `release/floor-g4-minimal`(7), `docs/d395-plan`·`docs/ui-boundaries-d322`(6), `feat/d400-plan2-rosim`(dashboard 5, web_common 2), `refactor/web-transport`(4).

### 4c 장치 패키지 (IO·native)

`src/drivers/imu_bno055`, `src/products/pinky_pro/{adc,lamp,led,bringup,profile}`, `src/products/omx/{adapter,profile}`, `src/sim/description`, `src/runtime/navigation`, `src/sim/gz_sim`(패키지 전체 → `integrations/simulation/gazebo`. `launch/`·`scripts/` 분리는 Q2). `colcon_roots`에 `integrations` 추가.

- 소비자: Pinky `Dockerfile` IO stage `COPY` 7줄과 CORE stage의 `cyclonedds_localhost.xml`(원본만), `deploy/robot/omx/Dockerfile*`과 `/repo/src/products/omx/adapter` PYTHONPATH 3곳, CI의 `touch src/sim/gz_sim/COLCON_IGNORE`, `.gitattributes`, `harness.yaml`, `test/test_robot_runtime.py`·`test_image_customization_contract.py`·`test_native_systemd_contract.py`, 1b가 남긴 isaac `prepare_urdf.py`의 description 경로.
- 게이트: 패키지 시험(adapter 333 passed/5 skipped 기준), WSL `colcon build` + share/launch lookup, IO 이미지와 native payload의 설치 closure 비교(D-310 Task 5 방식), Gazebo 2-pinky 기동 스모크(WSL).
- 겹치는 브랜치: `feat/rosy-cell-c3-gazebo`(adapter 12, gz_sim 4), `codex/pinky-integrated-current`(gz_sim 20), `feat/d400-plan2-rosim`(gz_sim 16).

### 4d Pinky CORE와 contracts (마지막 앞)

`src/contracts/foundation` → `contracts/foundation`, `src/contracts/interfaces` → `contracts/ros_idl`, `src/runtime/{gateway,services,events,api_web}` → `middleware/core/*`. `colcon_roots`에 `contracts` 추가. contracts 두 root는 D-427 순서상 contracts 파트지만 CORE 이미지 입력이므로 여기서 옮긴다.

- 소비자: Pinky `Dockerfile` `COPY` 8줄, `Dockerfile.fleet`·`Dockerfile.vision`의 `COPY src/contracts/foundation/core_common/`(목적지 유지), `ci.yml` flake8·pytest 경로, `deploy/robot/omx/run_pilot_sim.sh` PYTHONPATH, `parents[N]` 107(gateway 74가 대부분), sys.path 10, 루트 `AGENTS.md` pytest 줄.
- 게이트: 루트 `AGENTS.md`의 분리 pytest 두 줄(새 경로), architecture, lint, WSL `colcon build`와 `ros2 pkg executables core`, CORE·IO·native 설치 closure 비교, Fleet·Vision 이미지 빌드.
- 겹치는 브랜치: `feat/d400-plan2-rosim`(gateway 16, services 11), `feat/d415-saf003-fleet-loss`(9+8+5+3), `fix/d407-console-link-and-event-fields`, `docs/d416-pinky-device-actions`, `feat/d418-ssh-access`·`feat/d418-robot`(api_web 7), `feat/gz-learned-lane-drive`, `fix/lane-keep-wall-base`, `fix/lidar-self-mask`, `integrate/commit-merge-20261003`(8+8+9+8).

### 4e sensing (마지막)

`src/runtime/sensing` → `middleware/perception`, 패키지 `control` 전체. recorder·map 자산·sim 도구 분리는 Q2.

- 소비자: Pinky `Dockerfile` IO `COPY`, `.dockerignore` 허용 2줄, `.gitattributes` 6줄, `Dockerfile.fleet`의 map 자산 `COPY` 원본(목적지 `/opt/rosy/maps/map_v2_fleet/` 유지), 1a가 남긴 `learning/training/perception`의 sensing sys.path, `parents[N]` 124, sys.path 18, 루트 `AGENTS.md` sensing pytest 줄.
- 게이트: `python -m pytest middleware/perception/test -q`(따로 실행: gateway와 `test_battery.py` basename이 겹친다), learning perception 시험, WSL colcon, IO·native closure, Fleet 이미지 빌드, Gazebo lane 스모크.
- 겹치는 브랜치: `integrate/commit-merge-20261003`(44), `feat/d423-object-range-detection`(41), `feat/d400-plan2-rosim`(14), `feat/gz-learned-lane-drive`(14), `refactor/d362-p0-2-sensing-calibration-sequence`(9), `fix/g4-teleop-watchdog-and-stop-epsilon`(4).

## Wave 5: 정리

빈 `src/`, `modules/`, `apps/`를 지운다(`src/AGENTS.md`, `src/sim/AGENTS.md` 등 폴더 노트 포함). `colcon_roots`에서 `src`를 뺀다. 모든 root가 `path == d427_target`이면 `legacy` 필드와 그 시험은 한 release 동안 유지한 뒤 지운다(그동안 rebase되는 브랜치를 잡기 위해서다). 루트 `AGENTS.md` Layout, umbrella `AGENTS.md`의 "Live package `control` is ..." 줄을 갱신한다.

## 롤백

- 각 커밋은 `git mv`와 소비자를 함께 담으므로 `git revert <sha>` 하나로 되돌린다. main에서 reset하지 않는다.
- 데이터·wire·설치 경로가 바뀌지 않으므로 롤백에 변환 단계가 없다. 예외는 1a의 사이트 PC model-watch unit이며, 되돌리면 사이트 PC에서 설치 스크립트를 다시 실행한다.
- image wave를 되돌린 경우 다음 release 전에 payload inventory 비교를 다시 한다.

## 동시 작업 규약

1. **공지.** wave를 시작하기 전에 peer 세션(현재 이동 대상 root를 바꾸는 브랜치의 소유자)에게 wave 이름, 이동 root, 동결 창, 기준 SHA를 알린다. ADR 리뷰 때처럼 번호 붙은 질문으로 "착지 / rebase 예정 / 보관(D-172 archive tag)"을 받는다.
2. **동결 창.** 동결은 해당 wave의 root에만 걸린다. 작은 wave(0, 1, 2, 3a, 4a)는 반나절, 큰 wave(3c, 4b–4e)는 하루를 넘기지 않는다. 창 안에서는 그 root에 새 커밋을 넣지 않는다. 창을 넘기면 wave를 접고 다시 공지한다.
3. **브랜치.** wave마다 `refactor/d427-<wave>` 하나, `.worktrees/d427-<wave>`에서 `git worktree add --relative-paths`로 만든다. 한 wave 안의 커밋은 root 하나씩이다.
4. **착지 뒤 peer rebase.** 이동 커밋은 rename 유사도를 유지하므로 `git rebase main`이 대부분 rename을 따라간다. rebase 뒤 `python -m pytest test/architecture -q`를 돌리면 옛 경로에 남은 새 파일이 `test_moved_roots_leave_nothing_behind`에서 잡힌다.
5. **오래된 브랜치.** 2026-09-30 이전에 마지막 커밋이 있는 미병합 브랜치 27개(그중 23개가 이동 대상 root를 건드린다. `feat/camera-*`, `uiux/*`, `fix/sd-*` 등)는 wave 0 전에 착지·보관을 정한다. 결정하지 않은 브랜치는 이동 뒤 rebase 비용이 커진다.

## 열린 질문 (사용자 결정)

| # | 질문 | 권고 |
|---|---|---|
| Q1 | ROS 패키지가 `src/` 밖으로 나가면 colcon 탐색 root를 어떻게 정하나 | 매니페스트 `colcon_roots` 목록 하나를 CI·native payload·rosdep·개발 스크립트가 읽는다(wave 0). `--base-paths .` 전체 탐색은 `docs/`·`archive` 등의 우연한 `package.xml`을 집을 수 있어 쓰지 않는다 |
| Q2 | 매니페스트가 하위 폴더를 다른 파트로 떼어 둔 패키지(`control`의 recorder·map·sim 도구, `gz_sim`의 launch·scripts, Fleet web, execution 세 갈래)를 이동 때 함께 나누나 | 나누지 않는다. 패키지 단위로 옮기고, 나누기는 설치 내용이 바뀌는 별도 변경(각자 계획과 ARTIFACT 비교)으로 한다. 예외는 1c의 `lerobot_export.py`(런타임에서 import하는 곳이 없고 위반 1건이 빠진다)와 D-425 Task 9의 Console web |
| Q3 | `data/`(tracked 11파일: README, `.gitkeep` 3개, teleop mp4 7개)를 `learning/datasets`로 옮기나 | 옮기지 않는다. 소스가 아니라 데이터 drop 폴더이고, 모든 checkout에 gitignore된 `data/perception` 산출물이 있다. 매니페스트 목표를 `data`(part learning)로 바꾼다 |
| Q4 | `rosy-execution` wheel 하나가 middleware(`local`)와 operations(`api`, `site`)에 걸친다. 나누나 | wave 2a 뒤에 나눈다. `rosy.execution.*` import 이름은 그대로 두고, 배포 이름은 operations 쪽이 `rosy-execution`을 유지하고 middleware 쪽에 `rosy-execution-local`을 새로 만든다. 새 배포 이름 하나가 생기는 것은 사용자 승인이 필요하다. 승인이 없으면 wheel을 `operations/execution`에 통째로 두고 `local` root를 operations에서 middleware를 import하는 것으로 남긴다 |
| Q5 | D-399 후속 1(엔벌로프 스킬 ADR) 전에 `SkillInvocation`을 contracts로 옮겨도 되나 | 된다. 타입을 바꾸지 않고 옮기며 원래 이름을 re-export한다. 엔벌로프 ADR은 이 자리에서 타입을 확장한다. 위반 3건이 빠진다 |
| Q6 | 1c 뒤 `learning/curation/omx/lerobot_export.py`가 `omx_adapter.demonstration`(장치 녹화 형식 검증)을 import하면 learning → middleware 새 위반이 된다 | `rosy.omx-demonstration.v1` 검증을 2b에서 Episode profile로 contracts에 옮긴다. 그 전까지는 1c 커밋에서 `KNOWN_VIOLATIONS`의 `external:lerobot` 1건을 지우고 `learning/curation/omx → middleware/apps/device/omx/adapter` 1건을 이유와 함께 넣는다(집합 크기 유지). 2b에서 지운다 |
| Q7 | `tools/perception`을 이동 때 `datasets/registry/training`으로 나누나. 그리고 재생 게이트가 장치 인식 코드를 import하는 edge를 어떻게 하나 | 통째로 `learning/training/perception`에 옮긴다(sys.path 47곳이 형제 폴더를 가정한다). 나누기는 2b에서 계약 경계가 생긴 뒤 한다. 장치 알고리즘 재생 import는 "같은 코드로 재생해야 한다"(D-205)는 이유로 정당하므로, §2에 "learning은 middleware 인식 백엔드를 재생 목적으로만 import할 수 있다"는 예외를 넣을지 별도 결정한다. 그 전까지 `KNOWN_VIOLATIONS`에 남긴다 |
| Q8 | native payload가 장치 전용이 아닌 패키지(`isaac_sim`, `fleet`, `rosy_cell`, `rosy_vision`, `games`, `gz_sim`)까지 빌드한다. 이동 때 빼나 | 빼지 않는다. 이 계획은 inventory 동등성을 지킨다. 빼는 일은 D-427 §2(learning은 장치에 설치되지 않음)를 근거로 한 별도 ARTIFACT 변경이다 |

## 완료 정의

- 모든 root가 `path == d427_target`(Q3로 바뀐 목표 포함)이고 `legacy` 아래 tracked 파일이 없다.
- `colcon_roots`에서 찾은 ROS 패키지 이름 집합이 27개 기준과 같다.
- `KNOWN_VIOLATIONS`가 9건에서 최대 5건으로 줄었다(Q4·Q6 결정에 따라 조정).
- 각 image wave에 CORE·IO·native 설치 closure 비교 증거가 그 커밋 SHA와 함께 `docs/validation/d427-source-migration/`에 있다. native를 돌리지 못했으면 `NOT_RUN`으로 적고 `ARTIFACT_EQUIVALENT`를 주장하지 않는다.
- 장치 수용은 이 계획의 출구가 아니다.
