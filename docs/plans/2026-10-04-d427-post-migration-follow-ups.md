# D-427 이동 뒤 남은 일

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 항목 하나를 한 브랜치·한 worktree에서 끝낸다. 우선순위 묶음(P1 → P5) 순서를 지키고, 묶음 안에서는 "선행"이 풀린 항목부터 한다.

**Status:** PLAN rev 1 (2026-10-04). 문서만이다. 기준은 2026-10-03 밤 상태다.

- `origin/main` `3eca84531`: wave 0, 1, 2(2b 생략), 3a 착지.
- `refactor/d427-w3b-site-apps` `a169447f3`: 3b 준비 완료, 미착지.
- `refactor/d427-bulk` `965c7874a`: 3b 위에 `tools/harness/d427_move.py`(`8767146af`)와 3c 일괄 이동. 4a–4e는 같은 브랜치에서 진행 중.
- wave 5: 시작 전.

**Goal:** [D-427 이동 계획](2026-10-03-d427-source-migration.md)의 wave 3b–4e가 main에 들어간 뒤 남는 일을 우선순위대로 한곳에 모은다. ADR 내용은 다시 적지 않는다. 항목마다 실행할 사람과 끝났다는 증거만 적는다.

## 읽는 법

항목마다 다음 칸을 둔다.

- **역할:** `executor`(구현), `code-reviewer`·`verifier`(독립 리뷰. 작성 세션이 아니어야 한다), `architect`·`planner`(ADR·설계 초안), `release`(릴리스 세션, `rosy-release-push` 스킬), `operator`(사용자. 실물·사이트 PC 작업).
- **선행:** 시작 조건.
- **대상:** 파일과 ADR.
- **게이트:** 완료 증거. 호스트 pytest는 장치·실주행 수용이 아니다.
- **크기:** S(반나절 이하), M(하루 안팎), L(여러 날 또는 ADR 승인 대기).
- **safety:** `예`이면 그 커밋에 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5). 판정은 `python tools/harness/safety_review.py origin/main HEAD`가 한다. 표에 `아니오`라도 이 명령이 요구하면 따른다.

## 공통 규칙

1. 모든 작업은 `rosy-platform/.worktrees/<topic>`에서 `git worktree add --relative-paths`로 한다. main checkout에서 일하지 않는다. bare `git stash`, `git add -A`, amend는 쓰지 않는다.
2. push 전 순서는 루트 `AGENTS.md` "D-427 이동 기간 규칙" 4항(fetch → rebase → `rosy_harness.py generate` → pre-push)을 따른다. force-push 하지 않는다.
3. 역사 문서(`docs/adr`, `docs/plans`, `docs/validation`, 모든 `logs.md`·`progress.md`의 과거 항목)는 옛 경로를 그대로 둔다(D-226).
4. 게이트는 커밋한 SHA의 깨끗한 checkout에서 돌린다([verify-what-you-ship](../solutions/workflow-issues/verify-what-you-ship-the-working-tree-is-not-the-commit.md)).
5. Windows 호스트에서는 `python`을 쓴다. ROS 게이트는 WSL Ubuntu에서 한다.
6. 실물 로봇은 공유 자원이다. 동작을 일으키는 작업은 사용자 승인 뒤에만 한다.

## 요약

| ID | 항목 | 역할 | 크기 | safety | 선행 |
|---|---|---|---|---|---|
| P1-1 | wave 5 정리 | executor | M | 판정에 따름 | 4e 착지 |
| P1-2 | push와 CI ARM64 payload·SD 이미지 동등성 증거 | release | M | 아니오 | wave별 push |
| P1-3 | safety 경로 이동의 독립 rename 리뷰 | code-reviewer | M | 예(리뷰 자체) | 3b·3c·4c·4d 착지 |
| P1-4 | AGENTS 이동 기간 규칙 2·5항 삭제 | executor | S | 아니오 | P1-1 |
| P1-5 | 사이트 PC model-watch 재설치 | operator | S | 아니오 | wave 1 착지(완료) |
| P1-6 | peer 브랜치 rebase 공지 | planner | S | 브랜치별 | wave별 착지 |
| P1-7 | 다음 릴리스로 로봇 배포 | release + operator | M | 아니오 | P1-1, P1-2 |
| P2-1 | `fleet.ai` → `rosy.decision` carve | executor + architect | L | 판정에 따름 | 3c 착지 |
| P2-2 | Console web → `operations/ui/console` | executor | M | 아니오 | D-425 Task 6 |
| P2-3 | gz_sim `launch`·`scripts` 분리 | architect → executor | M | 아니오 | 4c 착지, 설계 결정 |
| P2-4 | signal observer 중첩 해소 | architect → executor | S | 아니오 | 3b 착지 |
| P2-5 | `learning/training/perception` 분리(Q7) | executor | M | 아니오 | P2-6 |
| P2-6 | 2b 학습 계약 스키마 | architect → executor | L | 아니오 | D-427 후속 2 설계 승인 |
| P3-1 | 층 1 물리 E-stop 회로 증거·실측 | operator + verifier | M | 아니오(증거) | 없음 |
| P3-2 | 층 3 D-400 그림자 → 집행 | executor + verifier | L | 예 | 유휴 호스트 |
| P3-3 | 층 4 엔벌로프 스킬 계약 ADR | architect | M | ADR(구현 시 예) | 없음 |
| P3-4 | 층 5 OMX Arbiter 표·MANUAL 선점 | architect | L | ADR(구현 시 예) | P4-1과 하나 |
| P3-5 | 층 7 확인(완료) | verifier | S | 아니오 | 없음 |
| P3-6 | `KNOWN_SAFETY_VIOLATIONS` 축소(Fleet 정지 경로 carve) | executor + code-reviewer | L | 예 | 3c 착지 |
| P3-7 | 문서화된 시험 빈틈 | executor | M | 판정에 따름 | 4d 착지 |
| P3-8 | `feat/d400-plan2-rosim` 착지 trailer | 브랜치 주인 + code-reviewer | S | 예 | P3-2 G-sim |
| P3-9 | robot-literal backlog 후속 | executor + code-reviewer | M | 일부 예 | 4d·4e 착지 |
| P4-1 | Motion Intent + DeviceControlPort ADR | architect | L | ADR | 없음 |
| P4-2 | `rosy.site-device/1` ADR | architect | M | ADR | 없음 |
| P4-3 | ER2 사이트 장치 후보 제안 ADR | architect | M | 아니오 | P4-2, P2-1 |
| P4-4 | PLC 인터록 ADR | architect | M | ADR | P4-2 |
| P4-5 | 로컬 VLA 배치 ADR | architect | M | ADR | P3-3 |
| P4-6 | 남은 `KNOWN_VIOLATIONS` 은퇴 | executor | 항목별 | 아니오 | 표 참고 |
| P5-1 | ADR Log·docs index 정합성 | executor | S | 아니오 | 없음 |
| P5-2 | 옛 경로를 쓰는 살아 있는 문서 | executor | S | 아니오 | P1-1, 사용자 결정 |
| P5-3 | `test_jpeg_relay` Windows flake | executor | S | 아니오 | 없음 |
| P5-4 | D-435 수용 판단 | architect + critic | M | 아니오 | P1-1 |

