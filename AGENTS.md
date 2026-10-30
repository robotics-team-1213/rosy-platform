<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-30 -->

# ROSY

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-30 (상세 절차를 정본 문서로 옮기고 이 파일은 늘 지킬 규칙과 포인터만 둠)

## Purpose

문서 편집은 [D-777](docs/adr/D-777-concise-human-agent-documentation.md)을 따른다. 공유·협업 문서는 독자의 작업 위치와 다음 행동부터 안내하고, 상세 규칙은 해당 기준 문서로 연결한다.

ROSY Platform connects observed world state, site orchestration, device execution, and offline learning/evaluation (ROS 2 Jazzy, first hardware Pinky Pro). CORE (`middleware/core/gateway`) owns the external API and final Base command path; OMX retains its joint/action owner. `operations/fleet` owns serving and dispatch transactions, `operations/world` the current sighting/operator-pin/odom MapPose projection. The legacy final publisher (`middleware/drive/runtime/safety_node.py`, installed as `control.safety_node`) must not run beside CORE. Source parts and holder decisions are in `tools/harness/platform_parts.yaml` and [the folder responsibility guide](docs/reference/platform-folder-responsibilities.md); the system map is README 「핵심 계약」. Folder role does not establish writer authority, host placement, or image closure (D-315). License: Apache-2.0.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `contracts/` | Shared ROS-free shapes, foundation and ROS IDL |
| `applications/` | Product application holders; Fleet UI and gateway composition in `applications/fleet` (D-822) |
| `middleware/` | CORE, device apps, perception, skills, execution, drivers, robot UI |
| `integrations/` | Robot, simulation, model and fieldbus adapters |
| `shared/` | Shared web components and operator copy |
| `operations/` | D-427 operations part: Fleet, Decision, World, site execution, cell/overhead, site devices |
| `learning/` | D-427 learning part: curation, registry, training, evaluation, Isaac env. Only `isaac_sim` reaches a device (native payload, D-427 Q8) |
| `deploy/` | Image build, signed release, Pi runtime |
| `tools/` | Developer commands. Not installed on the robot |
| `test/` | Host pytest for deploy/robot/pinky_pro/release/motor contracts |
| `docs/` | Governance: spec, API contract, ADR, plans, `solutions/` (past problems by category) |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |

Each folder's own `AGENTS.md` carries its files and rules. Root files: `README.md` (landing, core contracts), `CONCEPTS.md` (domain vocabulary), `PRODUCT.md`, `DESIGN.md` (visual guide, D-359 §8), `STATUS.md` (generated; edit progress/logs/ADRs instead), `env.sh`.

## For AI Agents

### 모델 PC·AI PC·현장 PC 역할

- **모델 PC:** `learning/`의 데이터·사람 정답·학습·독립 평가·승격 증거와 고정 모델 산출물을 맡는다. 운영 추론·Fleet 판단·장치 명령을 맡지 않는다.
- **AI PC:** 운영에서는 승인된 고정 버전 추론을 맡는다. [D-897](docs/adr/D-897-dual-host-offline-simulation-learning.md)에 따라 별도 환경의 오프라인 시뮬레이션 학습도 허용하며, 운영 추론과 GPU 시간을 분리한다. 막힘 VLM은 출처·시각이 붙은 정체 사실만, 숙고형 모델은 Mission/Task 후보만 낸다. Fleet 원장 쓰기·admission·ROS·`cmd_vel`·장치 Action 권한은 없다.
- **현장 PC:** `operations/fleet`가 사실을 검증하고 규칙·admission·사람 확인을 거쳐 답을 고른다. 기존 Decision 구현은 `operations/decision/src/rosy/decision`으로 분리했고 Fleet transaction과 배포를 유지한다. 후속 숙고형 모델 파이프라인의 구현 여부는 [설계](docs/plans/2026-10-08-decision-model-pipeline-design.md)를 본다.
- **로봇:** CORE가 장치 상태·안전을 다시 확인하고 최종 `/cmd_vel`을 단독 발행한다. 소스 경로로 실행 호스트를 추정하지 않는다(D-315). 이 역할 분담은 D-516이며, AI PC의 현장 경로는 아직 활성화되지 않았다.

