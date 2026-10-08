<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-04 -->

# ROSY

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

ROSY is a robot middleware and fleet-control platform (ROS 2 Jazzy, first hardware Pinky Pro). This repository is the robot-side workspace: CORE (middleware/core/gateway) is the external API gateway, supported by shared contracts, events, services, web API, hardware bringup, Nav2/SLAM, Gazebo, Raspberry Pi deploy/robot/pinky_pro/release tooling, and charging-dock ESP32 firmware. middleware/perception contains the absorbed Control package; its legacy final publisher must not run beside CORE. operations/fleet owns the Fleet console and dispatch services. Current source parts are learning, operations, middleware, contracts, integrations, and shared web, as recorded in tools/harness/platform_parts.yaml. Folder role does not establish writer authority, host placement, or image closure (D-315). License: Apache-2.0.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | GitHub landing: system diagram, who-starts-where table, document map, core contracts, short robot-run section. Shared-checkout start order lives in `docs/reference/shared-checkout.md`; build/sim/test/Pi runtime in `docs/reference/developer-guide.md` |
| `LICENSE` | Apache License 2.0 |
| `env.sh` | Dev env: source ROS 2 Jazzy then workspace `install/setup.bash` |
| `CONCEPTS.md` | Shared domain vocabulary — entities, named processes, status concepts with project-specific meaning |
| `PRODUCT.md` | Product schema (`impeccable:product-schema`): platform, users, purpose, positioning — the top-level "who is this for" the UI lanes read |
| `DESIGN.md` | Visual design guide (DESIGN.md format, D-359 §8): tokens, themes, typography, layout tiers, shared components, do/don't. ADRs and contract tests own the contract; sidecar `.impeccable/design.json` is local-only |
| `STATUS.md` | Generated: per-module gate snapshot (SOURCE…FIELD) linking each module's `progress.md`. Edit progress/logs/ADRs, not this file |
| `tools/fix_ament_resource.sh` | Recreate ament `resource/<pkg>` markers for Python packages under the domain groups |
| `tools/run_fleet_sim.sh` | One-click multi-robot Gazebo + fleet orchestration launcher |
| `data/` | Local teleop checks (`teleop/`) and drive recordings (`drive/`). Session files are not committed |
| `.gitignore` | Ignores colcon `build/` `install/` `log/`, `__pycache__`, `.omc/` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `contracts/` | Shared ROS-free skill/motion shapes, foundation and ROS IDL; wheel folders carry `COLCON_IGNORE` (see `contracts/AGENTS.md`) |
| `middleware/` | CORE, device apps, perception, skills, execution, drivers and robot UI (see `middleware/AGENTS.md`) |
| `integrations/` | Robot, simulation, model and fieldbus adapters; placement and import boundaries follow the ownership manifest (see `integrations/AGENTS.md`) |
| `shared/` | Shared web components and operator copy; contracts remain in `contracts/` (see `shared/AGENTS.md`) |
| `docs/` | Governance docs: spec, live API contract, ADR, plans (see `docs/AGENTS.md`) |
| `deploy/` | Image build, signed release, Pi runtime (see `deploy/AGENTS.md`) |
| `tools/` | Developer commands. Not installed on the robot (see `tools/AGENTS.md`) |
| `learning/` | D-427 learning part: `training/perception/` (D-356 learned-loop tooling), `envs/isaac/` (ROS package `isaac_sim`, a `colcon_roots` entry), `curation/omx/` (LeRobot export); see `learning/AGENTS.md` and each child `AGENTS.md`. Only `isaac_sim` reaches a device (native payload, D-427 Q8) |
| `operations/` | D-427 operations part (a `colcon_roots` entry): `world/` (wheel `rosy-world`), `processes/palletizing/` (wheel `rosy-palletizing`, harness module `palletizing`), `execution/` (wheel `rosy-execution`: `rosy.execution.api`, `rosy.execution.site`), `apps/fleet/` (wheel `rosy-app-gateway`, import `rosy_gateway`, console script `rosy-site-gateway`). Wave 3b: ROS packages `apps/games/` (`games`), `vision/` (`rosy_vision`, with the read-only `vision/signal_observer/`), `processes/cell/` (`rosy_cell`); `ui/cam/` (Rosy Cam Android app, `COLCON_IGNORE`); `site_devices/` (dock and signal firmware, see its `AGENTS.md`). Wheel folders carry `COLCON_IGNORE`; see `tools/harness/platform_parts.yaml` and `operations/AGENTS.md` |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |
| `operations/site_devices/` | Dock and signal site devices: firmware outside colcon, device contracts (see `operations/site_devices/AGENTS.md`, D-427 wave 3b) |
| `test/` | Host pytest for deploy/robot/pinky_pro/release/motor contracts (see `test/AGENTS.md`) |
| `docs/assets/` | Architecture and product images (see `docs/assets/AGENTS.md`) |
| `docs/solutions/` | Documented solutions to past problems — bugs, best practices, workflow patterns — by category, with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in a documented area |
| `reference/` | Frozen upstream pinky_pro zip (see `reference/AGENTS.md`) |
| `.github/` | CI workflow (see `.github/AGENTS.md`) |