## P1. 이동 마무리

### P1-1 wave 5 정리

- **역할:** executor. **크기:** M. **safety:** `safety_review.py` 판정(매니페스트의 safety root에서 `legacy`를 지우는 커밋은 safety 항목을 바꾼다).
- **선행:** 4e까지 main 착지. 매니페스트 pending root 0개:
  ```bash
  python -c "import yaml;print([r['path'] for r in yaml.safe_load(open('tools/harness/platform_parts.yaml',encoding='utf-8'))['roots'] if r['path']!=r['d427_target'] and not r.get('deferred')])"
  ```
  출력이 `[]`이어야 한다.
- **대상:** 빈 `src/`·`modules/`·`apps/`와 그 폴더 노트(`src/AGENTS.md`, `src/sim/AGENTS.md` 등), 매니페스트 `colcon_roots`에서 `src` 제거, 루트 `AGENTS.md` Layout, `test/test_robot_literals.py`.
- **단계:**
  1. `git ls-files src modules apps`가 폴더 노트만 남았는지 확인하고 지운다.
  2. `colcon_roots`에서 `src`를 뺀다. `build-native-payload.sh`·SD 이미지 스크립트는 wave 0부터 목록을 읽으므로 코드 변경이 없어야 한다. 바뀌면 그 자체가 결함이다.
  3. `test/test_robot_literals.py`는 아직 `ROOT / "src"`를 훑는다(3b 뒤 `operations`만 더했다). 매니페스트 파트 root를 훑게 바꾸고, backlog 키를 저장소 상대 경로로 통일하고, `HOME_PREFIXES`를 Pinky 제품 목표(`middleware/apps/device/pinky/`, `middleware/drivers/` 중 Pinky 보드 패키지)로 바꾸고, 검사 파일 수 > 0 단정을 넣는다([folder-move-widens](../solutions/workflow-issues/folder-move-widens-path-scoped-contract-tests-2026-09-25.md)).
  4. `git grep -n -E 'ROOT / "src"|"src" /' -- test tools deploy`로 `src`를 직접 훑는 나머지 시험을 찾아 같은 방식으로 고친다.
  5. 별도 커밋, **한 release 뒤**: 매니페스트 `legacy` 필드와 `test_moved_roots_leave_nothing_behind`를 지운다(이동 계획 Wave 5). 그 사이 rebase되는 브랜치를 잡기 위한 유예다. `deferred` root는 `legacy`를 지워도 남는다.
  6. 저장소 밖 umbrella `F:\Dev\Control\Robot\Rosy\AGENTS.md`의 "Live package `control` is ..."·"Fleet is ..." 줄은 커밋 대상이 아니다. 사용자에게 수정을 알린다.
- **게이트:** `python -m pytest test/architecture -q`, `python tools/harness/rosy_harness.py lint`(0 errors), 루트 `AGENTS.md`의 pytest 두 줄(새 경로), `python -m pytest test/test_robot_literals.py -q`, WSL `colcon list --base-paths <colcon_roots> --names-only`가 27개 이름 기준과 같음. ARM64 payload·SD 1회는 P1-2.

### P1-2 push와 CI ARM64 payload·SD 이미지 동등성 증거

- **역할:** release. **크기:** M. **safety:** 아니오.
- **선행:** 각 image wave(4b, 4c, 4d, 4e)와 wave 5가 push됨.
- **대상:** `.github/workflows/build-native-payload.yml`, `.github/workflows/build-pinky-image.yml`, 새 폴더 `docs/validation/d427-source-migration/`.
- **사실:** 2026-10-03 기준 `origin/main`에 `docs/validation/d427-source-migration/`이 없다. 이동 계획 wave 0 8번(ARM64 payload 1회, SD 1회)의 증거도 저장소에 없다. 첫 실행이 wave 0 기준선을 겸하거나, 기준선을 `NOT_RUN`으로 적는다.
- **단계:**
  1. 비교 기준 = 직전 release의 `rosy-packages.txt`와 SD 이미지 패키지 목록·rosdep 범위. release 번호와 SHA를 적는다.
  2. wave별로 두 workflow를 `gh workflow run`으로 돌리고 artifact를 X:\DevTemp\rosy-d427\parity\<wave>\에 받는다.
  3. diff를 `docs/validation/d427-source-migration/<wave>.md`에 남긴다: 커밋 SHA, run URL, 이름 차이(0건이어야 함), 설치 파일 차이(의도한 것만. 예: 1c의 `omx_adapter.lerobot_export`).
  4. 돌리지 못한 것은 `NOT_RUN`으로 적고 `ARTIFACT_EQUIVALENT`를 주장하지 않는다.
- **게이트:** wave마다 위 파일이 있고 이름 차이 0건. CI 녹색.

### P1-3 safety 경로 이동의 독립 rename 리뷰

- **역할:** code-reviewer 또는 verifier. 이동 커밋을 만든 세션이 아니어야 한다. **크기:** M. **safety:** 예. 이 리뷰가 trailer의 근거다.
- **선행:** 대상 커밋이 main에 있다. 3c 일괄 커밋(`965c7874a`)의 trailer는 "independent rename review pending"이라 적혀 있다. pushed 커밋은 고치지 않으므로 리뷰 기록이 그 trailer를 채운다.
- **대상:** D-430 §5와 이동 계획 "공통 절차" 6번의 목록. 3b `operations/site_devices/{dock,signal}/firmware`, 3c `cancel_all*.py`·`dispatch_admission.py`·`local_stop_transport.py`·`console.py`·`task_dispatch_routes.py`, 4c `omx_adapter`의 `command_owner.py`·`local_stop.py`·`action_api.py`, 4d `core_features/safety`·`command/{manager,arbitration}.py`·`line_follow/{body_stop,clearance}.py`·`core/bridge/cmd_vel.py`·`core/fleet_loss_wiring.py`·`core_api_web/api/v1/safety.py`·`core_common/robot_body.py`.
- **단계:**
  1. `git log --format='%H %s' --grep='^Safety-Review:' origin/main`에서 이동 커밋을 고른다.
  2. 커밋마다 `git show -M --summary --format= <sha> | grep rename`과 `git diff -M <sha>^ <sha> -- <safety 새 경로>`로, safety 파일의 변경이 rename(유사도 100%) 또는 `parents[N]`·저장소 경로·import 경로 수정뿐인지 본다. 동작 변경이 있으면 결함으로 보고한다.
  3. 매니페스트 `safety_modules`·`safety_anchors`·`concern: safety` root가 새 경로를 가리키고 빠진 항목이 없는지 본다(이전 커밋 매니페스트와 집합 비교).
  4. `KNOWN_SAFETY_VIOLATIONS` 키가 경로만 바뀌고 개수가 늘지 않았는지 본다.
  5. 결과를 `docs/validation/d427-source-migration/safety-rename-review.md`에 커밋 SHA별 판정으로 남긴다.