시험 위치도 분리한다(D-527). 개발 PC는 원격 시험을 요청하고 CI는 코드 계약과 푸시 게이트, 모델 PC는 사람 정답 기반 Laya/Kev·VLM 독립 평가와 승격 receipt, AI PC는 승인 고정 버전의 적재·GPU·loopback 스모크와 watchdog, 현장 Fleet·CORE는 그림자/장치 수용을 맡는다. AI PC 합성 재생의 일치 수치를 L0 정확도로 쓰지 않는다. 실제 장치 주소·계정은 공개 문서 대신 gitignored `private/`에 둔다.

### D-427 이후 공동 작업 규칙 (2026-10-04, 이동 기간 2·5항 삭제)

소스 이전(D-427·D-429·D-430) 뒤에도 모든 세션이 지킨다. 이전 경로 `legacy`와 잔여 검사에는 한 release 유예를 둔다.

1. **우선순위:** main CI 초록불 > 안전(D-430 공백) > 기능. 충돌하면 앞이 이긴다.
2. **main 체크아웃에서 작업하지 않는다.** 모든 작업은 `.worktrees/<topic>`에서 한다. main 체크아웃에 커밋 안 된 변경을 남기면 다른 세션의 fast-forward와 pre-push가 막힌다. 순서는 아래 「같이 하는 깃」이다.
3. **구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다.** ADR 없이 새 최상위 폴더를 만들지 않는다.
4. **push 순서는 [D-868](docs/adr/D-868-local-main-first-merge-commit-publish.md)이 대체했다:** 모든 변경은 로컬 `main`에 먼저 착지하고, 공개 `main`에는 그 로컬 `main`을 merge commit PR로 올린다.
5. **safety 태그 경로**(매니페스트 `concern: safety`, `safety_modules`, `safety_anchors`)를 바꾸거나 옮기는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5, CI가 검사).

