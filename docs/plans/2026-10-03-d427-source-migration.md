# D-427 B 단계 소스 이전 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan wave by wave.

**Status:** PLAN rev 3 (2026-10-03). 아직 아무 파일도 옮기지 않았다. 기준 main `f41716e55`(`integrate/commit-merge-20261003` 착지 뒤). rev 1에 대한 독립 critic의 REVISE 지적과 사용자 결정(아래 "결정 기록")을 반영했다. 파일 수와 겹치는 브랜치 목록은 이 기준으로 다시 셌다. 겹치는 브랜치는 `git cherry main <branch>`에서 main에 없는 커밋(`+`)이 바꾼 파일만 센다. 각 wave를 시작할 때 HEAD, 매니페스트, 진행 중 브랜치를 다시 센다.

**Goal:** [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md) §6 "이후(B)"를 실행한다. `tools/harness/platform_parts.yaml`의 각 root를 `path`에서 `d427_target`으로 옮긴다. 순서는 §6을 따른다: learning → contracts → operations → middleware, Pinky CORE는 마지막.

**Move table:** 매니페스트가 이동 표다. 이 문서는 표를 다시 적지 않고 wave 묶음, 소비자, 선행 조건, 검증만 적는다. wave 0에서 매니페스트에 `wave` 필드를 넣은 뒤에는 다음 명령으로 남은 표를 출력한다.

```bash
python -c "import yaml;[print(r.get('wave','-'),r['path'],'->',r['d427_target']) for r in yaml.safe_load(open('tools/harness/platform_parts.yaml',encoding='utf-8'))['roots'] if r['path']!=r['d427_target'] and not r.get('deferred')]"
```

## 결정 기록 (사용자, 2026-10-03)

- Q1–Q8은 권고대로 정한다. Q4의 시점만 critic 지적에 따라 바꾼다.
- `rosy-execution-local` wheel 분리를 허용한다. 커밋 `2c`로 2a 뒤, 3a 앞에 넣는다.
- 오래된 미병합 브랜치 정리: snapshot tag `archive/<branch>` 17개를 달았고(`refactor/web-transport`는 `archive/refactor/web-transport-midmerge`), 해당 worktree와 detached worktree를 지웠다. 브랜치 자체는 남겨 두었다. wave 0의 선행 조건은 "tag 완료, worktree 제거, 브랜치 유지"다.
- 새 배포 이름 `rosy-contracts-skill`(2a, Q9)을 승인했다. 남은 열린 질문은 없다.

## 범위와 비목표

| 범위 | 비목표 |
|---|---|
| source root 이동(`git mv`)과 같은 커밋의 살아 있는 소비자 수정 | 패키지 이름, ROS 패키지·노드·토픽·서비스 이름, API 경로, 공개 wire 변경(D-231, D-427 §6) |
| 매니페스트 `path` 갱신, `KNOWN_VIOLATIONS` 축소 | 런타임 동작 변경. 이동 커밋은 동작이 같아야 한다 |
| colcon 탐색 root, SD 이미지 소스 트리, wheel 빌드 목록, Docker `COPY` 원본 경로, harness module path, 현재 AGENTS·README | 설치 경로·장치 경로·컨테이너 내부 경로(`/opt/rosy/...`, `<release>/deploy/...`) 변경 |
| 2a의 계약 타입 추출(re-export로 기존 import 유지), 2c의 wheel 분리 | Episode·DatasetManifest·PolicyArtifact 스키마 설계(D-427 후속 2의 별도 설계) |
| | 하위 폴더를 다른 패키지로 떼어 내는 일(Q2, `deferred`) |
| | 장치 수용(DEVICE/FIELD). 이동 출구는 SOURCE·ARTIFACT 동등성까지다 |
| | 역사 문서 수정(D-226). `docs/adr`, `docs/plans`, `docs/validation`, `logs.md`·`progress.md`의 과거 항목은 옛 경로를 그대로 둔다 |

출구 이름은 [D-310 계획](2026-09-27-product-source-layout-migration.md)과 같다. `SOURCE_CANDIDATE`(host·harness·colcon), `ARTIFACT_EQUIVALENT`(이미지·payload 설치 내용 비교), `DEVICE_ACCEPTED`(이 계획 밖).

## 이전 이동에서 가져온 규칙

`docs/solutions/workflow-issues/`의 교훈을 각 커밋의 점검 항목으로 쓴다.

1. **경로를 세 종류로 나눈다** ([blanket-path-rewrite](../solutions/workflow-issues/blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md)). 저장소 경로만 고친다. 설치·release 경로(`/opt/rosy/src/site/fleet/`, `/opt/rosy/apps/gateway/src`, `<release>/deploy/robot/native/`)는 장치 계약이므로 고치지 않는다. 트리 전체 `sed`는 금지한다. 소비자 목록을 만들고 파일별로 고친다.
2. **identity hash 입력은 바이트를 바꾸지 않는다** ([payload-runtime-id](../solutions/workflow-issues/payload-runtime-id-hashes-comments-too-2026-10-01.md)). `deploy/robot/pinky_pro/image/device-python-requirements.txt`의 주석 경로가 낡아도 그대로 둔다. `test/test_python_runtime_id.py`가 지킨다.
3. **경로 범위 시험이 넓어지거나 비지 않았는지 본다** ([folder-move-widens](../solutions/workflow-issues/folder-move-widens-path-scoped-contract-tests-2026-09-25.md)). "X 아래 전부"로 범위를 잡은 시험은 이동 뒤 다른 패키지를 끌어들이거나, X가 비면 아무것도 검사하지 않고 통과한다. 이동 전후 검사 대상 파일 수를 비교한다. wave 0은 `src/`를 직접 훑는 시험에 0보다 큰 개수 단정을 넣는다.
4. **`parents[N]`는 깊이가 바뀐다.** 저장소 root를 찾는 `parents[N]`가 이동 대상 root에 481개, `test/`에 188개 있다(wave별 수는 각 wave의 소비자 항목). 시험 코드는 N을 고친다. 설치되어 실행되는 코드가 checkout 경로를 계산하면 고치지 말고 결함으로 보고한다([installed-layout-import](../solutions/workflow-issues/installed-layout-import-passes-repo-tests-2026-09-22.md)).
5. **공유 index에서는 자기 경로만 stage한다** ([peers-share-one-git-index](../solutions/workflow-issues/peers-share-one-git-index-never-amend-stage-only-your-line-2026-09-26.md), [parallel-session-sweeps](../solutions/workflow-issues/parallel-session-sweeps-shared-tree-2026-09-29.md)). 모든 wave는 `.worktrees/` worktree에서 한다. `git add -A`, amend, bare `git stash`는 쓰지 않는다.
6. **커밋을 검증한다** ([verify-what-you-ship](../solutions/workflow-issues/verify-what-you-ship-the-working-tree-is-not-the-commit.md)). 게이트는 커밋한 SHA의 깨끗한 checkout에서 돈다.
7. **시험이 코드와 같은 문자열을 반복하면 sed 앞에서 동어반복이 된다.** 경로를 확인하는 시험은 문자열 비교 대신 존재 여부를 보거나 생산자(매니페스트, payload builder)에서 경로를 얻는다.
8. **이동한 `logs.md`·`progress.md`는 내용을 바꾸지 않는다(D-226).** 이동 커밋에서 두 파일은 rename 유사도 100%여야 한다. 새 항목은 다음 커밋에 쓴다. 이유는 wave 0의 harness 수정(6번) 참고.