- **게이트:** `python -m pytest test/architecture/test_safety_separation.py -q`, `python -m pytest middleware/core/services/test -q -k safety`(4d 뒤 경로), Fleet `test_dispatch_stop_latch.py`·`test_cancel_all.py`, OMX `local_stop`·`command_owner` 시험. 리뷰 문서 커밋에 `Safety-Review: <리뷰어 레인> docs/validation/d427-source-migration/safety-rename-review.md` trailer.

### P1-4 AGENTS 이동 기간 규칙 2·5항 삭제

- **역할:** executor. **크기:** S. **safety:** 아니오.
- **선행:** P1-1 1–4단계 착지.
- **대상:** 루트 `AGENTS.md` "D-427 이동 기간 규칙 (2026-10-03, 사용자 결정 — 이동 완료 시 2·5항 삭제)".
- **단계:** 2항(경로 동결)과 5항(새 코드는 목표 경로에만)을 지우고 나머지를 다시 번호 매긴다. 제목의 "이동 완료 시 2·5항 삭제"를 삭제 날짜로 바꾼다. 1항 우선순위의 "폴더 이동"은 의미가 없어진다. 남길지는 사용자에게 묻는다(열린 질문 1). 대신 새 코드 위치는 매니페스트 `d427_target`이 정본이라는 한 줄을 Working In This Directory에 둔다.
- **게이트:** `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_harness_contracts.py -q`.

### P1-5 사이트 PC model-watch 재설치

- **역할:** operator(사이트 PC 접근). **크기:** S. **safety:** 아니오.
- **선행:** wave 1의 1-pre가 main에 있다(`deploy/site/install-model-watch.sh`가 `/opt/rosy/model-watch/bin/rosy-model-watch` wrapper를 설치한다). 사이트 PC 소스 사본을 그 뒤 main으로 갱신.
- **대상:** `deploy/site/install-model-watch.sh`, `deploy/site/rosy-model-watch`, `deploy/site/rosy-model-watch.service`, `deploy/site/README.md`.
- **단계:** 사이트 PC에서 설치 스크립트를 한 번 다시 돌린다. `ROSY_MODEL_WATCH_SRC=<소스 사본> /opt/rosy/model-watch/bin/rosy-model-watch locate`가 `learning/training/perception/model/watch.py`를 가리키는지 본다.
- **게이트:** `systemctl status rosy-model-watch.timer`가 active, 다음 timer 실행의 journal에 오류 없음. 결과를 `docs/validation/d427-source-migration/site-model-watch.md`에 적는다. 사이트 PC에 접근할 수 없으면 `NOT_RUN`.

### P1-6 peer 브랜치 rebase 공지

- **역할:** planner(공지), 브랜치 주인(rebase). **크기:** S. **safety:** 브랜치가 safety 경로를 바꾸면 rebase 뒤 커밋에 trailer.
- **선행:** 해당 wave가 main에 있다. 공지는 wave 착지 때마다 한다.
- **rebase 방법**(브랜치 주인, 그 브랜치의 worktree에서):
  ```bash
  git fetch origin
  git status --short                       # 비어 있어야 한다. WIP는 먼저 커밋한다(bare stash 금지)
  git branch backup/<branch>-pre-d427 HEAD # 되돌릴 자리
  git -c merge.renameLimit=100000 rebase origin/main
  # rename을 못 찾은 충돌: git rebase --abort 후
  # git -c merge.renameLimit=100000 rebase -X find-renames=40% origin/main
  # 옛 경로에 새 파일이 생겼으면 git mv <old> <new> 후 git rebase --continue
  python -m pytest test/architecture -q    # test_moved_roots_leave_nothing_behind가 옛 경로 잔재를 잡는다
  python tools/harness/rosy_harness.py lint
  python tools/harness/safety_review.py origin/main HEAD --warn-only
  ```
  커밋이 많으면 `git rebase --rebase-merges`를 쓰지 말고 커밋을 정리한 뒤 rebase한다. 옛 경로 문자열은 브랜치 주인이 고친다.
