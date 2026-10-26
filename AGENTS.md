<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-04 -->

# ROSY

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-14

## Purpose

문서 편집은 [D-777](docs/adr/D-777-concise-human-agent-documentation.md)을 따른다. 공유·협업 문서는 독자의 작업 위치와 다음 행동부터 안내하고, 상세 규칙은 해당 기준 문서로 연결한다.

ROSY Platform connects observed world state, site orchestration, device execution, and offline learning/evaluation (ROS 2 Jazzy, first hardware Pinky Pro). This repository contains the platform's source, not only the robot workspace. CORE (`middleware/core/gateway`) owns the external API and final Base command path; OMX retains its joint/action owner. `operations/fleet` owns serving and dispatch transactions; canonical Console assets live in `applications/fleet/web`, and existing advisory Decision code in `operations/decision/src/rosy/decision` (`rosy.decision`), both installed by the same Fleet distribution; `operations/world` owns the current sighting, operator-pin, and odom MapPose projection. Fleet imports `rosy.world.state.projections.map_pose` directly; the Fleet alias is gone (D-752). `source=bridged` is dead reckoning, not a future rollout. Action-conditioned future World prediction remains planned. The existing ROS `control` distribution remains in `middleware/perception`: sensor and vision implementations live in `sensors/sensing` and `vision/perception`, while Drive algorithms and the Nav2 backend live in `middleware/drive/{planning,tracking,recovery,calibration,safety}`. Legacy node composition remains under `middleware/perception/control`; its legacy final publisher (`control/safety_node.py`) must not run beside CORE. Source mapping preserves `control.*` imports and installed resources. Current source parts and all holder decisions are in `tools/harness/platform_parts.yaml` and [the folder responsibility guide](docs/reference/platform-folder-responsibilities.md). Folder role does not establish writer authority, host placement, or image closure (D-315). License: Apache-2.0.

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
| `applications/` | Product application holders; Fleet UI and gateway composition live in `applications/fleet` (see `applications/AGENTS.md`, D-822) |
| `middleware/` | CORE, device apps, perception, skills, execution, drivers and robot UI (see `middleware/AGENTS.md`) |
| `integrations/` | Robot, simulation, model and fieldbus adapters; placement and import boundaries follow the ownership manifest (see `integrations/AGENTS.md`) |
| `shared/` | Shared web components and operator copy; contracts remain in `contracts/` (see `shared/AGENTS.md`) |
| `docs/` | Governance docs: spec, live API contract, ADR, plans (see `docs/AGENTS.md`) |
| `deploy/` | Image build, signed release, Pi runtime (see `deploy/AGENTS.md`) |
| `tools/` | Developer commands. Not installed on the robot (see `tools/AGENTS.md`) |
| `learning/` | D-427 learning part: `curation/perception/` (data and review), `registry/perception/` (artifact/provenance store and delivery), `training/perception/` (trainer), `evaluation/perception/` (replay); orchestration CLI is `tools/perception/`, `envs/isaac/` (ROS package `isaac_sim`, a `colcon_roots` entry), `curation/omx/` (LeRobot export); see `learning/AGENTS.md` and each child `AGENTS.md`. Only `isaac_sim` reaches a device (native payload, D-427 Q8) |
| `operations/` | D-427 operations part (a `colcon_roots` entry): `decision/` (existing `rosy.decision`, same Fleet distribution), `applications/fleet/web` (canonical Fleet-served assets), `world/` (wheel `rosy-world`; direct MapPose import, D-752), `processes/palletizing/` (wheel `rosy-palletizing`, harness module `palletizing`), `site_execution/` (wheel `rosy-execution`: `rosy.execution.api`, `rosy.execution.site`), `applications/fleet/gateway` (wheel `rosy-app-gateway`, import `rosy_gateway`, console script `rosy-site-gateway`). Wave 3b: ROS packages `apps/games/` (`games`), `overhead/` (`rosy_vision`; read-only signal observation is `signal_observation/`), `processes/cell/` (`rosy_cell`); `site_ui/cam/` (Rosy Cam Android app, `COLCON_IGNORE`); `site_devices/` (dock and signal firmware, see its `AGENTS.md`). Wheel folders carry `COLCON_IGNORE`; see `tools/harness/platform_parts.yaml` and `operations/AGENTS.md` |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |
| `operations/site_devices/` | Dock and signal site devices: firmware outside colcon, device contracts (see `operations/site_devices/AGENTS.md`, D-427 wave 3b) |
| `test/` | Host pytest for deploy/robot/pinky_pro/release/motor contracts (see `test/AGENTS.md`) |
| `docs/assets/` | Architecture and product images (see `docs/assets/AGENTS.md`) |
| `docs/solutions/` | Documented solutions to past problems — bugs, best practices, workflow patterns — by category, with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in a documented area |
| `.github/` | CI workflow (see `.github/AGENTS.md`) |