## 현재 구조에서 확인한 사실

- **colcon 탐색.** ROS 패키지 27개가 모두 `src/` 아래에 있다. 다음이 `src`를 직접 쓴다.
  - CI: `.github/workflows/ci.yml`의 `cd src && colcon build`, 그 뒤 `. src/install/setup.sh`(125, 152, 164행). `test/test_ci_dependencies.py:20`이 이 문자열을 단정한다.
  - ARM64 리허설: `.github/workflows/arm64-rehearsal.yml:42`의 `cd src`, `:52`의 `source src/install/setup.sh`.
  - native payload: `deploy/robot/pinky_pro/image/build-native-payload.sh`의 `-d "$WORKSPACE/src"` 검사(30행), `rosdep --from-paths "$WORKSPACE/src"`, `colcon build/list --base-paths src`(123–125행). payload는 장치 전용이 아닌 `isaac_sim`, `fleet`, `rosy_cell`, `rosy_vision`, `games`까지 `src/` 전체를 빌드한다.
  - **SD 이미지:** `deploy/robot/pinky_pro/image/build-image.sh:100`이 `--source-tree "$WORKSPACE/src"`를 넘기고, `customize-rootfs.sh:189`가 그 트리만 `/tmp/rosy-src`로 복사한 뒤 `resolve-required-source-paths.py --source-root`로 rosdep 범위를 정한다(192–198행). `test/test_image_customization_contract.py:42,61`이 이 문자열을 단정한다.
  - `resolve-required-source-paths.py`는 root 하나만 `rglob`한다.
  - 개발 진입: `env.sh:6`의 `colcon build --base-paths src`, `tools/build_wsl.sh`, `tools/sync_*.sh`.

  따라서 **ROS 패키지 하나를 `src/` 밖으로 옮기면 CI, payload inventory, SD 이미지 rosdep 범위에서 그 패키지가 조용히 사라진다.** wave 0이 탐색 root를 먼저 바꾸는 이유다.
- **`src/`를 직접 훑는 시험은 `src/`가 비면 그냥 통과한다.** `test/test_boot_display.py:791`(`(ROOT / "src").rglob("*.launch.py")`), `test/robot_contracts.py:51` `source_manifests()`, `test/architecture/test_module_structure.py:565` `_packages()`, `test/test_control_deploy_closure.py:22` `SRC`.
- **release 영향 분류.** `deploy/robot/pinky_pro/release/artifact_impact.py:75`는 `startswith("src/")`로 native-payload 영향을 판정한다. 옮긴 경로는 "영향 없음"으로 잘못 분류된다.
- **목표가 겹친다.** `middleware/core` ← gateway·services·events·api_web(ROS 패키지 4개), `middleware/apps/device/pinky` ← bringup·profile, `middleware/apps/device/omx` ← adapter·profile·`apps/agent`. 패키지 폴더는 중첩될 수 없다(D-310 `profile/` 교훈).
- **하위 폴더를 다른 파트로 떼어 둔 root:** `src/runtime/sensing`(recorder·map 자산·sim 도구), `src/sim/gz_sim/{launch,scripts}`, `src/site/fleet/fleet/server/web`, `modules/execution/src/rosy/execution/{local,api,site}`, `src/products/omx/adapter`의 `lerobot_export.py`. 모두 한 패키지의 설치물 안에 있다.
- **execution wheel.** `modules/execution/pyproject.toml:17`이 `api`·`local`·`site`를 한 wheel `rosy-execution`에 넣는다. 3a에서 그 wheel을 operations로 옮기면서 `local`을 그대로 두면 `local`은 4a까지 어느 wheel에도 들지 않는다. `test/test_platform_transfer_owner_boundary.py:20`이 `rosy.execution.local.receipts`를 import하므로 깨진다. 분리 커밋 2c가 3a보다 먼저 와야 한다.
- **`KNOWN_VIOLATIONS`와 `PACKAGE_DIR_ROOTS`는 root `path`를 key로 쓴다.** 이대로 두면 이동 커밋마다 key도 고쳐야 한다.
- **harness append-only 검사가 이동한 log를 보지 못한다.** `tools/harness/rosy_harness.py:673`은 `git show <ref>:<새 경로>/logs.md`로 과거 내용을 읽는다. 이동 직후에는 그 ref에 새 경로가 없어 `None`이 되고 검사를 건너뛴다.
- **옛 경로를 쓰는 방식이 여러 가지다.** 슬래시 문자열 말고도 다음이 있다.
  - 경로 조각 결합: `"src" / "..."` 형태가 205곳, 시험 파일 43개. 예: `deploy/robot/pinky_pro/dev/core_dev_overlay.py:410-414,426`, `tools/calibration/analyze_session.py:35-37,45-46`.
  - 셸 변수 뒤: `"$WORKSPACE/src/..."`(`build-native-payload.sh:79`), `"$SRC/tools/perception/..."`(`deploy/site/install-model-watch.sh:117-118`).
  - 상대 경로: `src/site/cam/app/build.gradle.kts:64`의 `rootProject.file("../../hmi/web_common/icons")`. cam이 `operations/ui/cam`으로 가는 3b와 web_common이 `shared/web`으로 가는 4b에서 깨진다. 같은 파일 40–59행의 `../../../test/fixtures/protocol/*`는 깊이가 같아(3단) 그대로 맞다.
- **사이트 PC 설치가 저장소 경로에 묶여 있다.** `deploy/site/rosy-model-watch.service:20`은 `/opt/rosy/model-watch/src/tools/perception/model/watch.py`를 실행한다. `src`는 사이트 PC의 소스 사본이다.
- **wheel `pyproject.toml` 8개**(`modules/*`, `apps/*`, `integrations/robots/omx`)가 파트 root 아래로 들어간다. colcon이 이것을 Python 패키지로 인식하면 ROS 이름 집합이 바뀐다.

## Wave 표

숫자 = 해당 root가 직접 소유한 tracked 파일 수(하위 root 제외). 겹치는 브랜치(각 wave 절)는 `git branch --no-merged main` 중 그 root의 파일을 바꾸는 브랜치이고, 괄호 숫자는 그 root에서 바뀐 파일 수다. **wave는 하나씩 차례로 한다.** 모든 wave가 `ci.yml`, 매니페스트, Dockerfile, AGENTS를 고치므로 두 wave를 동시에 열지 않는다.