- **대상 브랜치**(2026-10-03 기준, `git branch --no-merged origin/main`에서 이동 root를 바꾸는 브랜치. 괄호는 그 root에서 바뀐 파일 수, `git log --no-merges origin/main..<branch>`로 셌으므로 이미 main에 같은 패치가 있는 커밋도 섞였을 수 있다):

  | 브랜치 | 커밋 | 이동 root (wave) |
  |---|---|---|
  | `feat/d400-plan2-rosim` | 26 | `src/hmi/dashboard`(5)·`web_common`(2) [4b], `src/sim/gz_sim`(9)·`launch`(7) [4c], `src/runtime/gateway`(16)·`services`(9)·`core_features/safety`(2)·`api_web`(4) [4d], `src/runtime/sensing`(14) [4e]. **safety** |
  | `feat/gz-learned-lane-drive` | 21 | `src/sim/description`(2)·`gz_sim`(1)·`launch`(1) [4c], `gateway`(7)·`services`(7)·`foundation`(1) [4d], `sensing`(14) [4e] |
  | `feat/overhead-markerless-tracking` | 19 | `src/site/vision`(18) [3b], `src/site/fleet`(17)·`server/web`(10) [3c], `foundation`(2) [4d] |
  | `feat/common-discovery-link` | 10 | `firmware/dock`(3)·`firmware/signal`(3)·`src/site/cam`(28) [3b], `src/site/fleet`(10) [3c], `src/hmi/pilot`(14)·`web_common`(7)·`dashboard`(2) [4b], `foundation`(12)·`api_web`(7)·`gateway`(9)·`services`(6) [4d]. **safety**(펌웨어) |
  | `feat/d414-fleet-cancel-all` | 12 | `src/site/fleet`(14)·`server/web`(4) [3c], `api_web`(1) [4d]. **safety**(cancel_all) |
  | `feat/d415-saf003-fleet-loss` | 10 | `src/site/fleet`(2) [3c], `foundation`(3)·`api_web`(5)·`gateway`(8)·`services`(7)·`core_features/safety`(2) [4d]. **safety** |
  | `docs/d416-pinky-device-actions` | 12 | `src/site/fleet`(9)·`server/web`(3) [3c], `foundation`(1)·`api_web`(3)·`gateway`(3)·`services`(8) [4d] |
  | `fix/d407-console-link-and-event-fields` | 8 | `src/site/fleet`(9)·`server/web`(2) [3c], `foundation`(1)·`api_web`(3)·`gateway`(3)·`services`(8) [4d] |
  | `feat/line-follow-robot-overlay` | 6 | `src/runtime/sensing`(10) [4e] |
  | `fix/s21-nsd-callback-lifetime` | 1 | `src/site/cam`(6) [3b] |
  | `fix/audit-test-clock` | 1 | `src/runtime/events`(3) [4d] |
  | `refactor/d362-p0-1-fleet-app-routes` | 2 | `src/site/fleet`(10) [3c] |
  | `refactor/d362-p0-2-sensing-calibration-sequence` | 2 | `src/runtime/sensing`(9) [4e] |
  | `refactor/d362-p1-dashboard-split` | 2 | `src/hmi/dashboard`(11) [4b], `api_web`(1)·`gateway`(1) [4d] |
  | `docs/d395-plan` | 2 | `src/hmi/dashboard`(6) [4b] |
  | `codex/pinky-integrated-current` | 1 | `src/sim/gz_sim`(11)·`launch`(4)·`scripts`(5) [4c] |
  | `fix/hardware-runtime-truth` | 1 | `src/sim/gz_sim/scripts`(1) [4c] |
  | tag만 있는 브랜치: `feat/d355-goal-evidence-verifier`, `feat/camera-preview-rectification`, `docs/ui-boundaries-d322`, `refactor/web-transport`, `release/floor-g4-minimal`, `uiux/mobile-acceptance` | 1–8 | fleet·web [3c], dashboard·web_common [4b], foundation·api_web [4d]. `archive/<branch>` tag가 있으므로 주인이 "보관"을 확인하면 rebase하지 않는다 |
  | `quarantine/auto-state-fixtures-20261003` | 4 | 모든 이동 root(트리 전체 사본). rebase 대상이 아니다. 주인에게 보관·삭제를 묻는다 |

  이동 root를 건드리지 않는 미병합 브랜치(`feat/ci-affected-tests`, `feat/site-candidate-ci`, `integrate/d437-runlog`, `feat/role-surfaces-s1`, `fix/sd-*`, `refactor/d171-*` 등)는 공지만 하고 확인은 생략한다.
- **게이트:** 브랜치별 응답(착지·rebase 예정·보관)을 공지 스레드에 받는다. rebase된 브랜치는 위 세 명령이 녹색.

### P1-7 다음 릴리스로 로봇 배포

- **역할:** release(빌드·서명·게시), operator(로봇 확인). **크기:** M. **safety:** 아니오(소스 변경 없음). 로봇 작업은 사용자 승인.
- **선행:** P1-1, P1-2의 4b–4e·wave 5 증거가 이름 차이 0건. 이동과 release를 섞지 않는다(D-191 취지): 이동 커밋만 담은 release를 따로 만들지 말고 다음 정규 release에 실린다.
- **대상:** `deploy/robot/pinky_pro/release/`, D-191, D-412 auto-update.
- **단계:** 정규 release를 cut한다. release note에 "D-427 소스 이동 포함, 설치 경로 불변"과 P1-2 증거 링크를 적는다. auto-update가 켜진 로봇이 새 payload를 적용한 뒤 readback을 확인한다.
- **게이트:** release receipt, 각 로봇의 payload 버전 readback과 `CORE_READY`. 실주행 G 단계는 이 항목의 출구가 아니다.

## P2. 미룬 carve (Q2)

### P2-1 `fleet.ai` → `rosy.decision` (D-429 §5)

- **역할:** architect(포트 모양), executor(이동), code-reviewer. **크기:** L. **safety:** `safety_review.py` 판정. proposal store의 후보 fence(D-358 §4)는 D-430 층 6이므로 리뷰어가 fence 시험을 확인한다.
- **선행:** 3c 착지. 착지한 3c는 이 carve를 하지 않았다(`965c7874a` 메시지: "the fleet.ai carve to rosy.decision is not done here"). carve **직전에** 겹치는 브랜치를 다시 센다:
  ```bash
  for b in $(git branch --no-merged origin/main --format='%(refname:short)'); do
    n=$(git log --no-merges --format= --name-only origin/main..$b -- operations/fleet/fleet/ai src/site/fleet/fleet/ai operations/fleet/fleet/server/proposal_store.py src/site/fleet/fleet/server/proposal_store.py | sort -u | wc -l)
    [ "$n" -gt 0 ] && echo "$b $n"
  done
  ```
  하나라도 있으면 P1-6 공지로 착지·보관을 먼저 받는다.
- **대상:** `operations/fleet/fleet/ai/**`, `operations/fleet/fleet/server/proposal_store.py`, 새 `operations/decision/`(wheel, 배포 이름은 열린 질문 2), 매니페스트(`deferred` 제거, `rosy.decision.api` root에 `api: true`), `ci.yml` wheel 목록, `deploy/site/Dockerfile.fleet`, D-429 §5, D-358 §4.
- **단계:**
  1. `ModelToolCall`·`ModelToolResult`·`ProposalConflict`·`ProposalRejected`와 저장 포트 Protocol을 `rosy.decision.api`에 둔다. proposal store가 그것을 import한다. 역방향 import는 없다.
  2. dispatch 구현은 Fleet이 주입한 저장 포트로 proposal store를 부른다. D-358 §4 트랜잭션(후보 삽입 + stop·세대·watermark 확인)은 proposal store 안에 그대로 둔다. `rosy.decision`은 트랜잭션을 열지 않는다.
  3. 한 커밋 `refactor(d427): carve fleet.ai to rosy.decision`에서 `git mv`, 모든 호출자·시험 import 변경. re-export shim은 두지 않는다.
  4. ROS 이름, HTTP 경로, wire, 저장 스키마, 모델 도구 이름은 바꾸지 않는다.
- **게이트:** `git grep -n -E "\bfleet\.ai\b|from fleet import ai" -- ':!docs/adr' ':!docs/plans' ':!**/logs.md' ':!**/progress.md'` 0건, `python -m pytest operations/fleet/test -q`(3c 착지 때 기준 수와 비교), `python -m pytest operations/decision -q`, `test_model_tool_adapter_conformance.py`, ER2 후보 fence 시험(`test_dispatch_stop_latch.py` 포함), Fleet 이미지 빌드와 fake lifespan, `test/architecture`, lint, WSL `colcon list` 이름 동일.