## For AI Agents

### 모델 PC·AI PC·현장 PC 역할

- **모델 PC:** `learning/`의 데이터·사람 정답·학습·독립 평가·승격 증거와 고정 모델 산출물을 맡는다. 운영 추론·Fleet 판단·장치 명령을 맡지 않는다.
- **AI PC:** 승인된 고정 버전의 추론만 맡는다. 막힘 VLM은 출처·시각이 붙은 정체 사실만, 숙고형 모델은 Mission/Task 후보만 낸다. Fleet 원장 쓰기·admission·ROS·`cmd_vel`·장치 Action 권한은 없다.
- **현장 PC:** `operations/fleet`가 사실을 검증하고 규칙·admission·사람 확인을 거쳐 답을 고른다. 숙고형 코드 목표 자리는 `operations/decision`; 현재 경로와 구현 여부는 [설계](docs/plans/2026-10-08-decision-model-pipeline-design.md)를 본다.
- **로봇:** CORE가 장치 상태·안전을 다시 확인하고 최종 `/cmd_vel`을 단독 발행한다. 소스 경로로 실행 호스트를 추정하지 않는다(D-315). 이 역할 분담은 D-516이며, AI PC의 현장 경로는 아직 활성화되지 않았다.

상세 입력·출력, 모델 교체와 실패 처리: [Decision 모델 파이프라인](docs/plans/2026-10-08-decision-model-pipeline-design.md). 실제 장치 주소·계정은 공개 문서 대신 gitignored `private/`에 둔다.

### D-427 이후 공동 작업 규칙 (2026-10-04, 이동 기간 2·5항 삭제)

소스 이전(D-427·D-429·D-430) 뒤에도 모든 세션이 지킨다. 이전 경로 `legacy`와 잔여 검사에는 한 release 유예를 둔다.

1. **우선순위:** main CI 초록불 > 안전(D-430 공백) > 기능. 충돌하면 앞이 이긴다.
2. **main 체크아웃에서 작업하지 않는다.** 모든 작업은 `.worktrees/<topic>`에서 한다. main 체크아웃에 커밋 안 된 변경을 남기면 다른 세션의 fast-forward와 pre-push가 막힌다. 스테이징·착지·푸시·ADR 번호·기존 실패 비교의 전문은 아래 「같이 하는 깃」이다. `docs/reference/shared-checkout.md`의 같은 제목 절은 같은 착수 순서를 적는다. 명령 카드는 `.claude/skills/rosy-land-on-main/SKILL.md`다.
3. **구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다.** ADR 없이 새 최상위 폴더를 만들지 않는다.
4. **push 전 순서:** `git fetch` → `origin/main` 위로 rebase → `python tools/harness/rosy_harness.py generate`(생성 문서가 바뀌면 커밋) → pre-push 검사(`tools/hooks/pre-push` 목록). force-push 하지 않는다.
5. **safety 태그 경로**(매니페스트 `concern: safety`, `safety_modules`, `safety_anchors`)를 바꾸거나 옮기는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5, CI가 검사).