| Wave | 브랜치 | root (files) | 합계 | 이미지 영향 | 줄일 위반 |
|---|---|---|---|---|---|
| 0 | `refactor/d427-w0-mechanism` | 이동 없음 | 0 | native payload·SD 이미지 스크립트(inventory·이미지 동일 증명) | 0 |
| 1 | `refactor/d427-w1-learning` | 1-pre model-watch 진입점, `tools/perception`(75) + `prototype`(24), `src/sim/isaac_sim`(37), `lerobot_export.py`+시험(2) | 138 | IO·native에서 `omx_adapter.lerobot_export` 모듈 하나 빠짐 | 1 (`omx adapter → external:lerobot`), 1건 교체(Q6) |
| 2 | `refactor/d427-w2-contracts` | 2a 타입 추출, 2b 학습 계약 자리, 2c `rosy-execution-local` 분리(`execution/local` 2파일 → `middleware/execution/local`) | 새 파일 ~12, 이동 2 | 없음 | 3 (execution api→skills api, palletizing→skills api, execution api→local) |
| 3a | `refactor/d427-w3a-ops-modules` | `modules/world`(3), `modules/processes/palletizing`(16), `apps/gateway`(4), execution `api`(2)+`site`(3)+metadata(1) | 29 | Fleet 사이트 이미지 `COPY` | 0 |
| 3b | `refactor/d427-w3b-site-apps` | `src/site/vision`(47), `src/site/games`(57), `src/site/cell`(33), `src/site/cam`(111) | 248 | Vision 사이트 이미지, native inventory(이름 동일) | 0 |
| 3c | `refactor/d427-w3c-fleet` | `src/site/fleet`(232) + `fleet/server/web`(25, 패키지 안에 그대로, `deferred`) | 257 | Fleet 사이트 이미지, native inventory | 0 |
| 4a | `refactor/d427-w4a-mw-modules` | `modules/skills/api`(3), `modules/skills/manipulation`(3), `apps/agent`(6), `firmware/dock`(8), `firmware/signal`(15) | 35 | 없음 | 0 |
| 4b | `refactor/d427-w4b-ui` | `src/hmi/web_common`(53), `src/hmi/dashboard`(75), `src/hmi/pilot`(53), `src/hmi/face`(34) | 215 | CORE·IO·native·SD, Fleet 이미지(`web-common`) | 0 |
| 4c | `refactor/d427-w4c-device` | `src/drivers/imu_bno055`(20), `src/products/pinky_pro/{adc,lamp,led,bringup,profile}`(96), `src/products/omx/{adapter,profile}`(82), `src/sim/description`(38), `src/sim/gz_sim` 전체(86), `src/runtime/navigation`(49) | 371 | IO·native·SD | 0 |
| 4d | `refactor/d427-w4d-core` | `src/contracts/foundation`(70), `src/contracts/interfaces`(12), `src/runtime/{gateway,services,events,api_web}`(345) | 427 | CORE·IO·native·SD, Fleet·Vision 이미지(`core_common`) | 0 |
| 4e | `refactor/d427-w4e-sensing` | `src/runtime/sensing`(621) | 621 | IO·native·SD, Fleet 이미지(map 자산 `COPY`) | 0 |
| 5 | `refactor/d427-w5-cleanup` | 빈 `src/`, `modules/`, `apps/` 삭제, `colcon_roots`에서 `src` 제거 | — | native payload·SD 스크립트(`src` 검사 제거) | 0 |

모든 wave 뒤에도 위반 5건이 남는다. `apps/agent → palletizing`, `integrations/robots/omx → {skills/api, skills/manipulation, omx adapter}`(3건), `learning perception → middleware perception`(Q7). 이동 커밋은 key 이름만 바꾸며 집합 크기를 늘리지 않는다.

`profiles/`(2), `integrations/robots/omx`(4), `data`(11, Q3)는 옮기지 않는다. 최상위 `modules/`·`apps/` 43파일은 2c·3a·4a에서 파트 안으로 옮긴다.

## Wave 0: 이동 장치 (파일 이동 없음)

**선행:** 오래된 브랜치 정리가 끝났다(tag 완료, worktree 제거, 브랜치 유지. 결정 기록 참고). 이 wave가 main에 들어가기 전에는 어떤 이동도 시작하지 않는다.

1. **leaf 목표.** 여러 패키지가 같은 목표를 가리키는 root의 `d427_target`을 패키지 하나당 폴더 하나로 나눈다.
   - `middleware/core/{gateway,services,events,api_web}`. `middleware/core/navigation`은 그대로.
   - `middleware/apps/device/pinky/{bringup,profile,description}`.
   - `middleware/apps/device/omx/{adapter,profile,agent}`.
   - `modules/execution` 메타데이터는 `operations/execution`, `local`은 `middleware/execution/local`(2c).
   - `data`의 목표를 `data`로(Q3).
   - 시험 `test_package_targets_are_leaf_unique`: `package.xml`이나 `pyproject.toml`이 있는 root의 목표끼리 같거나 한쪽이 다른 쪽 패키지 폴더 안에 있으면 실패한다. 패키지가 아닌 컨테이너 목표(`middleware/core`)는 허용한다.
2. **wave와 상태 필드.**
   - 각 root에 `wave: 1|2c|3a|…|4e` 또는 `wave: none`(이미 목표 위치)을 넣는다.
   - root 상태는 셋이다. **moved**: `path == d427_target`. **partly moved**: 부모 패키지와 함께 옮겨졌지만 떼어 내기는 미뤘다. `deferred: <후속 작업 이름>`을 갖고, `path`는 부모 목표 아래의 실제 위치이며 `d427_target`은 그대로다. **pending**: 그 밖.
   - Q2에 따라 처음부터 `deferred`인 root: `src/site/fleet/fleet/server/web`(D-425 Task 9), `src/sim/gz_sim/launch`·`scripts`(gz_sim 분리 후속), sensing 안의 recorder·map·sim 도구(현재 별도 root가 아니므로 매니페스트 note로 남긴다).
   - 시험: pending root는 모두 wave를 갖는다. `deferred` root는 부모 패키지 목표 아래에 있다.
3. **안정 key.** `KNOWN_VIOLATIONS`와 `PACKAGE_DIR_ROOTS`의 key를 `path`에서 `d427_target`으로 바꾼다. 이후 이동 커밋은 매니페스트 `path`만 바꾼다. `_edges`는 `importer["d427_target"]`을 key로 낸다. 1번 뒤에 한다.
4. **옛 경로 검사 `test_moved_roots_leave_nothing_behind`.** 이동 커밋은 옛 경로를 `legacy: <old path>`로 남긴다. moved·partly moved root 모두에 적용한다.
   - `legacy` 아래에 tracked 파일이 없다. 이동 뒤 rebase된 브랜치가 옛 경로에 새 파일을 만들면 여기서 잡힌다.
   - **검사 범위:** `.github/`, `deploy/`, `tools/`, `test/`, 모든 파트 root와 아직 남은 `src/`·`modules/`·`apps/`의 비-Markdown 파일, `env.sh`, `.dockerignore`, `*.dockerignore`, `.gitattributes`, 현재 `AGENTS.md`·`README.md`. 제외: `docs/adr/`, `docs/plans/`, `docs/validation/`, 모든 `logs.md`·`progress.md`(D-226), 바이트 고정 목록 `FROZEN_BYTES = {"deploy/robot/pinky_pro/image/device-python-requirements.txt"}`.
   - **슬래시 문자열:** `<legacy>`가 경로 조각 경계에서 시작하면 찾는다. `/` 뒤도 포함한다(`$WORKSPACE/src/...`, `$SRC/tools/perception/...`, `/repo/src/...`). 예외는 실제 설치 경로뿐이다. 일치한 문자열을 담은 경로 토큰(공백·따옴표·`=`·`:` 사이)이 `/opt/`, `/usr/`, `/etc/`로 시작하면 제외한다. 예: `/opt/rosy/src/site/fleet/`는 제외, `"$WORKSPACE/src"`와 `/repo/src/...`는 검사 대상.
   - **조각 결합:** `<legacy>`를 조각으로 나눠 `"src"\s*[/,]\s*"site"\s*[/,]\s*"fleet"`처럼 `/` 연산자, `os.path.join`, `Path(a, b)` 결합을 찾는다. 조각 사이에 변수가 끼는 경우(`HERE.parents[2] / "src" / "runtime"`)도 이 정규식에 걸린다.
   - **상대 경로:** 검사 범위 파일의 `(\.\./)+[\w./-]+` 문자열을 파일 폴더와 그 조상 폴더(저장소 root까지) 기준으로 각각 해석한다. 어느 하나라도 `legacy` 아래로 해석되면 실패한다. gradle의 `rootProject.file`처럼 기준 폴더가 파일 폴더와 다른 경우를 조상 해석이 덮는다. 경로가 아닌 시험 문자열(`"../../etc/passwd"` 같은 경로 탐색 거절 사례)은 파일·문자열 쌍 allowlist로 둔다.
   - 변이 증명: 각 방식(슬래시, `$VAR/`, 조각 결합, `../`)으로 옛 경로를 하나씩 `deploy/`나 `test/`에 넣어 실패하는지 확인하고 되돌린다.
