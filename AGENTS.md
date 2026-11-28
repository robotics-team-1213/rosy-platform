<!-- Parent: ../AGENTS.md -->

# ROSY

**Parent context:** `../AGENTS.md`
## Purpose

문서 편집은 [D-777](docs/adr/D-777-concise-human-agent-documentation.md)을 따른다.

ROSY Platform (ROS 2 Jazzy, first hardware Pinky Pro, Apache-2.0) connects world state, site orchestration, device execution and offline learning. CORE (`middleware/core/gateway`) owns the external API and the final Base command path; OMX keeps its joint/action owner; `operations/fleet` owns dispatch transactions, `operations/world` the MapPose projection. The legacy final publisher `control.safety_node` must not run beside CORE. Folder role does not establish writer authority, host placement or image closure (D-315); system map: README 「핵심 계약」.

## Subdirectories

Top-level folder roles: [folder responsibility guide](docs/reference/platform-folder-responsibilities.md) and `tools/harness/platform_parts.yaml`. `STATUS.md` is generated; edit progress/logs/ADRs instead.

## For AI Agents

### 모델 PC·AI PC·현장 PC 역할

- **모델 PC:** `learning/` 데이터·정답·학습·독립 평가·승격 증거. 운영 추론·Fleet 판단·장치 명령은 맡지 않는다.
- **AI PC:** 승인된 고정 버전 추론, 별도 환경의 오프라인 시뮬 학습(D-897). 후보·사실만 내고 Fleet 원장 쓰기·admission·ROS·`cmd_vel`·장치 Action 권한은 없다.
- **현장 PC:** `operations/fleet`가 사실 검증·admission·사람 확인으로 답을 고른다(Decision은 `operations/decision`).
- **로봇:** CORE가 장치 상태·안전을 다시 확인하고 최종 `/cmd_vel`을 단독 발행한다(D-516). 소스 경로로 실행 호스트를 추정하지 않는다(D-315).

시험 위치(D-527): 개발 PC는 원격 요청, CI는 계약·푸시 게이트, 모델 PC는 독립 평가·승격, AI PC는 고정 버전 스모크, 현장은 그림자·장치 수용.

### D-427 이후 공동 작업 규칙

소스 이전(D-427·D-429·D-430) 뒤에도 모든 세션이 지킨다.

1. **우선순위:** main CI 초록불 > 안전(D-430 공백) > 기능. 충돌하면 앞이 이긴다.
2. **main 체크아웃에서 작업하지 않는다.** 브랜치 전환·커밋은 `.worktrees/<topic>`에서만(아래 「같이 하는 깃」).
3. **구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다.** ADR 없이 새 최상위 폴더를 만들지 않는다.
4. **병합 경로는 [D-1055](docs/adr/D-1055-pr-merge-queue-only-merge-path-land-retired.md)다:** 공개 `main`에는 주제 PR 하나가 Merge Queue를 거쳐 merge commit으로만 들어간다.
5. **safety 태그 경로**(매니페스트 `concern: safety`, `safety_modules`, `safety_anchors`)를 바꾸거나 옮기는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5, CI가 검사).