### 같이 하는 깃

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다. 이 절이 에이전트가 따라 하는 전문이다. `docs/reference/shared-checkout.md`의 「같이 하는 깃」은 같은 착수 순서를 적고, `.claude/skills/rosy-land-on-main/SKILL.md`는 같은 명령을 카드로 반복한다. 문구를 바꿀 때는 이 절과 `docs/reference/shared-checkout.md`의 그 절을 한 커밋에서 같이 고친다. 실험실 PC 우산 `F:\Dev\Control\Robot\Rosy\Agents.md`도 같은 절차를 적는다. 브랜치 이름과 남의 미커밋을 지우지 않는 이유는 [D-372](docs/adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다. 배경은 `docs/solutions/workflow-issues/adr-numbers-collide-between-concurrent-sessions-2026-09-25.md`다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에 자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치를 만든다.** 저장소 루트에서 `git status --short --branch`와 `git worktree list`를 본 다음 `git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main`을 실행한다. `<type>`은 내용과 맞는 `feat`, `fix`, `refactor`, `docs`, `uiux` 가운데 하나다(D-372). 한 브랜치에는 한 주제만 둔다. worktree는 이 저장소의 `.worktrees/`에만 둔다. `.worktrees/`는 gitignore다. 공유 `main` 체크아웃은 `git merge --ff-only`로 착지할 때만 쓴다. 거기에 커밋되지 않은 변경을 남기면 다른 세션의 fast-forward가 거절된다. 스크래치, 로그, pytest 출력은 저장소 밖에 둔다. 실험실 PC에서는 `X:\DevTemp`다. `ListAgents`가 있으면 동료와 그 소유 경로를 본다. 백그라운드 실행기는 단계마다 자기 브랜치에 커밋한다. 그 브랜치에 40분 동안 새 커밋이 없으면 디스패처가 실행기를 확인한다.
2. **자기 경로만 스테이징한다.** `git status --short`에서 이번 작업으로 만들거나 고친 경로만 `git add <path> ...`에 적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 인덱스 하나가 모든 세션의 것이라 넓은 add 한 번이 다른 세션의 파일을 커밋에 넣는다. 잘못된 경로 하나가 `git add` 전체를 실패시키므로, 커밋 전에 exit code를 본다. 경로 없는 커밋 전에는 `git diff --cached --name-only`가 자신의 목록과 같아야 한다. 공유 인덱스에 동료가 이미 올려 둔 경로가 있으면, 파일이 전부 자신 것일 때만 `git commit --only <자신의 경로>`를 쓴다. `--only`는 작업 트리 내용을 기록하기 때문이다. 공유 체크아웃에서 `--amend`, `rebase`, `reset --hard`, `stash`는 쓰지 않는다. 그 사이 HEAD가 동료의 커밋이 될 수 있다. `git commit -- <공유 파일>`도 쓰지 않는다. 작업 트리 전체를 가져가 동료의 행이 들어간다. 이어 쓰는 파일 `docs/reference/ROSY ADR Log.md`와 `docs/logs.md`에 동료의 미커밋 행이 있을 수 있다. 자신의 행만 `git apply --cached --unidiff-zero my-row.patch`로 올리고, `git diff --cached -- <file>`이 자신의 행만 보여 주면 끝이다. 브랜치 이름을 적는 문서는 `git branch`가 출력한 이름을 그대로 쓴다. 자신이 쓰지 않은 경로는 그대로 둔다. stash, revert, checkout, restore, reset, clean, amend, 삭제로 치우지 않는다. 루트의 추적되지 않은 `list.txt`는 로컬 메모라 커밋하지 않는다. 머지나 체크아웃이 그 파일 때문에 거절되면 파일을 그대로 두고 거절 문구를 사용자에게 알린다.
3. **계약을 읽고 고친다.** 제품 파일을 고치기 전에 `README.md`의 「핵심 계약」과 아래 Working In This Directory를 읽는다. 외부 API, 모드, 프로토콜 필드는 SRS, API reference, ADR에 있는 것만 쓴다. 읽기가 끝난 기준은 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연 것이다.
4. **ADR 번호는 파일을 만들기 직전에 도구로 선점한다.** 다른 세션이 몇 분 사이에 같은 번호를 가져간다. `python tools/harness/adr_reserve.py next "<주제>"`를 돌리고 찍힌 번호를 쓴다. 도구는 모든 브랜치와 워크트리의 `docs/adr`, Log 행, gap, `refs/adr/D-*`를 보고 그 다음 번호로 `refs/adr/D-nnn`을 만든다. 같은 ref는 한 세션만 만들 수 있다(D-510). 이 ref는 로컬에만 있어 CI는 모른다. 선점한 ADR이 이 브랜치와 같이 착지하지 않으면 push 전에 `tools/harness/adr_gaps.txt`에 `D-nnn 이유` 한 줄을 넣는다. ADR 파일과 Log 행은 한 커밋이다. Log는 UTF-8 BOM과 CRLF를 유지한다. 그 다음 `python tools/harness/rosy_harness.py lint`를 돌린다. 쓰지 않을 번호는 `python tools/harness/adr_reserve.py release D-nnn --reason "<주제>"`로 푼다. 충돌로 못 쓰게 된 번호도 이유와 함께 `tools/harness/adr_gaps.txt`에 넣는다.
5. **테스트는 기존 실패와 비교한다.** 워크트리에서 관련 pytest를 돌리고 저장소 밖의 로그와 비교한다. 실험실 PC 명령은 아래다.

```bash
python -m pytest <paths> -q -rfE -p no:cacheprovider > X:/DevTemp/<name>/run.txt
python test/known_failures.py X:/DevTemp/<name>/run.txt
```

   exit 1의 `NEW`는 깨끗한 `main` 워크트리에서 달리 확인되기 전에는 그 브랜치의 실패다. 고친 실패의 줄은 같은 커밋에서 `test/known_failures.txt`에서 뺀다. 그 브랜치가 만든 실패를 그 파일에 넣지 않는다. 호스트 pytest 통과는 장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **착지와 푸시는 사용자가 말한 뒤에만 한다.** 기본 방법은 워크트리에서 `python tools/land.py --tests auto`다. 이 도구는 아래 두 단계를 main이 멈출 때까지 되풀이하고, 테스트나 lint가 실패하면 착지하지 않으며, 푸시하지 않는다. 착지는 두 단계다. (1) 워크트리에서 `git merge main`을 하고 관련 테스트를 다시 돌린 다음 `known_failures`와 비교한다. `NEW`가 있으면 브랜치에서 고치고 이 단계를 반복한다. (2) `main` 체크아웃에서 `git merge --ff-only <브랜치>`를 한다. 그 사이에 main에 새 커밋이 있으면 (1)부터 다시 한다. 착지는 `--ff-only`만 한다. `--ff-only`가 동료의 미커밋 파일을 덮어써서 거절되면 그 파일을 그대로 두고 거절 문구를 알린다. stash, checkout, 삭제로 치운 뒤 다시 시도하지 않는다. 푸시는 사용자가 푸시를 말한 뒤에만 한다. 순서는 위의 D-427 4항이다. `git fetch` 하고 `origin/main` 위로 rebase 한 뒤 `python tools/harness/rosy_harness.py generate`를 하고, 생성 문서가 바뀌면 그 변경을 커밋하고, pre-push 검사(`tools/hooks/pre-push` 목록)를 통과한 다음에 push 한다. force-push는 하지 않는다. 로컬 `main`이 `origin/main`보다 앞에 있으면 그 커밋의 CI 증거는 아직 없다.

멈추는 신호는 다음이다. `git add -A`로 다른 파일까지 넣으려 할 때, `test/known_failures.py` 없이 실패를 기존 실패로 부를 때, 조금 전에 비어 보였던 ADR 번호를 다시 보지 않고 쓸 때, 동료의 변경을 stash 했다가 머지 뒤에 되돌리려 할 때, amend가 새 커밋보다 빠르다고 여길 때.

### Working In This Directory

- 새 소스 위치와 소유 영역은 `tools/harness/platform_parts.yaml`의 현재 root와 `d427_target`이 정본이다. 미병합 브랜치는 소유 세션이 최신 `origin/main` 위로 rebase한다.

- Treat `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, and `docs/reference/ROSY ADR Log.md` as contracts. Do not invent REST paths, modes, or protocol fields that are not in the API ref or `core_common.protocol.schemas` (`contracts/foundation/core_common/protocol/schemas.py`).
- External clients must not speak ROS. `core` is the only gateway (CORE SRS §1.3). Command Manager (`core_features.command`) is the only `cmd_vel` publisher (D-2).
- Single process: main thread rclpy `MultiThreadedExecutor`, worker thread uvicorn+FastAPI (D-1). Entry point is `core=core.main:main` — `ros2 run core core`. Do not split into two processes.
- `slam_toolbox` is optional. `ros_bridge` must import it inside try/except, never at module top (`package.xml` comment). CI boots the node without it.
- Config merge order: `contracts/foundation/config/rosy_default.yaml` → `~/.rosy/rosy.yaml` → `ROSY_CONFIG`.
- Do not commit colcon `build/`, `install/`, `log/`, or `__pycache__/`.
- This repo is PUBLIC. Place every new file by D-226: internal material, real device addresses/accounts and filled device config go in the gitignored `private/` (write `<robot-ip>` in public docs); data code or tests read stays beside the reader; dated evidence goes in `docs/validation/<topic>-<YYYY-MM-DD>/`; module how-to goes in the module's one `docs/`. A new secret kind needs its ignore rule and its tracked template added to `test/architecture/test_document_placement.py` in the same change.
- Hardware profile is YAML. In-tree Pinky full spec is `middleware/apps/device/pinky/profile/config/profile.yaml`. The robot advertises `deploy/robot/pinky_pro/config/{profile,capabilities}.${ROSY_RUNTIME_MODE}.yaml` (`core` / `motor` / `hardware`).
- ROS package discovery uses the manifest `colcon_roots` across `learning/`, `operations/`, `middleware/`, `contracts/`, `integrations/`, and `shared/`. Do not reintroduce `rosy_*` or `pinky_*` package names. The CORE launch file still carries its legacy filename `rosy_core.launch.py`.
- Dashboard screens are static files in `middleware/ui/robot`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.
- Project skills in `.claude/skills/`: `rosy-device-access` (SSH to a robot), `rosy-hw-bringup` (board devices), `rosy-land-on-main` (shared checkout, ADR numbers, `test/known_failures.txt`), `rosy-dashboard-drive` (Playwright, `tools/dashboard_drive.py`), `rosy-release-push` (payload release to an existing robot), `rosy-pinky-review` (run and check the Pinky label review app, `tools/review_app_smoke.py`).

### Testing Requirements

Tiers (D-436). **This machine runs the affected tier (fast iteration) and the pre-push fast gate only. The full suite never runs locally by default; it runs on GitHub Actions runners** as a parallel matrix (`.github/workflows/ci.yml`): push to `main`, pull requests whose selection escalates, nightly schedule, `workflow_dispatch`, and before a release build. The arm64 payload already builds on the GitHub ARM64 runner (`build-native-payload.yml`). PR CI runs affected and goes full by itself when the selector escalates (shared foundation `src/contracts/**`, `tools/harness/**`, `conftest.py`, packaging/pytest config, requirements pins, `.github/workflows/**`, or a file that maps to no module). `affected --run` on an escalated selection runs only the guards plus the suites mapped from the changed files (owning module, direct reverse dependents, referencing tests) and says the rest is on GitHub; `--full` forces a local full run (avoid: 40-60 min here, and Windows lacks wheels CI installs).

GitHub results (the full tier is never re-run locally to "check"):

```bash
gh run list --branch <branch> -L 3                      # find the run for your push / PR
gh run watch <run-id> --exit-status                     # wait; non-zero exit when it fails
gh run view <run-id> --log-failed                       # only the failed steps' logs
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'
```

Reproduce locally only the failed matrix entry's pytest invocation (the job name `test (<entry>)` maps to `CI_FULL_MATRIX` in `tools/harness/affected_tests.py`, or to the `affected-N` invocation printed by the `Test scope (D-436)` step). A local `main` that is not pushed has no CI evidence.

```bash
# Affected tier (D-436): tests of the touched modules + reverse dependents + tests naming the
# changed paths + the guard set; prints why each suite runs and when it escalates to FULL.
# Suites sharing a test basename (gateway vs sensing test_battery.py) come out as separate runs.
python tools/harness/rosy_harness.py affected --base main          # print the selection
python tools/harness/rosy_harness.py affected --base main --run    # run it

# Quick tier (D-346): the pre-commit/push gate (~3 min).
# Same suite as the pre-push hook (tools/hooks/install.sh). 2026-10-01: dashboard
# contract + root contract suites added after the D-362 split and secret-scan/
# scorecard classes landed red through the old tier.
python3 -m pytest test/test_harness_contracts.py test/architecture/test_module_structure.py \
  test/test_io_image_closure.py test/test_line_follow_contract_docs.py \
  test/test_behavior_test_ownership.py test/test_module_scorecard.py \
  test/test_release_boundary_guards.py test/test_robot_literals.py \
  middleware/core/gateway/test/test_protocol_version_alignment.py \
  middleware/core/gateway/test/test_event_catalogue.py \
  middleware/core/gateway/test/test_console_layout.py \
  middleware/core/gateway/test/test_host_cards.py \
  middleware/core/gateway/test/test_host_hardware.py \
  middleware/core/gateway/test/test_triage_contract.py \
  middleware/core/gateway/test/test_host_status_summary.py -q
python3 tools/harness/rosy_harness.py lint   # ADR duplicates, mojibake, append-only

# Full tier: runs on GitHub runners (see above), not here. The commands below are what a
# Linux/WSL host would run to reproduce one CI matrix entry, not a routine local step.
# ROS 2 overlay (Linux / Pi). On Windows, run Python tests that do not need rclpy.
source env.sh
colcon --log-base log build --symlink-install --base-paths $(python3 tools/harness/colcon_roots.py) --build-base build --install-base install

# core unit tests (no live ROS required for most)
python3 -m pytest middleware/core/gateway/test/ middleware/core/events/test/ middleware/core/services/test/ shared/web/test/ -v

# Fleet formation/relay/session/console (no ROS)
python3 -m pytest operations/fleet/test/ -v

# Deploy, release, motor, Wi-Fi, host-agent contracts (host)
python3 -m pytest test/ -v

# CI also: flake8 (max 120), boot smoke without slam_toolbox
```

CI (`.github/workflows/ci.yml`) on `main` / PRs: colcon build in `ros:jazzy-ros-base`, pytest, boot smoke, SaveMap type guard — all on domain-tree paths. Note: `origin` exists (`github.com/robotics-team-1213/rosy-platform.git`) and CI events fire on push and pull requests — check the latest run (`gh run list`) for current status; a local `main` that is ahead of `origin/main` has no CI evidence at all.

### Common Patterns

- Requirement IDs (`CORE-001`, `SAF-005`, `PWR-001`) not section numbers (D-17).
- Python packages: ament_python (`setup.py` + `package.xml`). C++/URDF/Nav2/interfaces: ament_cmake.
- Namespaces + `frame_prefix` for multi-robot (D-4). Robot identity has **no default**:
  `ROS_DOMAIN_ID` = 40 + N and `ROSY_NAMESPACE` = `rosy_%02d` are derived from
  `ROSY_ROBOT_NUMBER` at install, and a missing identity stops the runtime (D-33).
  A default here is what once shipped every unit as 42/`rosy_01`.
- Dashboard screens are static files in `middleware/ui/robot`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.

## Dependencies

### Internal

- `middleware/core/gateway` depends on `contracts/foundation`, `middleware/core/events`, `middleware/core/services`, `middleware/core/api_web`, and `contracts/ros_idl` (plus, at runtime, bringup/Nav2 topics).
- `deploy/` consumes `src/` via `deploy/robot/pinky_pro/Dockerfile`.
- `test/` imports `deploy/robot/pinky_pro/release` via `test/conftest.py` `sys.path`.

### External

- ROS 2 Jazzy, rclpy/rclcpp, Nav2, CycloneDDS
- FastAPI, uvicorn, pydantic, PyYAML, httpx, websockets
- Optional: slam_toolbox, sllidar_ros2, Gazebo (ros_gz), wiringPi I2C, ws2811, Dynamixel SDK

<!-- MANUAL: -->