5. **colcon root를 한 곳에서.** 매니페스트에 `colcon_roots: [src]`를 넣는다. 다음이 이 목록을 읽거나 같은 값을 쓰고, 시험이 일치를 확인한다.
   - **build·install 위치 고정:** 모든 colcon 호출을 저장소 root에서 `--base-paths <roots> --build-base build --install-base install --log-base log`로 바꾼다(`.gitignore`가 이미 어느 깊이든 `build/`·`install/`·`log/`를 무시한다). 따라서 바뀌는 소비자: `ci.yml`의 `cd src`와 `. src/install/setup.sh` 3곳(125, 152, 164행), flake8·pytest 단계의 `cd src` 상대 경로, `arm64-rehearsal.yml:42`의 `cd src`와 `:52`의 `source src/install/setup.sh`, `test/test_ci_dependencies.py:20`의 단정, `test/robot_contracts.py:42`·`test/test_control_deploy_closure.py:24`의 "CI는 `src/build`·`src/install`에 빌드한다" 가정, `env.sh:6`, `tools/build_wsl.sh`, `tools/sync_*.sh`.
   - **native payload:** `build-native-payload.sh`의 `-d "$WORKSPACE/src"` 검사(30행)를 root 목록 각각의 존재 검사로, `rosdep --from-paths`와 `colcon build/list --base-paths`를 root 목록으로.
   - **SD 이미지:** `build-image.sh:100`의 `--source-tree "$WORKSPACE/src"`를 root 목록으로 바꾼다. `customize-rootfs.sh:189`는 각 root를 `/tmp/rosy-src/<root>`로 복사하고, `resolve-required-source-paths.py`는 여러 root를 받는다(중복 이름 거부는 전체 root에 걸쳐 유지, `--chroot-prefix` 의미 유지). `test_image_customization_contract.py:42,61`(그리고 payload 쪽 842–844행)의 문자열 단정은 매니페스트에서 기대값을 만든다.
   - **release 영향:** `artifact_impact.py:75`의 `startswith("src/")`를 `colcon_roots`의 각 root(그리고 `learning` 예외, 아래 7번)로 바꾼다.
   - **비지 않는 scan:** `test_boot_display.py:791`, `robot_contracts.source_manifests()`, `test_module_structure.py:565` `_packages()`, `test_control_deploy_closure.py:22`가 `colcon_roots`를 돈다. 각 시험에 0보다 큰 최소 개수를 단정한다(package.xml 27개, launch 파일은 현재 수).
   - **ROS 이름 고정:** `test_ros_package_names_are_frozen`. 모든 `colcon_roots`에서 찾은 `package.xml` 이름 집합이 현재 27개와 같고 각 이름이 한 경로에만 있다. `COLCON_IGNORE`가 있는 `src/site/cam`은 집합에 넣되 탐색 제외 사실을 기록한다. `test_target_layout.py`의 `SRC` 기준 `TARGET` 표는 이 시험과 매니페스트로 대체하고, 패키지 이름 보존 단정은 옮겨 온다.
   - **wheel과 colcon:** 게이트는 WSL `colcon list --base-paths <roots> --names-only` 이름 집합이다. wheel `pyproject.toml` 8개가 파트 root 아래로 들어가는 wave(2c, 3a, 4a)에서 이 집합에 wheel 이름이 나타나면 해당 wheel 폴더에 `COLCON_IGNORE`를 넣는다. 매니페스트 시험은 `COLCON_IGNORE`가 `pyproject.toml`만 있는 폴더(그리고 cam)에만 있음을 확인한다.
6. **harness append-only.** `rosy_harness.py:673`에서 `git show <ref>:<새 경로>`가 없으면 매니페스트 `legacy` 경로로 다시 읽는다. `harness.yaml` module path와 매니페스트 root가 다르면 `git log --follow`로 대체한다. 시험: 이동한 module의 `logs.md` 과거 줄을 고치면 lint가 실패한다(변이 증명). 그와 별개로 규칙 8(rename 유사도 100%)을 지킨다.
7. **learning 장치 설치 예외.** 1b 뒤 `learning/envs/isaac`의 ROS 패키지 `isaac_sim`은 native payload inventory에 계속 들어간다(Q8). D-427 §2 "learning은 장치에 설치되지 않는다"의 예외를 매니페스트 root에 `device_install_exception: "native payload builds every colcon root (Q8); remove with the payload scope change"`로 적는다. 시험: `learning` 파트 root 중 `package.xml`이 있는 것은 이 필드를 가져야 한다.
8. **증거.** 값이 `[src]`이므로 결과는 같아야 한다. WSL Ubuntu에서 `colcon list --base-paths src --names-only` 전후 비교, ARM64 `build-native-payload.yml` 1회로 `rosy-packages.txt`가 이전 release와 같음, `build-pinky-image.yml` 1회로 `/tmp/rosy-src` rosdep 범위와 이미지 패키지 목록이 같음을 확인한다. 이 증명 뒤로는 각 wave가 WSL `colcon list` 비교로 inventory 동등성을 보이고, payload·SD 실빌드는 image wave(4b–4e)와 release 전에만 한다.