## For AI Agents

### 모델 PC·AI PC·현장 PC 역할

- **모델 PC:** `learning/`의 데이터·사람 정답·학습·독립 평가·승격 증거와 고정 모델 산출물을 맡는다. 운영 추론·Fleet 판단·장치 명령을 맡지 않는다.
- **AI PC:** 승인된 고정 버전의 추론만 맡는다. 막힘 VLM은 출처·시각이 붙은 정체 사실만, 숙고형 모델은 Mission/Task 후보만 낸다. Fleet 원장 쓰기·admission·ROS·`cmd_vel`·장치 Action 권한은 없다.
- **현장 PC:** `operations/fleet`가 사실을 검증하고 규칙·admission·사람 확인을 거쳐 답을 고른다. 기존 Decision 구현은 `operations/decision/src/rosy/decision`으로 분리했고 Fleet transaction과 배포를 유지한다. 후속 숙고형 모델 파이프라인의 구현 여부는 [설계](docs/plans/2026-10-08-decision-model-pipeline-design.md)를 본다.
- **로봇:** CORE가 장치 상태·안전을 다시 확인하고 최종 `/cmd_vel`을 단독 발행한다. 소스 경로로 실행 호스트를 추정하지 않는다(D-315). 이 역할 분담은 D-516이며, AI PC의 현장 경로는 아직 활성화되지 않았다.

시험 위치도 분리한다(D-527). 개발 PC는 원격 시험을 요청하고 CI는 코드 계약과 푸시 게이트, 모델 PC는 사람 정답 기반 Laya/Kev·VLM 독립 평가와 승격 receipt, AI PC는 승인 고정 버전의 적재·GPU·loopback 스모크와 watchdog, 현장 Fleet·CORE는 그림자/장치 수용을 맡는다. AI PC 합성 재생의 일치 수치를 L0 정확도로 쓰지 않는다.

상세 입력·출력, 모델 교체와 실패 처리: [Decision 모델 파이프라인](docs/plans/2026-10-08-decision-model-pipeline-design.md). 실제 장치 주소·계정은 공개 문서 대신 gitignored `private/`에 둔다.

### D-427 이후 공동 작업 규칙 (2026-10-04, 이동 기간 2·5항 삭제)

소스 이전(D-427·D-429·D-430) 뒤에도 모든 세션이 지킨다. 이전 경로 `legacy`와 잔여 검사에는 한 release 유예를 둔다.

1. **우선순위:** main CI 초록불 > 안전(D-430 공백) > 기능. 충돌하면 앞이 이긴다.
2. **main 체크아웃에서 작업하지 않는다.** 모든 작업은 `.worktrees/<topic>`에서 한다. main 체크아웃에 커밋 안 된 변경을 남기면 다른 세션의 fast-forward와 pre-push가 막힌다. 스테이징·착지·푸시·ADR 번호·기존 실패 비교의 전문은 아래 「같이 하는 깃」이다. `docs/reference/shared-checkout.md`의 같은 제목 절은 같은 착수 순서를 적는다. 명령 카드는 `.claude/skills/rosy-land-on-main/SKILL.md`다.
3. **구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다.** ADR 없이 새 최상위 폴더를 만들지 않는다.
4. **push 순서는 [D-868](docs/adr/D-868-local-main-first-merge-commit-publish.md)이 대체했다:** 모든 변경은 로컬 `main`에 먼저 착지하고, 공개 `main`에는 그 로컬 `main`을 merge commit PR로 올린다. 순서는 아래 「같이 하는 깃」 6항이다.
5. **safety 태그 경로**(매니페스트 `concern: safety`, `safety_modules`, `safety_anchors`)를 바꾸거나 옮기는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5, CI가 검사).

### 같이 하는 깃