### P2-2 Console web → `operations/ui/console` (D-425 Task 9)

- **역할:** executor. **크기:** M. **safety:** 아니오.
- **선행:** D-425 Task 6(설치·정적 서빙 계약) 착지. 3c 착지.
- **대상:** `operations/fleet/fleet/server/web`, [D-425 계획](2026-10-03-app-ownership-shared-transport-and-layout-migration.md) Task 9, 매니페스트 root(`deferred: D-425 Task 9` 제거).
- **주의:** D-425 계획 Task 9는 목적지를 `ui/console`로 적는다. 매니페스트 `d427_target`은 `operations/ui/console`이다. 매니페스트를 따른다(D-427이 나중 결정). `web/__init__.py` wheel scaffold와 설치 wrapper는 Task 9 본문대로 남긴다.
- **게이트:** Fleet 브라우저 suite(기존 실패 목록과 비교), Task 6 설치 시험, Fleet 이미지 빌드 후 Console 정적 자산 응답, `test/architecture`, lint.

### P2-3 gz_sim `launch` → `middleware/apps/device/sim`, `scripts` → `tools/sim`

- **역할:** architect(설치 방식 결정), executor. **크기:** M. **safety:** 아니오.
- **선행:** 4c 착지. `codex/pinky-integrated-current`, `feat/d400-plan2-rosim`, `feat/gz-learned-lane-drive`, `fix/hardware-runtime-truth`가 착지·보관됨.
- **설계 결정(열린 질문 3):** `ros2 launch gz_sim <file>`과 `share/gz_sim/launch` 경로는 D-231로 고정이다. launch 파일이 패키지 폴더 밖으로 나가면 `gz_sim`의 CMake가 패키지 밖 경로를 install하거나, 새 ament 패키지가 필요하다(새 패키지 이름은 새 ROS 이름이다). 결정 전에는 옮기지 않는다.
- **대상:** `integrations/simulation/gazebo/{launch,scripts}`, 매니페스트의 두 `deferred: gz_sim split follow-up` root, 매니페스트 `tools/sim` root(scripts가 들어오면 `src/sim/gz_sim/scripts` root를 지워 중복 목표를 없앤다), CI의 gz_sim `COLCON_IGNORE` 처리.
- **게이트:** WSL `colcon build --packages-select gz_sim`과 `ros2 launch gz_sim` 대상 파일 목록이 이전과 같음, Gazebo 2-pinky 기동 스모크, `test/architecture`(목표 중복 0), lint.

### P2-4 signal observer 중첩 해소

- **역할:** architect(위치), executor. **크기:** S. **safety:** 아니오(`concern: other`).
- **선행:** 3b 착지.
- **사실:** 3b 뒤 `operations/vision/signal_observer`가 ROS 패키지 `rosy_vision` 폴더(`operations/vision`, `setup.py`의 `find_packages(exclude=["test"])`) 안에 있다. `__init__.py`가 없어 wheel에 들지 않지만, 패키지 폴더 안에 다른 root가 있고 `test/conftest.py`가 두 개 겹친다. 설치는 `/opt/rosy/signal/observer/`(service `ExecStart`)이며 바꾸지 않는다.
- **단계:** 위치를 정한다(예: `operations/vision_observers/signal` 또는 `operations/site_devices/signal/observer`. D-429 §2와 D-163 읽기 전용 평면을 보고 architect가 고르고 사용자 확인, 열린 질문 4). 매니페스트 `d427_target`을 함께 바꾸고 `git mv`. 시험 `test_package_targets_are_leaf_unique`를 패키지 폴더 안에 비패키지 root가 있는 경우까지 넓힐지 함께 정한다.
- **게이트:** `python -m pytest operations/vision/test -q`와 observer 시험 각각, WSL `colcon build --packages-select rosy_vision` 설치 파일 목록이 이전과 같음, `test/architecture`, lint.

### P2-5 `learning/training/perception` 분리 (Q7)

- **역할:** executor. **크기:** M. **safety:** 아니오.
- **선행:** P2-6. 이동 계획 Q7은 "통째로 옮기고 2b 뒤에 나눈다".
- **대상:** `learning/training/perception`, `tools/perception_prototype`, 매니페스트, `KNOWN_VIOLATIONS`의 `learning/training/perception → middleware/perception`.
- **단계:** 학습(training)·큐레이션(curation)·평가로 나눈다. 장치 인식 코드를 재생에 쓰는 import는 남긴다. 그 edge를 D-427 §2의 재생 전용 예외로 둘지 별도 결정한다(열린 질문 5). 결정 전에는 `KNOWN_VIOLATIONS`에 그대로 둔다.
- **게이트:** `python -m pytest learning -q`, `test/architecture`, lint, model-watch wrapper `locate`가 새 위치를 찾음(P1-5 wrapper를 고쳐야 하면 사이트 PC 재설치가 다시 필요하다).

### P2-6 2b 학습 계약: Episode, DatasetManifest, PolicyArtifact (D-427 후속 2)

- **역할:** architect(설계 문서 또는 ADR), executor(구현). **크기:** L. **safety:** 아니오. 단 PolicyArtifact가 장치 실행 조건을 담으면 D-430 불변식 4와 대조한다.
- **선행:** 설계 승인(사용자). 2a(`rosy.contracts.skill`) 착지(완료).
- **대상:** 새 `contracts/learning`(import `rosy.contracts.learning`), `learning/curation/`의 변환기 세 개(`rosy.recording.session/1`, D-411 Pilot 녹화, `rosy.omx-demonstration.v1` → Episode profile), `control.sensing.perception.learned.manifest`의 `rosy.perception.model/1` → PolicyArtifact 인식 profile(원래 위치는 re-export).
- **게이트:** 계약 시험(스키마 round-trip, 세 변환기 fixture), `KNOWN_VIOLATIONS`에서 `learning/curation/omx → middleware/apps/device/omx/adapter` 삭제(5 → 4건), CI wheel 빌드·설치, `test/architecture`, lint.

## P3. 안전 빈틈 (D-430 §2)

### P3-1 층 1: 물리 E-stop 회로 증거와 실측 (D-427 §5 선행 조건 6)

- **역할:** operator(실물), verifier(증거 판정). **크기:** M. **safety:** 코드 없음. D-430 층 1 상태 갱신은 ADR 문서 수정이다.
- **선행:** 없음. 사용자 승인과 사람 입회.
- **단계:**
  1. Pinky·OMX의 E-stop 배선을 확인한다: 스위치가 모터 전원 또는 drive enable을 소프트웨어와 무관하게 끊는지. 사진과 회로 메모.
  2. 회로가 없으면 그 사실을 기록하고 하드웨어 추가안을 사용자에게 올린다. 이 경우 실측은 하지 않는다.
  3. 회로가 있으면: CORE를 멈춘 상태(소프트웨어 무응답)와 정상 주행 중 각각 E-stop을 눌러 정지 시간·거리를 잰다. 영상과 타임스탬프.