### 같이 하는 깃

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다. 아래는 모든 세션이 늘 지킬 요약이다. 명령 전문·예외·도구 동작은 [`docs/reference/shared-checkout.md`](docs/reference/shared-checkout.md#같이-하는-깃)이고, 명령 카드는 `.claude/skills/rosy-land-on-main/SKILL.md`다. 워크트리 한도에 닿았을 때, 도구가 거절하거나 멈췄을 때, 처음 보는 상태(`landed-dirty`, `stale-history`, `MAIN-RED` 등)가 나왔을 때는 진행하지 말고 그 문서를 읽는다. 브랜치 이름과 남의 미커밋을 지우지 않는 이유는 [D-372](docs/adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에 자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치:** 저장소 루트에서 `git status --short --branch`와 `git worktree list`를 본 다음 `python tools/worktrees.py new <짧은이름> <type>/<topic>`을 실행한다. 맨손 `git worktree add`는 쓰지 않는다. `<type>`은 `feat`, `fix`, `refactor`, `docs`, `uiux` 가운데 하나, 한 브랜치에 한 주제다. 한도는 main 포함 15개다([슬롯 운영 규칙](docs/reference/shared-checkout.md#워크트리-한도와-슬롯-운영), D-886). 스크래치·로그는 저장소 밖 `$ROSY_SCRATCH`에 둔다.
2. **스테이징:** 이번 작업으로 만들거나 고친 경로만 `git add <path> ...`에 적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 커밋 전에 `git diff --cached --name-only`가 자신의 목록과 같아야 한다. 공유 체크아웃에서 `--amend`, `rebase`, `reset --hard`, `stash`는 쓰지 않는다. 자신이 쓰지 않은 경로는 그대로 두고, 그 파일 때문에 거절되면 거절 문구를 사용자에게 알린다.
3. **계약:** 제품 파일을 고치기 전에 README 「핵심 계약」과 아래 Working In This Directory, 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연다.
4. **ADR 번호:** 파일을 만들기 직전에 `python tools/harness/adr_reserve.py next "<주제>"`로 선점한다. ADR 파일과 Log 행은 한 커밋이고, 뒤에 `python tools/harness/rosy_harness.py lint`를 돌린다.
5. **시험:** pytest는 이 노트북에서 돌리지 않는다. `tools/remote/remote_pytest.py`로만 돌리고(D-584), 결과는 `python test/known_failures.py`로 비교한다. 시험 PC가 닿지 않으면 그 시험은 "확인 못 함"이고 착지와 푸시는 하지 않는다. 호스트 pytest 통과는 장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **착지와 푸시는 사용자가 말한 뒤에만 한다.** 기본은 워크트리에서 `python tools/land_async.py --tests auto`다. 착지는 `--ff-only`만 하고, 거절되면 남의 파일을 치우지 않고 알린다. 모든 변경은 로컬 `main`에 먼저 착지하고 공개 `main`은 merge commit PR로만 올린다(D-868). squash·rebase 병합과 force-push는 하지 않는다.

멈추는 신호는 다음이다. `git add -A`로 다른 파일까지 넣으려 할 때, `test/known_failures.py` 없이 실패를 기존 실패로 부를 때, 조금 전에 비어 보였던 ADR 번호를 다시 보지 않고 쓸 때, 동료의 변경을 stash 했다가 머지 뒤에 되돌리려 할 때, amend가 새 커밋보다 빠르다고 여길 때.

### GitHub 게시와 두 에이전트 검토

공개 `main`은 로컬 `main`을 올린 PR의 merge commit 병합으로만 갱신한다(D-868). squash·rebase 병합은 쓰지 않는다. GitHub 사람 승인 수는 0, 필수 검사는 `ci-result`다(2026-10-16 사용자 결정). 작성 에이전트와 다른 읽기 전용 검토 에이전트가 base/head SHA를 지정해 검토하고, 게시 담당 한 명이 사용자에게 허용받은 범위의 push·PR·병합을 수행한다. 검토 결과·발견 사항 처리·시험 SHA·실제 CI 결과를 PR에 남긴다. 문서·생성물·merge 해결을 포함해 head가 바뀌면 변경 범위의 재검토와 새 SHA 검증이 필요하며 최종 게시 head는 검토 head와 같아야 한다. 절차와 종료 조건은 [PR 파이프라인](docs/reference/pr-pipeline.md)이 소유한다. `tools/land.py`는 로컬 착지 도구이며 공개 `main`에 직접 push하는 경로가 아니다. 공개 `main`은 ruleset이 직접 push를 막는다.

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

### Testing Requirements

Tiers are D-436. pytest never runs on this laptop (D-584): request affected and pre-push runs through `tools/remote/remote_pytest.py`, and compare every returned `run-N.txt` with `test/known_failures.py`. `rosy_harness.py affected --run` calls pytest on the invoking host, so never use it here; print the selection or pass its JSON to the remote runner. The full suite runs on GitHub Actions; a mapped affected run does not discharge the CI FULL requirement, and a local `main` ahead of `origin/main` has no CI evidence. Commands, the escalation list, the quick tier (owned by `tools/hooks/pre-push`) and `gh run` checks are in [developer-guide 「테스트와 CI」](docs/reference/developer-guide.md#테스트와-ci).

```bash
python tools/harness/rosy_harness.py affected --base origin/main --json | python tools/remote/remote_pytest.py --affected-json - --log-dir $ROSY_SCRATCH/<name>
python tools/harness/rosy_harness.py lint   # ADR duplicates, mojibake, append-only
```

### Common Patterns

- Requirement IDs (`CORE-001`, `SAF-005`, `PWR-001`) not section numbers (D-17).
- Python packages: ament_python (`setup.py` + `package.xml`). C++/URDF/Nav2/interfaces: ament_cmake.
- Namespaces + `frame_prefix` for multi-robot (D-4). Robot identity has **no default**:
  `ROS_DOMAIN_ID` = 40 + N and `ROSY_NAMESPACE` = `rosy_%02d` are derived from
  `ROSY_ROBOT_NUMBER` at install, and a missing identity stops the runtime (D-33).
  A default here is what once shipped every unit as 42/`rosy_01`.

<!-- MANUAL: -->