워크트리 운영 예산은 **main 포함 최대 15개**이며, 신규 생성 전에 [공유 체크아웃의 슬롯 운영 규칙](docs/reference/shared-checkout.md#워크트리-한도와-슬롯-운영)을 먼저 따른다. 한도에서는 완료 작업 정리·필요 변경의 커밋과 검증·장기 대기의 보존으로 슬롯을 회수한다. 도구도 같은 값(`.worktrees/` 14개)에서 막는다(D-886). 브랜치 종류·이름·수명은 같은 문서의 [「브랜치 이름과 수명」](docs/reference/shared-checkout.md#브랜치-이름과-수명)을 따른다.

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다. 이 절이 에이전트가 따라 하는 전문이다. `docs/reference/shared-checkout.md`의 「같이 하는 깃」은 같은 착수 순서를 적고, `.claude/skills/rosy-land-on-main/SKILL.md`는 같은 명령을 카드로 반복한다. 문구를 바꿀 때는 이 절과 `docs/reference/shared-checkout.md`의 그 절을 한 커밋에서 같이 고친다. 실험실 PC에서 이 저장소의 상위 폴더에 있는 우산 `..\AGENTS.md`(git 밖)도 같은 절차를 적는다. 사람용 요약과 팀원의 PR 길은 `docs/reference/git-workflow.md`다. 브랜치 이름과 남의 미커밋을 지우지 않는 이유는 [D-372](docs/adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다. 배경은 `docs/solutions/workflow-issues/adr-numbers-collide-between-concurrent-sessions-2026-09-25.md`다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에 자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치를 만든다.** 저장소 루트에서 `git status --short --branch`와 `git worktree list`를 본 다음 `python tools/worktrees.py new <짧은이름> <type>/<topic>`을 실행한다. 맨손 `git worktree add`는 쓰지 않는다. `<type>`은 내용과 맞는 `feat`, `fix`, `refactor`, `docs`, `uiux` 가운데 하나다(D-372). `<topic>`은 영문 소문자·숫자를 `-`로 이은 48자 이내다(D-886). 한 브랜치에는 한 주제만 둔다. 착지 단위로 나눈다: 한 브랜치는 따로 착지할 수 있는 관심사 하나와 한 모듈 계열이고, 바뀐 파일이 15개를 넘거나 `tools/land.py --dry-run`이 FULL을 찍으면 먼저 나눌 수 있는지 본다(FULL 한 라운드는 시험 PC에서 30~90분이다). FULL 트리거(`tools/harness/**`, `contracts/foundation/**`)나 공유 자산(`shared/web`)을 바꾸는 부분은 제품 변경과 다른 브랜치로 먼저 착지한다. D-766 한도의 95% 이상인 파일·단위에 더할 일은 그 나누기 브랜치를 먼저 착지한다. 배경은 `docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`다. 이 도구는 아무것도 지우지 않는다. 치울 수 있는 끝난 워크트리가 있으면 개수와 명령 `python tools/worktrees.py prune --apply`를 한 줄로 알린다(D-761, Proposed). 그 명령은 누가 만들었든 깨끗하고, `main`에 들어갔고, 잠기지 않았고, 캐시가 아닌 gitignore 파일이 없고, 충분히 쉰 워크트리만 지운다. 그런 워크트리는 잃을 것이 없다. 충분히는 브랜치에 자기 커밋이 있고 `main`에 들어간(착지한) 것이면 1시간, 그 밖의 것(방금 만들어 아직 커밋이 없는 워크트리 포함)은 72시간이다(D-790, Proposed). 자신이 만든 워크트리(소유자 기록이 호출한 쪽의 신원과 같고, 세션 id가 적혀 있으면 그것까지 같은 것)는 착지했고 깨끗하면 기다리지 않고 바로 지운다. git이 더는 모르는 `.worktrees/` 아래 디렉터리(orphan)도 1시간 쉬면 지운다. 캐시와 `.omc/state` 밖의 파일이 있으면 먼저 `$ROSY_SCRATCH/worktree-orphans/<이름>-<날짜>.zip`에 보관하고 그 보관 파일을 다시 열어 확인한 뒤에만 지운다. `new --prune`은 만들기 전에 그 청소를 한다. `.worktrees/` 아래가 14개(main 포함 15개) 이상이면 만들지 않고, 지금 누구나 치울 수 있는 워크트리와 소유자만 치울 수 있는 워크트리를 이름과 소유자로 보여 준다. `new`는 소유자로 git 신원과 세션 id를 적고, `--owner "<누구>"`가 있으면 그것을 적는다. 소유자 기록이 없는 워크트리는 `status`에 `unknown`으로 나온다. `status`의 `landed-dirty`는 이미 `main`에 들어간 브랜치의 워크트리에 미커밋 파일이 있다는 뜻이다. 그 워크트리에서 계속 일하지 말고 새 워크트리를 만들어 옮긴다. `stale-history`는 이력 재작성 이전 줄기의 브랜치다(`main`에 없는 커밋이 2,000개 넘음, 또는 `ad86fca808` 이전에서 갈라짐). 병합·착지하지 않고 필요한 것만 `main`에서 새 브랜치로 다시 만든다(D-172). `new --from <ref>`는 그런 ref에서 만들지 않는다. 그때 볼 것은 `python tools/worktrees.py status`다. 이 표는 행마다 소유자와 자신이 지울 수 있는지를 보여 준다. `prune --snapshot`은 커밋 안 된 내용을 `refs/wip/<날짜>/<이름>`에 남기고 더럽거나 `main`에 안 들어간 워크트리까지 지우므로 사람이나 디스패처만 돌린다. 세션이 알아서 돌리지 않는다. `--snapshot`은 호출한 쪽이 `new`로 만든 워크트리만 다루고, 다른 세션 것과 소유자 기록이 없는 것은 `--all`을 줘야 다룬다. 사고 대응 중에는 `--force-over-cap "<이유>"`로 상한을 넘겨 만든다. 오래 둘 워크트리는 `git worktree lock`으로 잠근다. worktree는 이 저장소의 `.worktrees/`에만 둔다. `.worktrees/`는 gitignore다. 공유 `main` 체크아웃은 `git merge --ff-only`로 착지할 때만 쓴다. 거기에 커밋되지 않은 변경을 남기면 다른 세션의 fast-forward가 거절된다. 스크래치, 로그, pytest 출력은 저장소 밖 `$ROSY_SCRATCH`에 둔다(없으면 시스템 임시 폴더. 실험실 PC는 `ROSY_SCRATCH=X:\DevTemp`). `ListAgents`가 있으면 동료와 그 소유 경로를 본다. 백그라운드 실행기는 단계마다 자기 브랜치에 커밋한다. 그 브랜치에 40분 동안 새 커밋이 없으면 디스패처가 실행기를 확인한다.
2. **자기 경로만 스테이징한다.** `git status --short`에서 이번 작업으로 만들거나 고친 경로만 `git add <path> ...`에 적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 인덱스 하나가 모든 세션의 것이라 넓은 add 한 번이 다른 세션의 파일을 커밋에 넣는다. 잘못된 경로 하나가 `git add` 전체를 실패시키므로, 커밋 전에 exit code를 본다. 경로 없는 커밋 전에는 `git diff --cached --name-only`가 자신의 목록과 같아야 한다. 공유 인덱스에 동료가 이미 올려 둔 경로가 있으면, 파일이 전부 자신 것일 때만 `git commit --only <자신의 경로>`를 쓴다. `--only`는 작업 트리 내용을 기록하기 때문이다. 공유 체크아웃에서 `--amend`, `rebase`, `reset --hard`, `stash`는 쓰지 않는다. 그 사이 HEAD가 동료의 커밋이 될 수 있다. `git commit -- <공유 파일>`도 쓰지 않는다. 작업 트리 전체를 가져가 동료의 행이 들어간다. 이어 쓰는 파일 `docs/reference/ROSY ADR Log.md`와 `docs/logs.md`에 동료의 미커밋 행이 있을 수 있다. 자신의 행만 `git apply --cached --unidiff-zero my-row.patch`로 올리고, `git diff --cached -- <file>`이 자신의 행만 보여 주면 끝이다. 브랜치 이름을 적는 문서는 `git branch`가 출력한 이름을 그대로 쓴다. 자신이 쓰지 않은 경로는 그대로 둔다. stash, revert, checkout, restore, reset, clean, amend, 삭제로 치우지 않는다. 루트의 추적되지 않은 `list.txt`는 로컬 메모라 커밋하지 않는다. 머지나 체크아웃이 그 파일 때문에 거절되면 파일을 그대로 두고 거절 문구를 사용자에게 알린다.
3. **계약을 읽고 고친다.** 제품 파일을 고치기 전에 `README.md`의 「핵심 계약」과 아래 Working In This Directory를 읽는다. 외부 API, 모드, 프로토콜 필드는 SRS, API reference, ADR에 있는 것만 쓴다. 읽기가 끝난 기준은 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연 것이다.
4. **ADR 번호는 파일을 만들기 직전에 도구로 선점한다.** 다른 세션이 몇 분 사이에 같은 번호를 가져간다. `python tools/harness/adr_reserve.py next "<주제>"`를 돌리고 찍힌 번호를 쓴다. 도구는 모든 브랜치와 워크트리의 `docs/adr`, Log 행, gap, `refs/adr/D-*`를 보고 그 다음 번호로 `refs/adr/D-nnn`을 만든다. 같은 ref는 한 세션만 만들 수 있다(D-510). 이 ref는 로컬에만 있어 CI는 모른다. 선점한 ADR이 이 브랜치와 같이 착지하지 않으면 push 전에 `tools/harness/adr_gaps.txt`에 `D-nnn 이유` 한 줄을 넣는다. ADR 파일과 Log 행은 한 커밋이다. Log는 UTF-8 BOM과 CRLF를 유지한다. 그 다음 `python tools/harness/rosy_harness.py lint`를 돌린다. 쓰지 않을 번호는 `python tools/harness/adr_reserve.py release D-nnn --reason "<주제>"`로 푼다. 충돌로 못 쓰게 된 번호도 이유와 함께 `tools/harness/adr_gaps.txt`에 넣는다. API reference 버전(`**Version:** v1.NNN`)도 같은 방식으로 `python tools/harness/api_reserve.py next "<주제>"`가 `refs/api/v1.NNN`을 선점하고, 번호를 바꿀 때는 `python tools/harness/api_reserve.py bump v1.NNN` 한 번이 헤더·테스트·`app.py`의 고정값만 옮긴다(자신의 changelog 행 제목은 손으로 고친다).
5. **테스트는 기존 실패와 비교한다.** 워크트리에서 관련 pytest를 돌리고 저장소 밖의 로그와 비교한다. pytest는 이 노트북에서 돌리지 않는다. `tools/remote/remote_pytest.py`가 모델 PC(OMEN), AI PC, 현장 PC 가운데 여유가 있는 곳(현장 PC는 맨 뒤, D-568)에서 돌리고 로그를 `$ROSY_SCRATCH\<이름>\`로 가져온다. pre-push와 `tools/land.py`가 이를 쓴다. 시험 PC가 하나도 닿지 않으면 노트북으로 넘어가지 않고 10분 동안 30초마다 다시 시도한 뒤 실패로 끝낸다(D-584). 그 시험은 "확인 못 함"이고 착지와 푸시는 하지 않는다. `--local`과 `ROSY_TEST_LOCAL`은 오류로 거절한다. 커밋된 HEAD만 보내므로 먼저 커밋한다. Gazebo는 노트북에서 돌리지 않고 `python tools/remote/remote_pytest.py --pick sim`이 고른 PC에서 돌린다. 실험실 PC 명령은 아래다.

```bash
python tools/remote/remote_pytest.py --log-dir $ROSY_SCRATCH/<name> -- <paths>
python test/known_failures.py $ROSY_SCRATCH/<name>/run-1.txt
```

   exit 1의 `NEW`는 깨끗한 `main` 워크트리에서 달리 확인되기 전에는 그 브랜치의 실패다. 고친 실패의 줄은 같은 커밋에서 `test/known_failures.txt`에서 뺀다. 그 브랜치가 만든 실패를 그 파일에 넣지 않는다. 호스트 pytest 통과는 장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **착지와 푸시는 사용자가 말한 뒤에만 한다.** 기본 방법은 워크트리에서 `python tools/land.py --tests auto`다. 이 도구는 시험 회차 전에 착지 대기열(`<git-common-dir>/rosy-land-queue/`, D-803)에서 표를 받고, 앞선 착지가 끝날 때까지 순번과 앞선 브랜치를 찍으며 기다린다. `--queue-timeout` 분(기본 180)을 넘으면 아무것도 병합·시험하지 않고 멈춘다. 맨 앞이 되면 `main`을 한 번 병합하고 시험한다. 표는 끝날 때(오류와 Ctrl-C 포함) 풀리고, 죽은 프로세스의 표(같은 호스트에서 pid 없음, 또는 3시간 동안 새로 고쳐지지 않음)는 다음 세션이 지운다. `--no-queue`는 사고 대응 때만 쓴다. FULL 티어가 통과한 뒤 `main`이 움직이면 다음 회차는 그 뒤 `main` 변경분의 선택만 돈다. 실행이 끊겨(시험 PC 끊김, Ctrl-C, 회차 상한) `land.py`를 다시 돌려도, 브랜치가 그때 시험한 변경과 `main` 병합만 가지고 있으면 같은 규칙을 쓴다(`<git-common-dir>/rosy-land-full/`, D-803 6). 브랜치에 자기 커밋이 더해졌으면 FULL을 다시 돈다. 이 도구는 아래 두 단계를 main이 멈출 때까지 되풀이하고, 테스트나 lint가 실패하면 착지하지 않으며, 푸시하지 않는다. 착지는 두 단계다. (1) 워크트리에서 `git merge main`을 하고 관련 테스트를 다시 돌린 다음 `known_failures`와 비교한다. `NEW`가 있으면 브랜치에서 고치고 이 단계를 반복한다. (2) `main` 체크아웃에서 `git merge --ff-only <브랜치>`를 한다. 그 사이에 main에 새 커밋이 있으면 (1)부터 다시 한다. 착지는 `--ff-only`만 한다. `--ff-only`가 동료의 미커밋 파일을 덮어써서 거절되면 그 파일을 그대로 두고 거절 문구를 알린다. stash, checkout, 삭제로 치운 뒤 다시 시도하지 않는다. `tools/land.py`는 시작할 때 치울 수 있는 끝난 워크트리 개수를 알리기만 한다. `--prune`을 주면 1번의 손실 없는 청소를 하고, `--no-prune`을 주면 알리지도 않는다. 착지한 자신의 워크트리는 그 워크트리에서 나온 뒤 `main` 체크아웃에서 명령 하나 `python tools/worktrees.py prune --apply`로 치운다(남의 착지한 워크트리는 1시간, 착지 증거가 없는 것은 72시간 뒤에 지운다). 착지한 워크트리에서 다음 일을 이어 하지 않는다. `tools/land.py`는 옛 이력 브랜치(`stale-history`)를 착지하지 않고, 원격 시험 전에 `tools/harness/size_range.py`로 D-766 크기를 본다. 착지 전에 `python tools/harness/size_range.py main HEAD`로 직접 볼 수 있다. NEW 실패가 1~5개이고 안전 루트 밖이면 각 id를 따로 한 번 다시 돌리고, 모두 통과하면 `LOAD-FLAKY`로 알리고 착지를 계속하며 공통 git 디렉터리의 `rosy-flaky-candidates.txt`에 적는다. 그 목록은 사람이 보고 증거가 맞을 때만 `test/flaky_quarantine.txt`로 옮긴다. 다시 실패하면 지금처럼 멈춘다(D-790). 같은 git 트리·명령·시험 환경(`remote_pytest.deps`)에서 이미 통과한 pytest 호출은 다시 돌리지 않고, 셀렉터가 차이에 고르지 않은 호출도 조상 커밋의 통과를 쓴다(`tools/land_cache.py`, 공통 git 디렉터리의 `rosy-land-cache.jsonl`). 모두 다시 돌리려면 `--no-cache`. 멈춘 라운드의 NEW id는 `main`에서 한 번 더 돌린다. 거기서도 실패하는 id는 `MAIN-RED`로 찍히고 멈춤 문구가 main이 깨졌다고 적는다. 그때는 자기 브랜치를 고치지 말고, 동료가 이미 고치는지 본 다음 main만 고치는 작은 `fix/` 브랜치를 먼저 착지한다. 착지하지 않고 보류하는 브랜치는 커밋해 두면 브랜치가 남는다. 워크트리까지 남기려면 `git worktree lock`으로 잠근다. 푸시는 사용자가 푸시를 말한 뒤에만 한다. 순서는 [D-868](docs/adr/D-868-local-main-first-merge-commit-publish.md)이다. `git fetch` 하고, `origin/main`이 로컬 `main`의 조상이 아니면 워크트리에서 `git merge origin/main`으로 합쳐 `tools/land.py`로 착지한다. `python tools/harness/rosy_harness.py generate`로 생성 문서를 맞춘 뒤 로컬 `main`의 끝을 `publish/main-<YYYYMMDD>` 브랜치로 push하고(pre-push 검사 통과) PR을 연다. `ci-result`가 녹색이면 `gh pr merge <PR> --merge --match-head-commit <SHA>`로 merge commit 병합하고, `main` 체크아웃에서 `git merge --ff-only origin/main`으로 맞춘다. squash·rebase 병합과 force-push는 하지 않는다. 로컬 `main`이 `origin/main`보다 앞에 있으면 그 커밋의 CI 증거는 아직 없다.

주제 브랜치는 `origin/main`이 아니라 로컬 `main`에서 만든다. 이미 게시한 브랜치는 `git merge`로 갱신하고 force-push하지 않는다. 공개 GitHub 게시·검토·병합은 아래 「GitHub 게시와 두 에이전트 검토」를 따른다.

멈추는 신호는 다음이다. `git add -A`로 다른 파일까지 넣으려 할 때, `test/known_failures.py` 없이 실패를 기존 실패로 부를 때, 조금 전에 비어 보였던 ADR 번호를 다시 보지 않고 쓸 때, 동료의 변경을 stash 했다가 머지 뒤에 되돌리려 할 때, amend가 새 커밋보다 빠르다고 여길 때.

### GitHub 게시와 두 에이전트 검토

공개 `main`은 로컬 `main`을 올린 PR의 merge commit 병합으로만 갱신한다(D-868). squash·rebase 병합은 쓰지 않는다. GitHub 사람 승인 수는 0, 필수 검사는 `ci-result`다(2026-10-16 사용자 결정). 작성 에이전트와 다른 읽기 전용 검토 에이전트가 base/head SHA를 지정해 검토하고, 게시 담당 한 명이 사용자에게 허용받은 범위의 push·PR·병합을 수행한다. 검토 결과·발견 사항 처리·시험 SHA·실제 CI 결과를 PR에 남긴다. 문서·생성물·merge 해결을 포함해 head가 바뀌면 변경 범위의 재검토와 새 SHA 검증이 필요하며 최종 게시 head는 검토 head와 같아야 한다. 절차와 종료 조건은 [PR 파이프라인](docs/reference/pr-pipeline.md)이 소유한다. 위의 `tools/land.py`는 로컬 착지 도구이며 공개 `main`에 직접 push하는 경로가 아니다. 공개 `main`은 ruleset이 직접 push를 막는다.

### Working In This Directory

- 새 소스 위치와 소유 영역은 `tools/harness/platform_parts.yaml`의 현재 root와 `d427_target`이 정본이다. 브랜치는 로컬 `main`에서 만들고 `git merge main`으로 갱신한다(D-868).

- Treat `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, and `docs/reference/ROSY ADR Log.md` as contracts. Do not invent REST paths, modes, or protocol fields that are not in the API ref or `core_common.protocol.schemas` (`contracts/foundation/core_common/protocol/schemas.py`).
- External clients must not speak ROS. `core` is the only gateway (CORE SRS §1.3). Command Manager (`core_features.command`) is the only `cmd_vel` publisher (D-2).
- Single process: main thread rclpy `MultiThreadedExecutor`, worker thread uvicorn+FastAPI (D-1). Entry point is `core=core.main:main` — `ros2 run core core`. Do not split into two processes.
- `slam_toolbox` is optional. `ros_bridge` must import it inside try/except, never at module top (`package.xml` comment). CI boots the node without it.
- Config merge order: `contracts/foundation/config/rosy_default.yaml` → `~/.rosy/rosy.yaml` → `ROSY_CONFIG`.
- Do not commit colcon `build/`, `install/`, `log/`, or `__pycache__/`.
- This repo is PUBLIC. Place every new file by D-226: internal material, real device addresses/accounts and filled device config go in the gitignored `private/` (write `<robot-ip>` in public docs); data code or tests read stays beside the reader; dated evidence goes in `docs/validation/<topic>-<YYYY-MM-DD>/`; module how-to goes in the module's one `docs/`. Lab SSH targets are `private/lab-hosts.json`, copied from `tools/remote/hosts.example.json`. A new secret kind needs its ignore rule and its tracked template added to `test/architecture/test_document_placement.py` in the same change.
- Hardware profile is YAML. In-tree Pinky full spec is `middleware/devices/pinky/profile/config/profile.yaml`. The robot advertises `deploy/robot/pinky_pro/config/{profile,capabilities}.${ROSY_RUNTIME_MODE}.yaml` (`core` / `motor` / `hardware`).
- ROS package discovery uses the manifest `colcon_roots` across `learning/`, `operations/`, `middleware/`, `contracts/`, `integrations/`, `shared/`, and `applications/`. Do not reintroduce `rosy_*` or `pinky_*` package names. The CORE launch file still carries its legacy filename `rosy_core.launch.py`.
- Dashboard screens are static files in `middleware/robot_ui/robot`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.
- Project skills in `.claude/skills/`: `rosy-device-access` (SSH to a robot), `rosy-hw-bringup` (board devices), `rosy-land-on-main` (shared checkout, ADR numbers, `test/known_failures.txt`), `rosy-dashboard-drive` (Playwright, `tools/dashboard_drive.py`), `rosy-release-push` (payload release to an existing robot), `rosy-pinky-review` (run and check the Pinky label review app, `learning/curation/perception/tools/review_app_smoke.py`), `rosy-fast-field-test` (fastest path from a model or code change to a real Pinky drive: on-robot loop, model pointer, release in parallel).

### Testing Requirements

Tiers (D-436). **This machine requests affected and pre-push pytest through `tools/remote/remote_pytest.py`; pytest never runs on this laptop (D-584). The full suite runs on GitHub Actions runners** as a parallel matrix (`.github/workflows/ci.yml`): push to `main`, pull requests whose selection escalates, nightly schedule, `workflow_dispatch`, and before a release build. The arm64 payload already builds on the GitHub ARM64 runner (`build-native-payload.yml`). PR CI runs affected and goes full by itself when the selector escalates (shared foundation `contracts/**` except Markdown records, `tools/harness/**` except `adr_gaps.txt`, `conftest.py`, packaging/pytest config incl. `package.xml` and `_source_layout.py`, requirements pins, `test/architecture/**`, `test/known_failures.txt`, `.github/workflows/**`, a committed rename across folders or a removed Python module, or a file that maps to no module). `affected --run` on an escalated selection runs only the guards plus the suites mapped from the changed files (owning module, direct reverse dependents, referencing tests) and says the rest is on GitHub; `--full` requests the full selection; do not bypass the remote runner. A mapped affected run does not discharge the CI FULL requirement. `tools/land.py` does not land a FULL selection on that mapped run: it runs the lab full tier (`CI_FULL_MATRIX` unsharded, root `test/`, every registered module suite and the selection's own suites; `full_invocations`) on the lab PCs and lands only with 0 NEW. Later rounds of that landing, and a later `land.py` run while the branch adds nothing but merges of main to the FULL-tested commit, run only the selection of main's delta since the FULL-tested main (D-762 stage 0, D-803 6).

GitHub results (the full tier is never re-run locally to "check"):

The selector's `affected --run` calls pytest on the invoking host; it does not send work to a test PC. Never use it on this laptop. Print the selection or pass its JSON to the remote runner as shown below.

```bash
gh run list --branch <branch> -L 3                      # find the run for your push / PR
gh run watch <run-id> --exit-status                     # wait; non-zero exit when it fails
gh run view <run-id> --log-failed                       # only the failed steps' logs
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'
```

Reproduce only the failed matrix entry's pytest invocation on a remote test PC (the job name `test (<entry>)` maps to `CI_FULL_MATRIX` in `tools/harness/affected_tests.py`, or to the `affected-N` invocation printed by the `Test scope (D-436)` step). A local `main` that is not pushed has no CI evidence.

The direct pytest examples below are for CI or the selected Linux test PC. From this laptop use `python tools/remote/remote_pytest.py --log-dir $ROSY_SCRATCH/<name> -- <paths>` and compare the returned log with `test/known_failures.py`.

```bash
# Affected tier (D-436): tests of the touched modules + reverse dependents + tests naming the
# changed paths + the guard set; prints why each suite runs and when it escalates to FULL.
# Suites sharing a test basename (gateway vs sensing test_battery.py) come out as separate runs.
python tools/harness/rosy_harness.py affected --base origin/main --print
python tools/harness/rosy_harness.py affected --base origin/main --json | python tools/remote/remote_pytest.py --affected-json - --log-dir <external-log-dir>

# Compare every run-N.txt printed by the remote runner, not only run-1.txt.
# For each log: python test/known_failures.py <external-log-dir>/run-N.txt

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
- Dashboard screens are static files in `middleware/robot_ui/robot`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.

## Dependencies

### Internal

- `middleware/core/gateway` depends on `contracts/foundation`, `middleware/core/events`, `middleware/core/services`, `middleware/core/api`, and `contracts/ros_idl` (plus, at runtime, bringup/Nav2 topics).
- `deploy/robot/pinky_pro/Dockerfile` consumes source under `contracts/`, `middleware/`, and `shared/`. Its image-internal `/opt/rosy_ws/src/` destinations are build layout, not repository source holders; Docker/Compose are development/CI paths.
- `test/` imports `deploy/robot/pinky_pro/release` via `test/conftest.py` `sys.path`.

### External

- ROS 2 Jazzy, rclpy/rclcpp, Nav2, CycloneDDS
- FastAPI, uvicorn, pydantic, PyYAML, httpx, websockets
- Optional: slam_toolbox, sllidar_ros2, Gazebo (ros_gz), wiringPi I2C, ws2811, Dynamixel SDK

<!-- MANUAL: -->