- **게이트:** `docs/validation/<date>-physical-estop/`에 로봇별 결과. D-430 §2 층 1의 "현재 상태" 칸을 증거 링크로 갱신(독립 리뷰). HTTP 응답·소프트 E-stop은 증거가 아니다(D-298, D-369 §5).

### P3-2 층 3: D-400 그림자 → 집행, Nav2·teleop 몸 기준 정지

- **역할:** 브랜치 주인(executor), verifier. **크기:** L. **safety:** 예.
- **선행:** 유휴 호스트에서 사용자가 고른 시간. `feat/d400-plan2-rosim`이 4b–4e 이동 뒤로 rebase됨(P1-6).
- **대상:** `feat/d400-plan2-rosim`(계획 2), [D-400 그림자 계획](2026-10-01-core-safety-policy-shadow-plan.md), 아직 없는 계획 3(집행), D-400, D-422, D-424.
- **단계:**
  1. G-sim 재실행. 이전 3회는 호스트 CPU 100%로 미결이었다. 부하를 기록하고 결과가 부하 때문인지 판정한다.
  2. 계획 2 착지(P3-8 trailer).
  3. 로봇별 G-dev(그림자 기록이 실제 주행에서 맞는지).
  4. 계획 3 작성: 집행 HOLD/래치 경계, `safety.policy_hold`, 보정 저장소 새 종류. 계획 2 문서 28행이 범위를 적어 두었다.
  5. Nav2·teleop 경로에 몸 기준 근접 정지가 없다. D-400 집행이 이 빈칸을 덮는 경로다. 계획 3에 "집행 시 모든 출처에 D-424 몸 기준 판정 적용"을 수용 조건으로 넣는다.
  6. 로봇별 G-enforce는 사용자 승인 뒤.
- **게이트:** G-sim 통과 기록, G-dev 증거, 계획 3 승인, 로봇별 G-enforce 기록. 그 전까지 어느 로봇에서도 enforce를 켜지 않는다.

### P3-3 층 4: 엔벌로프 스킬 계약 ADR (D-399 후속 1, D-427 후속 3)

- **역할:** architect(초안), critic·code-reviewer(독립 리뷰). **크기:** M. **safety:** ADR 문서. 구현은 safety 경로가 되므로 그때 trailer.
- **선행:** 없음.
- **대상:** D-399 §2·§7 후속 1, D-427 §5, D-430 층 4, D-231 §4(같은 호스트 밖 추론 개정 여부).
- **ADR이 정할 것:** LeRobot 추론 → Motion Intent, 작업 영역·시간·속도·스텝 상한, 이탈 시 HOLD와 RL `terminated=True`, 녹화 모드와의 관계, LeRobotDataset 매핑, 추론 호스트. D-430 매니페스트 태그(`middleware/skills`의 엔벌로프 root를 `concern: safety`로).
- **게이트:** ADR Accepted(사용자), ADR Log 행, D-430 층 4 상태 칸 포인터, harness lint. 이 ADR과 구현이 들어오기 전에는 학습 정책을 실물에 연결하지 않는다.

### P3-4 층 5: OMX Arbiter 표와 MANUAL 선점 (D-399 후속 5)

- P4-1과 같은 ADR이다(D-429 후속 1이 D-399 후속 5를 합쳤다). P4-1에서 한다. 구현 시 `omx_adapter/command_owner.py`·`local_stop.py`는 safety 경로다.

### P3-5 층 7: 확인만

- **역할:** verifier. **크기:** S. **safety:** 아니오.
- **사실:** 사이트 장치 직접 구동 이름(신호·문·컨베이어·PLC 출력)이 `src/site/fleet/test/test_model_tool_adapter_conformance.py`의 거부 목록에 있다(152–159행 근처, 3c 뒤 `operations/fleet/test/`). D-430 §2 층 7 상태 칸은 "아직 시험에 없다(D-429 wave 0)"라고 적혀 있다.
- **단계:** 시험이 녹색인지 보고 D-430 층 7 상태 칸을 "시험에 있다"로 고친다(ADR 상태 문구 갱신, 독립 리뷰).
- **게이트:** `python -m pytest operations/fleet/test/test_model_tool_adapter_conformance.py -q`, lint.

### P3-6 `KNOWN_SAFETY_VIOLATIONS` 축소: Fleet 정지 경로 carve

- **역할:** executor, code-reviewer(독립). **크기:** L. **safety:** 예.
- **선행:** 3c 착지. `feat/d414-fleet-cancel-all` 착지 또는 보관(같은 파일을 바꾼다).
- **사실:** `test/architecture/test_safety_separation.py`의 `KNOWN_SAFETY_VIOLATIONS`는 21건이다. D-430 §3은 18건이라 적는다. 차이 3건은 `app.py`가 `task_dispatch_routes`의 비앵커 이름(`GoalRequest`, `cancel_pending_task_queue`, `fanout_local_omx_stops`)을 import하는 것으로, 시험 주석이 "D-430 §3 grep에서 빠졌다"고 적는다.
- **대상:** D-430 Validation wave 0 2번이 요구한 carve 계획은 저장소에 별도 문서가 없다. 이 항목이 그것이다.
- **단계:**
  1. `operations/fleet/fleet/server/stop/` 하위 패키지를 만들고 `dispatch_admission`, `cancel_all`, `cancel_all_store`, `local_stop_transport`를 옮긴다. 하위 root `concern: safety`, `safety_modules`에서 해당 항목 제거, `safety_anchors` 경로 갱신.
  2. `console.py`의 `estop_all`과 `task_dispatch_routes.py`의 rearm 처리기·`fanout_local_omx_stops`를 `stop/`의 함수로 뽑는다. 두 섞인 파일은 그 함수를 부르는 decision 코드가 되고 `safety_modules`에서 빠진다(14건 감소).
  3. `cancel_all.py`의 `console_view` 오류 문구와 `fleet.swarm.transport.RobotApiError` import를 `stop/` 안의 작은 타입이나 주입으로 바꾼다(2건).
  4. 내부 edge 2건: `cancel_all_store.ensure_schema`, `dispatch_admission.normalize_resources`를 공개 진입점으로 승격(앵커 `public: true`)하거나 호출을 공개 함수 뒤로 옮긴다.
  5. `app.py` 3건은 2단계 뒤 공개 진입점으로 다시 분류한다.
  6. HTTP 경로, 응답, 래치 의미는 바꾸지 않는다. 모듈 이동이 Fleet import 경로를 바꾸므로 P1-6처럼 공지한다.