### 같이 하는 깃

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다. 아래는 모든 세션이 늘 지킬 요약이다. 명령 전문·예외·도구 동작은 [`docs/reference/shared-checkout.md`](docs/reference/shared-checkout.md#같이-하는-깃)이고, 명령 카드는 `.claude/skills/rosy-land-on-main/SKILL.md`다. 워크트리 한도에 닿았을 때, 도구가 거절하거나 멈췄을 때, 처음 보는 상태(`landed-dirty`, `stale-history`, PR의 `DIRTY` 등)가 나왔을 때는 진행하지 말고 그 문서를 읽는다. 브랜치 이름과 남의 미커밋을 지우지 않는 이유는 [D-372](docs/adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에 자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치:** 저장소 루트에서 `git status --short --branch`와 `git worktree list`를 본 다음 `python tools/worktrees.py new <짧은이름> <type>/<topic>`을 실행한다. 맨손 `git worktree add`는 쓰지 않는다. `<type>`은 `feat`, `fix`, `refactor`, `docs`, `uiux` 가운데 하나, 한 브랜치에 한 주제다. 한도는 main 포함 15개다([슬롯 운영 규칙](docs/reference/shared-checkout.md#워크트리-한도와-슬롯-운영), D-886). 스크래치·로그는 저장소 밖 `$ROSY_SCRATCH`에 둔다.
2. **스테이징:** 이번 작업으로 만들거나 고친 경로만 `git add <path> ...`에 적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 커밋 전에 `git diff --cached --name-only`가 자신의 목록과 같아야 한다. 공유 체크아웃에서 `--amend`, `rebase`, `reset --hard`, `stash`는 쓰지 않는다. 자신이 쓰지 않은 경로는 그대로 두고, 그 파일 때문에 거절되면 거절 문구를 사용자에게 알린다.
3. **계약:** 제품 파일을 고치기 전에 README 「핵심 계약」과 아래 Working In This Directory, 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연다.
4. **ADR 번호:** 파일을 만들기 직전에 `python tools/harness/adr_reserve.py next "<주제>"`로 선점한다. ADR 파일과 Log 행은 한 커밋이고, 뒤에 `python tools/harness/rosy_harness.py lint`를 돌린다.
5. **시험:** pytest는 이 노트북에서 돌리지 않는다. `tools/remote/remote_pytest.py`로만 돌리고(D-584), 결과는 `python test/known_failures.py`로 비교한다. 시험 PC가 닿지 않으면 그 시험은 "확인 못 함"이고 착지와 푸시는 하지 않는다. 호스트 pytest 통과는 장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **제출과 push는 사용자가 말한 뒤에만 한다.** 브랜치 워크트리에서 `python tools/pr_land.py --evidence`로 내면 GitHub Merge Queue가 merge commit으로 병합한다(D-1055). PR이 `DIRTY`·`CONFLICTING`일 때만 `git merge origin/main`을 하고 증거를 다시 돌린다. `BEHIND`는 그대로 둔다. squash·rebase 병합과 force-push는 하지 않는다.

다른 PR이 최근 7일 안에 main에 넣은 줄을 지우거나 고치면 PR 본문에 `Replaces: #N (이유)`(또는 `Step-Back: none (이유)`)를 적는다(D-1067, [못 잡는 것](docs/reference/shared-checkout.md#다른-pr의-최근-작업을-되돌리지-않는다)).

멈추는 신호는 다음이다. `git add -A`로 다른 파일까지 넣으려 할 때, `test/known_failures.py` 없이 실패를 기존 실패로 부를 때, 조금 전에 비어 보였던 ADR 번호를 다시 보지 않고 쓸 때, 동료의 변경을 stash 했다가 머지 뒤에 되돌리려 할 때, amend가 새 커밋보다 빠르다고 여길 때.

### GitHub 게시와 두 에이전트 검토

작성 에이전트와 다른 읽기 전용 검토 에이전트가 base/head SHA를 지정해 검토하고, 최종 게시 head는 검토 head와 같아야 한다. 필수 검사와 종료 조건은 [PR 파이프라인](docs/reference/pr-pipeline.md)이 소유한다.

### Working In This Directory

- **모듈 하네스(D-61):** 모듈 폴더에서 작업하기 전 그 모듈의 `progress.md`·`index.md`를 읽는다. 바꾼 뒤 `logs.md`에 덧붙이고, 게이트가 바뀌었으면 `progress.md`를 덮어쓴 다음 저장소 루트에서 `python tools/harness/rosy_harness.py generate`를 돌린다.
- 새 소스 위치와 소유 영역은 `tools/harness/platform_parts.yaml`의 현재 root와 `d427_target`이 정본이다.
- Contracts: `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, `docs/reference/ROSY ADR Log.md`. Do not invent REST paths, modes or protocol fields missing from the API ref or `core_common.protocol.schemas`.
- External clients must not speak ROS. `core` is the only gateway (CORE SRS §1.3). Command Manager (`core_features.command`) is the only `cmd_vel` publisher (D-2).
- Single process: main thread rclpy `EventsExecutor` (D-1058; rollback `ROSY_CORE_EXECUTOR=threaded`), worker thread uvicorn+FastAPI (D-1), entry `ros2 run core core`. Do not split into two processes.
- `slam_toolbox` is optional: `ros_bridge` imports it inside try/except, never at module top; CI boots without it.
- Config merge order: `rosy_default.yaml` (contracts/foundation/config) → `~/.rosy/rosy.yaml` → `ROSY_CONFIG`.
- This repo is PUBLIC. Place new files by D-226: internal material, real device addresses/accounts and filled device config go in gitignored `private/` (`<robot-ip>` in public docs; lab SSH targets in `private/lab-hosts.json`); dated evidence goes to `$ROSY_SCRATCH/<topic>/` and the PR body; only a record a README/STATUS must link goes in `docs/validation/`, updating an existing one first (D-1090). Each area has a file-count cap in `test/architecture/test_file_count_budget.py`. A new secret kind needs its ignore rule and template in `test/architecture/test_document_placement.py` in the same change.
- Hardware profiles are YAML (`middleware/devices/pinky/profile/config/`, robot side `deploy/robot/pinky_pro/config/`).
- ROS package discovery uses the manifest `colcon_roots`. Do not reintroduce `rosy_*` or `pinky_*` package names (the CORE launch file keeps its legacy name `rosy_core.launch.py`).
- Dashboard screens are static files in `middleware/robot_ui/robot` served by FastAPI (`core_api_web`), not Node (D-23).

### Testing Requirements

Tiers are D-436. pytest never runs on this laptop (D-584): use `tools/remote/remote_pytest.py` and compare each `run-N.txt` with `test/known_failures.py`. Never use `rosy_harness.py affected --run` here (it runs pytest locally); pass its JSON to the remote runner. A mapped affected run does not discharge the CI FULL requirement. Commands and escalation: [developer-guide 「테스트와 CI」](docs/reference/developer-guide.md#테스트와-ci).

```bash
python tools/harness/rosy_harness.py affected --base origin/main --json | python tools/remote/remote_pytest.py --affected-json - --log-dir $ROSY_SCRATCH/<name>
python tools/harness/rosy_harness.py lint
```

### Common Patterns

- Requirement IDs (`CORE-001`, `SAF-005`, `PWR-001`) not section numbers (D-17).
- Namespaces + `frame_prefix` for multi-robot (D-4). Robot identity has **no default**:
  `ROS_DOMAIN_ID` = 40 + N and `ROSY_NAMESPACE` = `rosy_%02d` are derived from
  `ROSY_ROBOT_NUMBER` at install, and a missing identity stops the runtime (D-33).
  A default here is what once shipped every unit as 42/`rosy_01`.

<!-- MANUAL: -->