**검증:** `python -m pytest test/architecture -q`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_image_customization_contract.py test/test_native_ros_payload.py test/test_python_runtime_id.py test/test_ci_dependencies.py test/test_boot_display.py test/test_control_deploy_closure.py -q`, artifact_impact 시험, WSL colcon list 비교, ARM64 payload 1회, SD 이미지 1회.

## 각 이동 커밋의 공통 절차

한 커밋은 한 영역(wave 안의 한 줄)이다. 커밋 하나가 녹색이어야 한다.

1. 소비자 목록을 만든다. 옛 경로를 `ROOT`, 그 조각을 `"a" / "b" / "c"`라 할 때:
   ```bash
   git grep -n -F "ROOT" -- . ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!**/logs.md' ':!**/progress.md'
   git grep -n -E '"a"\s*[/,]\s*"b"' -- . ':!docs'
   git grep -n -E "parents\[[0-9]\]|sys\.path\.(insert|append)|PYTHONPATH|\.\./" -- ROOT test tools deploy
   ```
   결과를 저장소 경로, 설치 경로, 바이트 고정 파일로 나눈 목록을 `X:/DevTemp/rosy-d427/<wave>/consumers.txt`에 남긴다. 옛 경로 검사(wave 0 4번)를 이동 전에 한 번 돌려 상대 경로 해석 결과를 같은 폴더에 저장하고, 이동 뒤 결과와 비교한다.
2. `git mv ROOT TARGET`. 옮긴 파일 안의 수정은 `parents[N]` 깊이, 저장소 상대 경로, 상대 `../` 경로로 제한한다. `logs.md`·`progress.md`는 고치지 않는다(규칙 8). 그래야 rename 유사도가 높게 유지되어 peer 브랜치 rebase가 rename을 따라간다.
3. 같은 커밋에서 고친다: 매니페스트 `path`·`legacy`(필요하면 `deferred`), `tools/harness/harness.yaml`의 module `path`·`tests`·`functional`, `.github/workflows/ci.yml`(wheel 목록·flake8·pytest 경로)과 `android.yml` path filter, Dockerfile `COPY` 원본(목적지는 그대로), `.dockerignore`·`deploy/site/*.dockerignore` 허용 목록, `.gitattributes`, `deploy/` 스크립트의 저장소 경로, 시험의 경로 상수, `test/architecture/test_platform_dependency_boundaries.py`의 경로 표, `AGENTS.md`(폴더 지도, 루트 `AGENTS.md`의 pytest 줄), 현재 README.
4. `python tools/harness/rosy_harness.py generate` 후 lint.
5. 게이트(아래 wave별)를 돌리고 커밋한다. 메시지: `refactor(d427): move <root> to <target>`.

## Wave 1: learning

**선행:**
- wave 0이 main에 있다.
- `integrate/commit-merge-20261003`, `feat/d423-object-range-detection`, `feat/rosy-cell-c3-gazebo`는 main에 들어왔다(`f41716e55`). 지금 learning root(`tools/perception`, `src/sim/isaac_sim`, omx adapter)를 바꾸는 미병합 커밋은 없다.
- 이미지 창: 1c는 IO·native 설치 내용에서 모듈 하나가 빠지므로 release 사이에 한다(D-191). 1a·1b는 이미지 밖이다. 1b의 `isaac_sim`은 payload inventory에 있지만 `colcon_roots`에 `learning`을 추가하므로 이름 집합이 같다.

| 커밋 | 이동 | 소비자 |
|---|---|---|
| 1-pre | 이동 없음. model-watch 진입점을 고정 | `deploy/site/install-model-watch.sh`가 `/opt/rosy/model-watch/bin/rosy-model-watch` wrapper를 설치한다. wrapper는 소스 사본에서 새 경로(`learning/training/perception/model/watch.py`)를 먼저 찾고 없으면 옛 경로를 쓴다. `rosy-model-watch.service:20` `ExecStart`와 설치 스크립트 117–118행의 `doctor` 호출이 wrapper를 쓴다. 시험 `test_site_install_model_watch.py`, `test_site_model_watch_units.py` 갱신. 사이트 PC는 이 커밋 뒤 한 번 재설치하면 이후 이동에 영향받지 않는다(`deploy/site/README.md`에 안내) |
| 1a | `tools/perception` → `learning/training/perception`(내부 구조 유지, Q7), `tools/perception/prototype` → `tools/perception_prototype` | `parents[N]` 44, sys.path 53(`HERE.parents[2] / "src" / "runtime" / "sensing"` 같은 조각 결합 포함. 4d·4e 전까지 sensing·foundation은 옛 위치다), `tools/calibration/analyze_session.py:35`(`REPO / "tools" / "perception" / "dataset"`), `src/runtime/sensing/control/recording.py` 주석, `test/test_learned_perception_pinky_runbook.py`, `test_module_structure.py`, `test_every_tools_subfolder_has_its_own_root` |
| 1b | `src/sim/isaac_sim` → `learning/envs/isaac`, `colcon_roots`에 `learning` 추가, `device_install_exception` 기입 | `prepare_urdf.py`의 `parents[1] / "description"`(형제 `src/sim/description`에 의존. 4c까지 옛 경로를 저장소 root 기준으로 계산), 시험 `parents[2]`, `harness.yaml` isaac_sim module, `test/test_pinky_release_impact.py`, `src/products/omx/adapter/config/omx_f_kinematics.yaml` 주석, `src/AGENTS.md`의 pytest 줄 |
| 1c | `omx_adapter/lerobot_export.py`와 `test/test_lerobot_export.py` → `learning/curation/omx/`(새 root, part learning) | `from .demonstration import validate_episode`를 `omx_adapter.demonstration` 절대 import로, `deploy/robot/omx/README.md`의 `python -m omx_adapter.lerobot_export` 실행법. `KNOWN_VIOLATIONS`에서 `external:lerobot`를 지우고 `learning/curation/omx → middleware/apps/device/omx/adapter`를 이유와 함께 넣는다(Q6, 2b에서 삭제) |

**게이트:** `python -m pytest learning/training/perception/test -q`(34파일), `python -m pytest learning/envs/isaac/test -q`, `python -m pytest src/products/omx/adapter/test -q`, `python -m pytest learning/curation/omx -q`, `python -m pytest test/architecture -q`, harness lint, WSL `colcon list` 이름 집합 동일. 1c는 IO 이미지 빌드 1회로 `omx_adapter` 설치 모듈 차이가 `lerobot_export` 하나뿐임을 확인한다.

## Wave 2: contracts

**선행:** wave 1. 2a의 새 배포 이름 `rosy-contracts-skill`은 승인됐다(Q9). 2b는 D-427 후속 2의 설계가 필요하다. 2c는 2a 뒤에만 한다.

- **2a 타입 추출.** `rosy.skills.api.SkillInvocation`과 `rosy.execution.local.receipts`의 `AttemptIdentity`·`ReceiptBinding`을 새 wheel `contracts/skill`(배포 이름 `rosy-contracts-skill`, import `rosy.contracts.skill`, part contracts)로 옮긴다. 원래 모듈은 같은 객체를 re-export해서 기존 import와 JSON 형식이 그대로다. `execution/api/plan.py`와 `palletizing/plan_bundle.py`는 새 이름을 import한다. CI wheel 빌드·설치 목록(`ci.yml:71,74`), 의존 선언(`rosy-skill-api`, `rosy-execution`, `rosy-palletizing`)에 추가한다. 위반 3건이 빠진다(Q5).
- **2b 학습 계약 자리.** 후속 2가 정한 타입을 `contracts/learning`(import `rosy.contracts.learning`)에 둔다. 녹화 변환기(`rosy.recording.session/1`, D-411 Pilot 녹화, `rosy.omx-demonstration.v1` → Episode profile)는 `learning/curation/`에 둔다. `rosy.omx-demonstration.v1` 검증을 Episode profile로 옮겨 1c의 교체 위반을 지운다. `control.sensing.perception.learned.manifest`의 `rosy.perception.model/1`은 PolicyArtifact 인식 profile로 옮기고 `control`이 re-export한다. learning perception → sensing edge의 import 수가 줄지만 edge는 남는다(Q7).
- **2c `rosy-execution-local` 분리.** 커밋 이름 `refactor(d427): split rosy-execution-local wheel`. `modules/execution/src/rosy/execution/local`(2파일)을 `middleware/execution/local/src/rosy/execution/local`로 옮기고, 그 폴더에 `pyproject.toml`(배포 `rosy-execution-local`, import 이름 그대로)을 만든다. `modules/execution/pyproject.toml:17`의 `include`에서 `rosy.execution.local*`을 뺀다. 같은 커밋에서 고친다: `ci.yml:71,74` wheel 목록, `profiles/installations/omx_cell_sim.yaml:8` 근처 wheel 목록, `apps/agent/src/rosy_agent/omx_sim.py:15` `_WHEELS`, `test/test_platform_transfer_owner_boundary.py:20`이 쓰는 설치 환경, 매니페스트 root(`path`=`d427_target`=`middleware/execution/local`), `PACKAGE_DIR_ROOTS`. 2a 뒤에는 `execution/api`가 `local`을 import하지 않으므로 두 wheel 사이 의존이 없다. 시험: 두 wheel을 각각 X: venv에 설치했을 때 `rosy.execution.local`과 `rosy.execution.api`가 각자 import되고, `rosy-execution`만 설치하면 `local`이 없다.

**게이트:** wheel 빌드와 X: venv 설치 검사(D-413 Task 2 절차), `omx_cell_sim` 프로파일 fake lifecycle(2c), `python -m pytest test/architecture -q`, 소비자 suite(`modules/*` 시험, `test/test_platform_*`), harness lint. WSL `colcon list`에 wheel 이름이 없는지 확인(2c). 이미지 영향 없음.

## Wave 3: operations

**공통 선행:** wave 2(3a의 execution 이동은 2c에 의존한다). 사이트 이미지 wave는 사이트 배포 사이에 한다.

### 3a 작은 wheel

`modules/world` → `operations/world`, `modules/processes/palletizing` → `operations/processes/palletizing`, `apps/gateway` → `operations/apps/fleet`, execution `api`·`site`와 메타데이터 → `operations/execution`.

- 소비자: `ci.yml` wheel 경로 목록, `deploy/site/Dockerfile.fleet:22`의 `COPY apps/gateway/src/`(목적지 `/opt/rosy/apps/gateway/src/`와 7행·15행의 경로는 설치 경로이므로 그대로), `test_platform_dependency_boundaries.py:17-29`, `test/test_platform_*`, `colcon_roots`에 `operations` 추가(필요하면 wheel 폴더 `COLCON_IGNORE`).
- 게이트: wheel 빌드·설치 검사, Fleet 사이트 이미지 빌드와 `rosy-site-gateway` fake lifespan, architecture, lint, WSL `colcon list`.
- 겹치는 브랜치: 없음.

### 3b 사이트 앱

`src/site/vision` → `operations/vision`, `src/site/games` → `operations/apps/games`, `src/site/cell` → `operations/processes/cell`, `src/site/cam` → `operations/ui/cam`. 영역마다 한 커밋.

- 소비자: `deploy/site/Dockerfile.vision:19-22` `COPY` 원본, `Dockerfile.vision.dockerignore`, `.github/workflows/android.yml:10,16`(cam path filter), cam `COLCON_IGNORE`, `src/site/cam/app/build.gradle.kts:64`의 `../../hmi/web_common/icons`(3b에서는 저장소 root 기준 `src/hmi/web_common/icons`로 다시 계산, 4b에서 다시 고친다), `test/architecture/test_app_identity.py`. 이 커밋이 D-425 Task 10의 cam 항목을 대신하며 목적지만 다르다.
- 게이트: 영역별 pytest(`operations/vision/test`, `operations/apps/games/test`, `operations/processes/cell/test`), Vision 이미지 빌드, cam 단위시험·APK assemble(아이콘 디렉터리 해석 확인), WSL `colcon list`·`colcon build --packages-select rosy_vision games rosy_cell`.
- 겹치는 브랜치: `feat/overhead-markerless-tracking`(vision 18).

### 3c Fleet

**진입 조건:** 아래 Fleet 브랜치가 모두 착지했거나 `archive/<branch>` tag로 보관됐다. 하나라도 남아 있으면 3c를 시작하지 않는다.

`src/site/fleet` → `operations/fleet`, 패키지 전체. `fleet/server/web` root는 패키지 안에 남아 `operations/fleet/fleet/server/web`이 되고 `deferred: D-425 Task 9`(partly moved)다. `operations/ui/console`로 떼는 일은 D-425 Task 9(설치 wrapper 유지)이며 D-425 Task 6(설치·정적 서빙 계약)이 먼저다.

- 소비자: `Dockerfile.fleet:20`의 `COPY src/site/fleet/`(목적지 `/opt/rosy/src/site/fleet/` 유지), `deploy/robot/omx/probe_fleet_ros_vendor_sim.sh:33`의 `/repo/src/site/fleet` PYTHONPATH(저장소 mount이므로 고친다), 조각 결합(`ROOT / "src" / "site" / "fleet"` 형태의 시험), `parents[N]` 32, sys.path 5, 루트 `AGENTS.md` pytest 줄, 하위 AGENTS.
- 게이트: `python -m pytest operations/fleet/test -q`(기준 1336 passed/7 skipped), Fleet 브라우저 suite(기존 실패 목록과 비교), Fleet 이미지 빌드, architecture, lint, WSL colcon.
- 진입 조건 대상 브랜치(`f41716e55` 기준): tag 없음 `feat/overhead-markerless-tracking`(19커밋: fleet 17, web 10, vision 18), `feat/d414-fleet-cancel-all`(12커밋: fleet 14, web 4), `refactor/d362-p0-1-fleet-app-routes`(2커밋: fleet 10), `feat/d415-saf003-fleet-loss`(fleet 2), `fix/d407-console-link-and-event-fields`(남은 1커밋: fleet 2), `docs/d416-pinky-device-actions`(남은 4커밋: fleet 2). tag만 있고 브랜치가 남은 것: `feat/d355-goal-evidence-verifier`(fleet 15), `feat/camera-preview-rectification`(fleet 6, web 3), `docs/ui-boundaries-d322`(fleet 2, web 2), `refactor/web-transport`(web 1). tag가 있는 브랜치는 소유자가 "보관, 이어 쓰지 않음"을 확인하면 조건을 채운다.

## Wave 4: middleware

**공통 선행:** wave 3. 4b–4e는 Pinky 이미지 입력이다(D-191).
- 각 sub-wave는 release 하나가 나간 직후 시작해서 다음 release cut 전에 끝낸다. 4b–4e 전체는 여러 release에 걸쳐도 된다.
- release마다 직전 release와의 payload `rosy-packages.txt`·설치 closure diff와 SD 이미지 패키지 목록 diff를 `docs/validation/d427-source-migration/`에 남긴다. diff가 이름 0건, 설치 파일은 의도한 것(1c의 모듈 하나 같은)뿐이어야 한다.
- 시작 전에 release를 맡은 peer 세션에 알린다. auto-update(D-412)는 release된 payload만 적용하므로 main 이동 자체는 로봇에 닿지 않는다.

### 4a 작은 middleware root

`modules/skills/{api,manipulation}` → `middleware/skills/*`, `apps/agent` → `middleware/apps/device/omx/agent`, `firmware/{dock,signal}` → `middleware/firmware/*`. 끝나면 최상위 `modules/`·`apps/`가 빈다.

- 소비자: `ci.yml` wheel 목록, `test_platform_dependency_boundaries.py:113`의 root tuple `("modules", "integrations", "apps", "profiles")`, firmware 시험 3개, `colcon_roots`에 `middleware` 추가(필요하면 wheel 폴더 `COLCON_IGNORE`).
- 게이트: wheel 설치 검사, `omx_cell_sim` 프로파일 fake lifecycle, architecture, lint, WSL `colcon list`.

### 4b UI (D-425 Tasks 7·8·10의 목적지 변경)

`src/hmi/web_common` → `shared/web`, `dashboard` → `middleware/ui/robot`, `pilot` → `middleware/ui/pilot`, `face` → `middleware/ui/face`. 패키지별 한 커밋. D-425 Task 6이 먼저다. ament wrapper(`package.xml`·`CMakeLists.txt`)는 패키지와 함께 옮기며 설치 share 경로(`share/web_common`, `share/dashboard`, `share/pilot`)는 같다. `colcon_roots`에 `shared` 추가.

- 소비자: Pinky `Dockerfile` CORE·IO stage `COPY`(`src/hmi/*` 5줄), `.dockerignore`, `Dockerfile.fleet:23`의 `COPY src/hmi/web_common/`(목적지 `/opt/rosy/web-common/` 유지), `deploy/robot/pinky_pro/dev/core_dev_overlay.py:426`(`repo / "src" / "hmi" / "web_common"`), `.github/workflows/android.yml:13,19`(web_common icons path filter), `src/site/cam/app/build.gradle.kts:64`(이제 `operations/ui/cam/app` 기준 `shared/web/icons`), `tools/sync_rosy*.sh`, `parents[N]` 65, CORE fallback 경로 상수.
- 게이트: 각 패키지 시험, Robot/Pilot/Fleet 브라우저 suite, WSL `colcon build --packages-up-to core pinky_pro web_common dashboard pilot` + `ros2 pkg prefix`, CORE·IO 이미지 빌드와 ament index 비교, cam APK assemble, ARM64 payload 1회(inventory·share 비교).
- 겹치는 브랜치: `refactor/d362-p1-dashboard-split`(dashboard 11), `docs/d395-plan`(dashboard 6), `feat/d400-plan2-rosim`(dashboard 5, web_common 2). tag만 있고 브랜치가 남은 것: `release/floor-g4-minimal`(dashboard 7), `docs/ui-boundaries-d322`(dashboard 6), `refactor/web-transport`(web_common 4, dashboard 1), `uiux/mobile-acceptance`(dashboard 2).

### 4c 장치 패키지 (IO·native·SD)

`src/drivers/imu_bno055`, `src/products/pinky_pro/{adc,lamp,led,bringup,profile}`, `src/products/omx/{adapter,profile}`, `src/sim/description`, `src/runtime/navigation`, `src/sim/gz_sim`(패키지 전체 → `integrations/simulation/gazebo`. `launch/`·`scripts/` root는 `deferred`). `colcon_roots`에 `integrations` 추가(`integrations/robots/omx` wheel은 필요하면 `COLCON_IGNORE`).

- 소비자: Pinky `Dockerfile` IO stage `COPY` 7줄과 CORE stage의 `cyclonedds_localhost.xml`(원본만), `build-native-payload.sh:79`의 `CYCLONEDDS_SOURCE="$WORKSPACE/src/products/pinky_pro/bringup/..."`, `deploy/robot/omx/Dockerfile*`과 `/repo/src/products/omx/adapter` PYTHONPATH 3곳, CI의 `touch src/sim/gz_sim/COLCON_IGNORE`, `arm64-rehearsal.yml`의 `--packages-skip`(이름 기반이라 그대로인지 확인), `.gitattributes`, `harness.yaml`, `tools/calibration/analyze_session.py:45-46`, `test/test_robot_runtime.py`·`test_image_customization_contract.py`·`test_native_systemd_contract.py`, 1b가 남긴 isaac `prepare_urdf.py`의 description 경로.
- 게이트: 패키지 시험(adapter 333 passed/5 skipped 기준), WSL `colcon build` + share/launch lookup, IO 이미지와 native payload 설치 closure 비교(D-310 Task 5 방식), **SD 이미지 1회(`build-pinky-image.yml`)**, Gazebo 2-pinky 기동 스모크(WSL).
- 겹치는 브랜치: `codex/pinky-integrated-current`(gz_sim 11, scripts 5, launch 4. 2026-09-27, tag 없음), `feat/d400-plan2-rosim`(gz_sim 9, launch 7), `feat/gz-learned-lane-drive`(description 2, gz_sim 1, launch 1), `fix/hardware-runtime-truth`(scripts 1, tag 없음).

### 4d Pinky CORE와 contracts

`src/contracts/foundation` → `contracts/foundation`, `src/contracts/interfaces` → `contracts/ros_idl`, `src/runtime/{gateway,services,events,api_web}` → `middleware/core/*`. `colcon_roots`에 `contracts` 추가. contracts 두 root는 D-427 순서상 contracts 파트지만 CORE 이미지 입력이라 여기서 옮긴다.

- 소비자: Pinky `Dockerfile` `COPY` 8줄, `Dockerfile.fleet:21`·`Dockerfile.vision:23`의 `COPY src/contracts/foundation/core_common/`(목적지 유지), `deploy/robot/pinky_pro/dev/core_dev_overlay.py:410-414`, `tools/calibration/analyze_session.py:37`, `ci.yml` flake8·pytest 경로, `deploy/robot/omx/run_pilot_sim.sh:7` PYTHONPATH, `parents[N]` 108(gateway 75), sys.path 10, 루트 `AGENTS.md` pytest 줄.
- 게이트: 루트 `AGENTS.md`의 분리 pytest 두 줄(새 경로), architecture, lint, WSL `colcon build`와 `ros2 pkg executables core`, CORE·IO·native 설치 closure 비교, **SD 이미지 1회(`build-pinky-image.yml`)**, Fleet·Vision 이미지 빌드, `core_dev_overlay.py` 묶음 생성 스모크.
- 겹치는 브랜치: `feat/d400-plan2-rosim`(gateway 16, services 11, api_web 4), `feat/d415-saf003-fleet-loss`(services 9, gateway 8, api_web 5, foundation 3), `feat/d418-ssh-access`·`feat/d418-robot`(api_web 7, gateway 1, foundation 1), `feat/gz-learned-lane-drive`(gateway 7, services 7, foundation 1), `feat/overhead-markerless-tracking`(foundation 2), `fix/d407-console-link-and-event-fields`·`docs/d416-pinky-device-actions`(services 2), `refactor/d362-p1-dashboard-split`(gateway 1, api_web 1), tag만 있는 `feat/camera-preview-rectification`(foundation 1).

### 4e sensing (마지막)

`src/runtime/sensing` → `middleware/perception`, 패키지 `control` 전체. recorder·map 자산·sim 도구 분리는 `deferred`(Q2).

- 소비자: Pinky `Dockerfile` IO `COPY`, `.dockerignore:20-21`, `.gitattributes:10-15`, `Dockerfile.fleet:25`의 map 자산 `COPY` 원본(목적지 `/opt/rosy/maps/map_v2_fleet/` 유지), `tools/calibration/analyze_session.py:36`, 1a가 남긴 `learning/training/perception`의 sensing sys.path, `parents[N]` 133, sys.path 18, 루트 `AGENTS.md` sensing pytest 줄.
- 게이트: `python -m pytest middleware/perception/test -q`(따로 실행: gateway와 `test_battery.py` basename이 겹친다), learning perception 시험, WSL colcon, IO·native closure, SD 이미지 1회, Fleet 이미지 빌드, Gazebo lane 스모크.
- 겹치는 브랜치: `feat/d400-plan2-rosim`(14), `feat/gz-learned-lane-drive`(14), `refactor/d362-p0-2-sensing-calibration-sequence`(9, 2026-09-30, tag 없음).

## Wave 5: 정리

빈 `src/`, `modules/`, `apps/`를 지운다(`src/AGENTS.md`, `src/sim/AGENTS.md` 등 폴더 노트 포함). `colcon_roots`에서 `src`를 빼면 `build-native-payload.sh`의 root 존재 검사와 SD 이미지 복사가 `src` 없이 돈다(wave 0에서 목록 기반으로 바꿨으므로 코드 변경 없음, ARM64 payload·SD 1회로 확인). 루트 `AGENTS.md` Layout, umbrella `AGENTS.md`의 "Live package `control` is ..." 줄을 갱신한다.

`legacy` 필드와 옛 경로 검사는 모든 root가 moved 또는 partly moved가 된 뒤 한 release 동안 유지하고 지운다(그동안 rebase되는 브랜치를 잡기 위해서다). partly moved root는 `legacy`를 지워도 `deferred`를 유지하므로 이 삭제를 막지 않는다.

## 롤백

- wave는 차례로만 진행하므로 롤백도 역순이다. 가장 최근 wave만 되돌릴 수 있다. 그 wave의 커밋을 역순으로 `git revert`한다. main에서 reset하지 않는다.
- 이미 다음 wave가 들어왔다면 앞 wave를 되돌리지 않는다. 뒤 wave부터 되돌리거나, 결함을 앞으로 고친다(roll forward). 뒤 wave가 같은 `ci.yml`·매니페스트·Dockerfile·AGENTS 줄을 다시 고쳤으므로 앞 wave만 revert하면 충돌하거나 경로가 섞인다.
- wave 안에서도 마지막 커밋부터 되돌린다. 각 커밋이 녹색이므로 어느 커밋 경계에서 멈춰도 main은 녹색이다.
- 데이터·wire·설치 경로가 바뀌지 않으므로 변환 단계가 없다. 1-pre 뒤에는 model-watch wrapper가 두 경로를 다 찾으므로 사이트 PC 재설치가 필요 없다.
- image wave를 되돌렸으면 다음 release 전에 payload inventory·SD 이미지 비교를 다시 한다.

## 동시 작업 규약

1. **공지.** wave를 시작하기 전에 peer 세션(이동 대상 root를 바꾸는 브랜치의 소유자)에게 wave 이름, 이동 root, 동결 창, 기준 SHA를 알린다. ADR 리뷰 때처럼 번호 붙은 질문으로 "착지 / rebase 예정 / 보관(D-172 archive tag)"을 받는다.
2. **동결 창.** 동결은 해당 wave의 root에만 걸린다. 작은 wave(0, 1, 2, 3a, 4a)는 반나절, 큰 wave(3c, 4b–4e)는 하루를 넘기지 않는다. 창 안에서는 그 root에 새 커밋을 넣지 않는다. 창을 넘기면 wave를 접고 다시 공지한다.
3. **한 번에 한 wave.** 앞 wave가 main에 들어가기 전에 다음 wave 브랜치를 만들지 않는다.
4. **브랜치.** wave마다 `refactor/d427-<wave>` 하나, `.worktrees/d427-<wave>`에서 `git worktree add --relative-paths`로 만든다. 한 wave 안의 커밋은 root 하나씩이다.
5. **착지 뒤 peer rebase.** 이동 커밋은 rename 유사도를 유지하므로 `git rebase main`이 대부분 rename을 따라간다. rebase 뒤 `python -m pytest test/architecture -q`를 돌리면 옛 경로에 남은 새 파일이나 옛 경로 문자열이 `test_moved_roots_leave_nothing_behind`에서 잡힌다.
6. **오래된 브랜치.** 2026-10-01 이전 미병합 브랜치는 wave 0 전에 정리됐다: snapshot tag 17개, worktree 제거, 브랜치 유지(결정 기록 참고). tag 없이 남은 오래된 브랜치(`codex/pinky-integrated-current`, `refactor/d362-p0-*`, `refactor/d362-p1-dashboard-split`, `fix/hardware-runtime-truth`, `fix/sd-*`, `feat/sd-writer-operability`, `perf/sd-single-verify`, `feat/role-surfaces-s1`, `refactor/d171-*`, `docs/d362-file-size-budget`)는 그 root를 옮기는 wave의 공지 때 소유자에게 착지·보관을 묻는다.

## 결정된 질문 (Q1–Q9)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | ROS 패키지가 `src/` 밖으로 나가면 colcon 탐색 root를 어떻게 정하나 | 매니페스트 `colcon_roots` 목록 하나를 CI·ARM64 리허설·native payload·SD 이미지·rosdep·개발 스크립트가 읽는다. build/install/log 위치는 저장소 root로 고정한다(wave 0 5번). `--base-paths .` 전체 탐색은 쓰지 않는다 |
| Q2 | 하위 폴더가 다른 파트로 매핑된 패키지를 이동 때 나누나 | 나누지 않는다. 패키지 단위로 옮기고 그 root는 `deferred`(partly moved)로 둔다. 예외는 1c의 `lerobot_export.py`와 2c의 `execution/local` |
| Q3 | `data/`를 `learning/datasets`로 옮기나 | 옮기지 않는다. 매니페스트 목표를 `data`(part learning)로 바꾼다 |
| Q4 | `rosy-execution` wheel을 나누나 | 나눈다. 2c에서 `rosy-execution-local`을 만들고 import 이름은 유지한다. 시점은 2a 뒤, 3a 앞 |
| Q5 | D-399 후속 1 전에 `SkillInvocation`을 contracts로 옮기나 | 옮긴다. 타입은 그대로, 원래 이름은 re-export. 새 배포 이름은 Q9 |
| Q6 | 1c 뒤 생기는 learning → middleware(`omx_adapter.demonstration`) edge | 1c에서 위반 1건을 교체해 집합 크기를 유지하고, 2b에서 demonstration 검증을 Episode profile로 옮겨 지운다 |
| Q7 | `tools/perception`을 나누나, 재생 import edge는 | 통째로 옮기고 2b 뒤에 나눈다. 장치 인식 코드를 재생에 쓰는 edge는 `KNOWN_VIOLATIONS`에 남기고, §2에 재생 전용 예외를 둘지는 별도 결정 |
| Q8 | native payload의 비장치 패키지를 이동 때 빼나 | 빼지 않는다. `isaac_sim`에는 `device_install_exception`을 적는다. 빼는 일은 별도 ARTIFACT 변경 |
| Q9 | 2a의 새 배포 이름 `rosy-contracts-skill`(import `rosy.contracts.skill`)을 쓰나 | 쓴다(2026-10-03 승인). 기존 `core_common`(ament 패키지)에 넣으면 pip wheel이 ament 패키지에 의존하게 되고, 새 배포 없이 두면 위반 3건이 남는다 |

## 열린 질문

없음. Q9(`rosy-contracts-skill` 배포 이름)는 2026-10-03 사용자가 승인했다(위 결정 표).

## 완료 정의

- 모든 root가 moved(`path == d427_target`) 또는 partly moved(`deferred`와 후속 작업 이름)다. pending root가 없다.
- `legacy` 아래 tracked 파일이 없고, wave 5의 한 release 유예 뒤 `legacy` 필드가 지워졌다.
- `colcon_roots`에서 찾은 ROS 패키지 이름 집합이 27개 기준과 같고 `src`가 목록에 없다.
- `KNOWN_VIOLATIONS`가 9건에서 5건으로 줄었다.
- 각 image wave와 그 사이 release마다 CORE·IO·native 설치 closure 비교와 SD 이미지 패키지 목록 비교가 커밋 SHA와 함께 `docs/validation/d427-source-migration/`에 있다. 돌리지 못한 항목은 `NOT_RUN`으로 적고 `ARTIFACT_EQUIVALENT`를 주장하지 않는다.
- 장치 수용은 이 계획의 출구가 아니다.