- **게이트:** `KNOWN_SAFETY_VIOLATIONS`가 21 → 0(또는 남은 항목마다 이유), `test_safety_separation.py`, `test_dispatch_stop_latch.py`, `test_cancel_all.py`, Fleet 전체 시험, Fleet 브라우저 E-stop·rearm 흐름, Fleet 이미지 빌드. trailer 근거에 이 시험 출력.

### P3-7 문서화된 시험 빈틈 (이동 계획 "알려진 빈틈")

- **역할:** executor. **크기:** M. **safety:** 행동 시험이 safety 태그 파일 옆에 들어가면 판정에 따름.
- **선행:** 4d 착지(경로 안정).
- **단계(우선순위 순):**
  1. **어느 층이 0을 내는가.** `test_estop_zeroes_every_source_and_clip_applies`는 출력 0만 본다. `CommandManager.select_output`의 stop 검사, E-stop 리스너의 슬롯 비우기, 입력 setter 거부, EMERGENCY의 `return ZERO`를 각각 단독으로 시험하는 층별 시험을 더한다. 각 장치를 하나씩 끄는 변이 증명을 커밋 메시지에 적는다.
  2. **소유자 규칙.** 공개 앵커 클래스를 통째로 import한 코드가 비공개 메서드를 부르는지 AST 속성 호출로 검사한다. 대상: `FleetConsole`, `SafetyManager`.
  3. **규칙 2 범위.** control·other 태그 코드가 safety 내부를 import하는지 검사를 넓힐지 정한다. 넓히면 첫날 위반을 동결 목록으로 시작한다.
  4. 남은 것(문자열 앵커 계산 비교, 승인 기록의 런타임 PUT·장치 overlay, 병합 커밋 trailer 범위)은 이 계획의 "알려진 빈틈"에 그대로 두고 처리하지 않는다.
- **게이트:** 새 시험 녹색, 변이 증명, `test/architecture`, lint.

### P3-8 `feat/d400-plan2-rosim` 착지 trailer

- **역할:** 브랜치 주인, code-reviewer. **크기:** S. **safety:** 예.
- **사실:** 이 브랜치는 `core_features/safety`(2파일)와 gateway·services·api_web를 바꾼다. 착지 때 safety 경로를 건드리는 커밋마다 trailer가 필요하다. CI의 `Safety-Review trailer (D-430)` 작업이 막는다.
- **단계:** rebase 뒤 `python tools/harness/safety_review.py origin/main HEAD`로 trailer 없는 커밋을 찾는다. 독립 리뷰 뒤 그 커밋들에 trailer를 단다(아직 push 안 된 브랜치 커밋이므로 rebase로 메시지를 고칠 수 있다). push 뒤 공개 커밋은 고치지 않는다.
- **게이트:** `safety_review.py`가 0 실패, CI 녹색, 리뷰 근거 링크.

### P3-9 robot-literal backlog 후속 (D-411·D-424 여섯 파일)

- **역할:** executor, code-reviewer. **크기:** M. **safety:** `robot_body.py`와 safety 태그 주석 파일은 예.
- **선행:** 4d·4e 착지(경로). 제품 profile 위치가 정해짐(D-397 `geometry.yaml`, D-411 §8 controls profile).
- **대상:** `test/robot_literal_backlog.txt` 74–86행의 여섯 항목.

  | 파일(이동 전 `src/` 상대) | 할 일 | safety |
  |---|---|---|
  | `contracts/foundation/core_common/protocol/controls.py` | `pinky_controls()`를 Pinky 제품 profile로 옮긴다(D-411 §8) | 아니오 |
  | `runtime/api_web/core_api_web/api/v1/system.py` | 위 이동 뒤 import가 빠지며 backlog에서 사라진다 | 아니오 |
  | `contracts/foundation/core_common/robot_body.py` | `PINKY_PRO_GEOMETRY`를 제품 profile `geometry.yaml`에서 읽는다(D-397, D-424, URDF 명목값 → 보정 정제) | 예 |
  | `runtime/sensing/control/control/lidar_guard.py` | docstring의 Pinky LiDAR 예시 숫자를 일반화 | 예(주석이라도) |
  | `runtime/sensing/control/control/safety_profile.py` | Pinky LiDAR 바닥 메모를 일반화 | 예(주석이라도) |
  | `runtime/services/core_features/localization/mission.py` | docstring 예시 거리를 profile 참조로 바꿈 | 아니오 |
- **게이트:** `python -m pytest test/test_robot_literals.py -q`(backlog 줄 삭제와 함께), CORE·line follow 시험, `RobotBody` 값이 이전과 같음을 보이는 시험(같은 Pinky profile에서 같은 숫자), trailer.

## P4. D-429 후속 ADR과 남은 import 위반

ADR은 `architect`가 초안을 쓰고 `critic`·`code-reviewer`가 독립 리뷰하고 사용자가 승인한다. 각 ADR은 D-427·D-429·D-430과의 관계 표를 가진다(AGENTS 규칙 6). 게이트는 ADR Log 행·상태·번호 충돌 부재·harness lint다.

| ID | ADR | 선행 | 이 ADR이 정해야 할 것(D-429 후속 본문 참고, 여기서는 묶음만) | 크기 |
|---|---|---|---|---|
| P4-1 | Motion Intent + DeviceControlPort | 없음 | D-399 후속 5와 합침(P3-4). 장치별 Arbiter 표, OMX MANUAL phase 선점(D-376 §6과 정합), `skills/manipulation`·`omx_adapter` 포트를 `api`로 추출하는 범위. 불변식 3(D-430)을 binding 시험에 어떻게 거는지 | L |
| P4-2 | `rosy.site-device/1` | 없음 | 공통 바탕, kind별 명령, 감독 상실 timeout, 측정/주장 구분. D-430 불변식 5 참조 | M |
| P4-3 | ER2 사이트 장치 후보 제안 | P4-2, P2-1 | 후보 스키마·감사·승인 UI. 도구 이름이 거부 목록(P3-5)과 겹치지 않음 | M |
| P4-4 | PLC 인터록 | P4-2 | 첫 비-ROS 대상. `test_plc_adapter_never_writes_safety_addresses`는 D-430 소유로 첫 어댑터와 함께 들어온다 | M |
| P4-5 | 로컬 VLA 배치 | P3-3 | 호스트, 엔벌로프, D-231 §4 개정 여부 | M |

### P4-6 남은 `KNOWN_VIOLATIONS` (`test/architecture/test_platform_parts.py`)

2026-10-03 기준 5건, 2b(P2-6) 뒤 4건 예상. 은퇴 커밋은 집합에서 키를 지우고 시험이 녹색이어야 한다(줄이기만).

| edge | 은퇴시키는 일 | 선행 |
|---|---|---|
| `middleware/apps/device/omx/agent → operations/processes/palletizing` | OMX 셀 owner가 셀 문서·compiler를 직접 읽지 않고 operations가 만든 PlanBundle(계약)을 받게 한다. 범위는 D-401(Rosy Cell)·D-435 역할 정리와 함께 정한다 | P5-4, P4-1 |
| `integrations/robots/omx → middleware/skills/manipulation` | transfer Skill 포트를 `api: true` root로 추출(D-429 §4) | P4-1 |
| `integrations/robots/omx → middleware/apps/device/omx/adapter` | pick-place journal 포트를 `api` root로 추출 | P4-1 |
| `learning/curation/omx → middleware/apps/device/omx/adapter` | demonstration 검증을 Episode profile로 | P2-6 |
| `learning/training/perception → middleware/perception` | 재생 전용 예외로 남길지 결정. 남기면 `KNOWN_VIOLATIONS` 대신 D-427 §2 예외 규칙으로 옮긴다 | P2-5, 열린 질문 5 |

## P5. 정리

### P5-1 ADR Log·docs index 정합성

- **역할:** executor. **크기:** S. **safety:** 아니오.
- **사실:** `docs/adr`에 D-426, D-427, D-429–D-435는 있고 D-428은 파일도 ADR Log 행도 없다. 브랜치 `feat/d428-web-face-sweep`가 있다. 번호 예약인지 확인한다(열린 질문 6).
- **단계:** `python tools/harness/rosy_harness.py lint`의 ADR 경고를 본다. `docs/progress.md`의 `adrs`·`plans` 목록과 ADR Log·파일 목록을 대조한다. 이동 계획과 이 계획을 `docs/progress.md` `plans`에 넣을지 정하고 `generate`로 `docs/index.md`를 다시 만든다.
- **게이트:** lint 0 errors, ADR 파일·Log 행·progress 목록 1:1.

### P5-2 옛 경로를 쓰는 살아 있는 문서 (D-226)

- **역할:** executor. 결정은 사용자. **크기:** S. **safety:** 아니오.
- **선행:** P1-1.
- **사실:** `git grep -l -E "src/(site|runtime|hmi|products|sim|contracts|drivers)/" -- docs ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!docs/solutions' ':!**/logs.md' ':!**/progress.md'`가 14개 파일을 찾는다. 계약 문서(`docs/reference/ROSY API & Protocol Reference.md`), 설계 참고(`docs/reference/ROSY_Platform_Architecture_Design_v0.2.md`, `docs/architecture/16_ROSY_Interface_Design_Principles.md`, `docs/reference/isaac-sim-integration-research.md`), 운영 문서(`docs/deployment/*.md` 3개), 폴더 노트(`docs/AGENTS.md`, `docs/reference/AGENTS.md`, `docs/spec/AGENTS.md`, `docs/test/AGENTS.md`), 평가(`docs/assessments/module-coupling-report.md`), 생성물 `docs/index.md`, ADR Log.
- **단계(권고, 열린 질문 7):** 운영 문서·계약 문서·폴더 노트는 새 경로로 고친다(사람이 그대로 실행한다). 설계 참고·평가·조사 문서는 본문을 두고 맨 위에 "경로는 D-427 이전, 대응은 `tools/harness/platform_parts.yaml`" 한 줄을 단다. ADR Log 과거 행은 고치지 않는다.
- **게이트:** 위 grep에서 운영·계약·폴더 노트가 0건, lint.

### P5-3 `test_jpeg_relay` Windows flake

- **역할:** executor(`superpowers:systematic-debugging`). **크기:** S. **safety:** 아니오.
- **사실:** 컨테이너 CI 실패는 좀비 판정으로 원인이 기록됐다([container-zombie-kill0-blindness](../solutions/deployment/container-zombie-kill0-blindness.md)). Windows 간헐 실패는 별도로 기록된 원인이 없다.
- **단계:** Windows에서 20회 반복(`for i in $(seq 20); do python -m pytest test/test_jpeg_relay.py -q -p no:cacheprovider || break; done`), 실패 출력 수집, 원인 확정 뒤 수정. 시간 의존이면 시계 주입, 포트 의존이면 임시 포트. skip으로 덮지 않는다.
- **게이트:** Windows 50회 연속 통과, 리눅스 CI 녹색, 교훈이 있으면 `docs/solutions/`.

### P5-4 D-435 수용 판단

- **역할:** architect(대응표), critic(독립 검토), 사용자(승인). **크기:** M. **safety:** 아니오.
- **선행:** P1-1. 미병합 `docs/d435-review` 브랜치 처리(착지 또는 흡수).
- **대상:** D-435 "Validation and follow-up"의 9개 반례, D-427·D-429·D-430 관계 행.
- **단계:** 이동 뒤 실제 경로(`operations/fleet`, `operations/execution`, `operations/processes/*`, `middleware/apps/device/omx/agent`)를 D-435 논리 역할에 대응시킨다. 반례마다 소유자·권한·원장을 그 경로로 설명한다. 폴더·서비스 신설이 필요 없음을 확인한다. 설명이 막히는 반례는 D-435 미결정 목록으로 옮긴다.
- **게이트:** 대응표가 D-435 본문 또는 부록에 있고, 사용자가 Accepted 또는 계속 Proposed를 정함. 수용 시 ADR Log 행 갱신, lint.

## 열린 질문

1. P1-4: 이동 기간 규칙 1항의 "폴더 이동 > main CI > 안전 > 기능"을 이동 뒤 어떻게 할지(삭제, 또는 "main CI > 안전 > 기능").
2. P2-1: `rosy.decision`의 배포 이름(예 `rosy-decision`)과 설치 단위(Fleet 이미지 wheel, ROS 패키지 `fleet`의 의존 선언).
3. P2-3: gz_sim launch를 패키지 폴더 밖으로 옮길 때 `share/gz_sim/launch` 설치를 유지하는 방법.
4. P2-4: signal observer의 최종 위치.
5. P2-5·P4-6: 재생 전용 learning → middleware perception edge를 D-427 §2 예외로 둘지.
6. P5-1: D-428 번호가 예약인지.
7. P5-2: 설계 참고 문서를 머리말로 둘지 본문을 고칠지.

## 완료 정의

- P1 전부 끝: pending root 0, `src/`·`modules/`·`apps/` 없음, wave별 동등성 증거, safety rename 리뷰 기록, AGENTS 2·5항 삭제, 로봇이 이동 포함 release를 readback.
- P2·P3·P4는 항목별 게이트로 닫는다. 이 계획 전체의 완료가 장치·현장 수용을 뜻하지 않는다.
