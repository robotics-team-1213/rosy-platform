# 중복 구현·파일 배치 감사 (2026-10-20)

작성 2026-10-20 KST. 대상: `D:\Dev\Robot` 트리와 정본 저장소 `Rosy/rosy-platform`
(main `8d8921ac0e`). 제품 코드·설정·git 상태는 바꾸지 않았다. 이 보고서와 루트 보고서
이동 스크립트, 그리고 이동될 보고서 사본만 만들었다.

## 먼저 볼 것

- 실행 계획은 이미 따로 있다: `Rosy/rosy-platform/docs/plans/2026-10-20-duplicate-placement-cleanup.md`
  (main 체크아웃에 미추적, 다른 세션 작성). 이 보고서는 그 계획을 대체하지 않는다.
  그 계획이 이미 잡은 묶음 0~4(문서·빈 파일 → 갈라진 사본 → 같은 사본 합치기 → 파일 이동,
  묶음 4는 ADR 필요)는 그대로 유효하다. 이 보고서는 계획에 없는 세 가지를 보강한다:
  (1) 루트 보고서 15개의 위치, (2) 운영 위험(main 발산·워크트리 상한), (3) 계획이
  다루지 않는 몇몇 사본의 근거와 문서 공백.
- 루트 보고서 15개는 이 워크트리 `docs/...`로 이미 **복사**해 두었다(원본 유지). 검토 후
  원본을 지우려면 이동 스크립트를 `-Apply`로 한 번 더 실행한다.

## 감사 방법

- 두 개의 독립 경로로 확인: (1) 정본 `rosy-platform` 전체를 `*.py` SHA256으로 묶어 바이트
  동일 그룹을 뽑고, (2) 파일 basename별로 묶어 동일 이름 다중 정의를 뽑은 뒤, 후보는
  내용·docstring·소비자를 직접 읽어 "의도된 중복 / 우발적 중복 / 중복 아님"을 판정했다.
- 문서 배치는 `docs/AGENTS.md`, `docs/assessments/AGENTS.md`, `docs/validation/AGENTS.md`,
  `docs/plans/AGENTS.md`와 `rosy-platform/AGENTS.md`의 명명·배치 규칙을 기준으로 삼았다.
- 루트 보고서는 정본 validation 기록과 **줄 단위 교집합**을 재서 "같은 파일인지, 갈라진
  사본인지, 다른 범위인지"를 구분했다(바이트 비교가 아님).
- 링크 재작성은 스크립트 dry-run으로 계획(planned 15, link rewrites 68, missing 0)을 먼저
  검증한 뒤 `-Apply -Copy`로 이 워크트리에 스테이징하고, 한글 인코딩과 대표 링크를 Read로
  확인했다.

## 결론 요약 (심각도 순)

| # | 항목 | 근거 | 위험 | 다음 행동 |
|---|------|------|------|-----------|
| 1 | main 발산 `ahead 983 / behind 52` | `git status -sb` | 착지(`--ff-only`) 불가, CI 증거 없음 | 사용자와 reconcile 방식 결정. 그 전 land 금지 |
| 2 | 워크트리 상한 60/60 도달 | `tools/worktrees.py status` 60행 | 새 worktree 생성 불가 | `prune` 전 다른 세션 worktree 검토·동의 |
| 3 | 루트 보고서 15개가 규약 밖 위치 | 루트 `D:\Dev\Robot\*.md`·`*.txt` | 규약 위반, 문서 발견성 저하 | 이 워크트리 사본 검토 후 `-Apply`로 원본 제거 |
| 4 | 동시 세션이 main·루트에 파일 생성 중 | `docs/plans/2026-10-20-duplicate-placement-cleanup.md`, 루트 `duplicate-placement-progress.md` | 편집 충돌 | 손대지 않음, 보고만 |
| 5 | peer_crypto 바이트 동일 중복 | SHA256 `9A59…7A29` | 이미 테스트로 소유권 고정 | 그대로 둔다(가드 존재) |
| 6 | 테스트 basename 충돌 13건, 문서는 1건만 기재 | `test_*.py` basename | 새 CI가 import 충돌로 오판 | 계획과 함께 AGENTS 문서 보강 |
| 7 | 문서 경로 드리프트 | `Rosy/AGENTS.md`, `docs/plans/AGENTS.md` | 잘못된 경로 안내 | Task 0 문서 수정에 추가 |
| 8 | `src/` 잔여(추적 0, 무시 31) | `git ls-files src` 빈 값 | retired 레이아웃 잔존 | 후속 정리 후보 |

---

## 1. 운영 위험

### 1.1 main 발산

`main...origin/main [ahead 983, behind 52]`, HEAD `8d8921ac0e89277a85c921810ab28218a5741b5c`
(2026-10-19 23:46:34 +0900). 983 커밋이 원격에 없고 52 커밋이 원격에만 있다. 이 상태에서는
`land.py`의 fast-forward 착지가 성립하지 않고, 원격 CI 증거도 현재 HEAD를 가리키지 않는다.
reconcile(merge 또는 rebase 정책) 전에는 어떤 Task도 land하지 않는다.

### 1.2 워크트리 상한

`git worktree list` 61행(main 포함), `.worktrees` 하위 61개 중 `.omc` 제외 60개 = cap 60.
상태 분포: locked 13, merged 14, unmerged 46, stale-history 1(`learning-delivery`),
landed-dirty 1(`v13-map-labels`, dirty 6), 45h 이상 idle 16, dirty 12.
dirty가 큰 것: `hardcode-paths` 738, `omx-native-ready` 84, `auto-state` 27.
merged+locked 7개, unmerged+locked 6개(`fleet-ship`, `omx-native-feedback`, `pinky-key-rotation`,
`learning-name-backport`, `pinky-rl-binding`, `pinky-turn-distance-design`).
`tools/worktrees.py prune`는 안전 정책상 가능하지만 다른 세션의 landed worktree를 지울 수
있으므로 사용자 동의 없이 실행하지 않는다.

### 1.3 착지 대기열

merged 14개와 unmerged 46개가 동시에 열려 있다. 이 감사는 그 내용을 판정하지 않는다.
다만 1.1의 발산과 겹치면 착지 순서를 먼저 정해야 한다.

## 2. 루트 보고서 이동

루트 `D:\Dev\Robot`에 세션 보고서 14개 md + 1개 txt가 규약 위치 밖에 있다. 전부 dated
기록이므로 `docs/validation/`(evidence) 또는 `docs/assessments/`(전체 트리 평가)·`docs/plans/`
(계획)로 옮긴다. 다른 세션의 `duplicate-placement-progress.md`는 이동 대상에서 제외한다.

### 2.1 이동표 (15개)

| 루트 원본 | 크기(B) | 목적지 |
|-----------|--------:|--------|
| `learning-pipelines-status-2026-10-19.md` | 33092 | `docs/assessments/2026-10-19-learning-pipelines-status.md` |
| `pipeline-completion-assessment-2026-10-19.md` | 28625 | `docs/assessments/2026-10-19-pipeline-completion.md` |
| `port-focus-assessment-2026-10-20.txt` | 10932 | `docs/assessments/2026-10-20-port-focus.md` |
| `pinky-corner-completion-2026-10-19.md` | 15548 | `docs/validation/pinky-corner-completion-2026-10-19/result.md` |
| `pinky-success-integration-2026-10-19.md` | 18161 | `docs/validation/pinky-success-integration-2026-10-19/result.md` |
| `pinky-drivable-v2-recheck-2026-10-19.md` | 9657 | `docs/validation/pinky-drivable-v2-recheck-2026-10-19/session-report.md` |
| `rosy-app-names-2026-10-19.md` | 7905 | `docs/validation/app-names-2026-10-19/session-report.md` |
| `rosy-app-deployment-2026-10-19.md` | 8087 | `docs/validation/rosy-app-deployment-2026-10-19/result.md` |
| `rosy-app-deployment-2026-10-20.md` | 5509 | `docs/validation/rosy-app-deployment-2026-10-20/result.md` |
| `uncommitted-merge-review-2026-10-19.md` | 23370 | `docs/validation/uncommitted-recovery-2026-10-19/result.md` |
| `worktree-cleanup-plan-2026-10-18.md` | 51177 | `docs/plans/2026-10-18-worktree-cleanup.md` |
| `worktree-cleanup-followup-2026-10-19.md` | 12755 | `docs/validation/worktree-cleanup-2026-10-19/result.md` |
| `worktree-merge-followup-2026-10-19.md` | 35464 | `docs/validation/worktree-merge-2026-10-19/result.md` |
| `worktree-retirement-manifest-2026-10-19.md` | 5368 | `docs/validation/worktree-retirement-2026-10-19/result.md` |
| `worktree-retirement-remaining-2026-10-19.md` | 4533 | `docs/validation/worktree-retirement-2026-10-19/remaining.md` |

`pinky-drivable-v2-recheck`와 `rosy-app-names`는 목적지 폴더에 이미 frozen `result.md`가
있어서 덮어쓰지 않고 `session-report.md`로 옆에 둔다(rewrite 금지). `uncommitted-recovery`
폴더에는 `result.md`가 없어 그 자리를 채운다.

### 2.2 정본 기록과의 관계 (바이트 동일 아님)

줄 단위 교집합으로 재 본 결과, 루트 사본은 정본과 **같은 파일이 아니다**:

- `pinky-drivable-v2-recheck`: 루트 89줄 vs 정본 56줄, 공통 22줄(루트의 24.7% / 정본의 39.3%).
  루트에만 있는 재검토 분석이 있다.
- `rosy-app-names`: 루트 72줄 vs 정본 73줄, 공통 20줄(27.8% / 27.4%).
- `pinky-success-integration`: 루트 235줄 vs `pinky-success-baseline-2026-10-19/result.md` 77줄,
  공통 20줄(8.5% / 26%). baseline 기록과 integration 보고는 범위가 다르다.

따라서 "중복이라 삭제"가 아니라 "옆에 보존"이 맞다. 정본 `result.md`는 그대로 둔다.

### 2.3 링크 재작성과 스크립트

스크립트: `C:\Users\SERIGGG\AppData\Local\Temp\opencode\root-report-relocation\relocate-root-reports.ps1`.

- 기본 dry-run. `-Apply`로 실행, `-Copy`면 원본 유지.
- main 체크아웃 root를 `git -C <worktree> rev-parse --git-common-dir`로 구해 상대 링크를
  다시 계산한다: `Rosy/rosy-platform/...`→repo root 기준, `rosy-vault/...`→`D:\Dev\Robot`
  기준, 루트 보고서끼리의 sibling 링크→새 위치 기준. `C:/...`·`http`·`#`는 그대로 둔다.
- dry-run: planned 15, link rewrites 68, missing targets 0. `-Apply -Copy`로 이 워크트리에
  15개 파일 스테이징 완료(UTF-8 한글·대표 링크 Read 확인).
- `-Apply`(move)는 목적지가 이미 있고 내용이 같으면 원본을 지우도록 처리해 두었다
  (스테이징 후 재실행 시 원본 정리). 내용이 다르면 경고하고 건너뛴다.

## 3. 중복 구현

### 3.1 바이트 동일

SHA256 동일 그룹은 4개뿐이다.

1. `middleware/core/api/core_api_web/api/peer_pairing/peer_crypto.py` ==
   `operations/fleet/fleet/server/peer/camera_peer_crypto.py`
   (각 5773B, SHA256 `9A59BC3B9A4C2414195798D3310FF2FF378F7A6C8E68F303B6A1CEB6A98E7A29`).
   `test/architecture/test_peer_proof_ownership.py`가 소유권을 고정하는 의도된 중복이다.
2. `test_copyright.py`, `test_flake8.py`, `test_pep257.py`가 3곳씩
   (`middleware/devices/pinky/bringup/test`, `middleware/drivers/pinky_led/test`,
   `middleware/robot_ui/face/test`)에 동일하게 있다. ament lint 보일러플레이트로 허용.

### 3.2 갈라진 사본 (계획과 연결)

- `deploy/site/site_users.py`(366줄) vs `operations/fleet/fleet/server/auth/site_users.py`(146줄).
  site 호스트에는 Fleet이 설치되지 않아 규칙을 미러한다(D-276 토큰 digest / D-519 비밀번호).
  의도된 미러지만 두 파일이 각자 진화하므로 drift 위험이 있다. 양쪽 docstring이 서로를
  가리킨다. 계획의 "갈라진 사본" 묶음에 포함해 소유권·검증 규칙 공유를 검토한다.
- 계약 vs 구현 쌍: `contracts/.../pilot_recording.py` vs `middleware/perception/nodes/pilot_recording.py`,
  `contracts/.../omx_sim.py` vs `middleware/devices/omx/agent/src/rosy_agent/omx_sim.py`.
- 호환 shim: `omx_adapter/camera_contract.py`(11줄), `omx_adapter/target_evidence.py`,
  `operations/processes/cell/rosy_cell/cell.py`(re-export 2줄).

### 3.3 동일 basename 다중 정의 (중복 아님, 계획과 연결)

`manager.py` x10, `analyze.py` x9, `worker.py` x7, `cli.py` x7 — 해시·크기가 전부 달라
도메인별 구현이다. 조치 불요. 다만 `straight_escape.py`(39 vs 63), `map_pose.py`(56 vs 411),
`lane_route.py`(140 vs 155)는 이름이 같고 범위가 달라, 계획이 다루는 "이름 정리" 후보에
해당한다.

### 3.4 중복 아님 (정상으로 판정)

- `profiles/`: 추적·문서화됨(`tools/harness/platform_parts.yaml`, `docs/reference/platform-folder-responsibilities.md`).
- `rosy-ops`, `rosy-vault`, `rosy-docs`, `rosy-platform`은 별도 repo. `rosy-vault/device_core`는
  별도 제품 "Rosy Device"로 중복 아님.
- `/cmd_vel` publisher 4곳은 `test/architecture/test_cmd_vel_publisher_identity.py`가 강제.

### 3.5 테스트 basename 충돌 (문서 공백)

충돌 13개 이름:

`test_battery`(gateway/perception), `test_command_watchdog`(isaac/gazebo),
`test_goal_lease`(gateway/fleet), `test_lane_return`(core/services, fleet),
`test_lane_route`(perception/fleet), `test_led_identity`(fleet/overhead),
`test_omx_profile`(omx adapter/learning curation), `test_package_contract`(core/api, imu_bno055),
`test_preview`(games/overhead), `test_responsibility_layout`(perception/situation),
`test_transport`(fleet/shared.web), `test_copyright`/`test_flake8`/`test_pep257` x3.

`rosy-platform` 루트에는 pytest.ini/setup.cfg/tox.ini도 `importmode` 설정도 없다. 각 test dir에
`conftest.py`만 있다. AGENTS 문서는 `test_battery` 한 건만 언급하므로, 나머지 12건을 같은
문단에 추가한다(계획과 함께).

## 4. 파일 배치·잔여물

### 4.1 루트 stray

`aff1.log`(0B, 미추적), `test_camera_extrinsic.py`·`test_trip_job_lease.py`(0B, `.gitignore:107`
`/*.py`로 무시). 계획 Task 0의 삭제 대상과 일치한다. 빈 폴더 `middleware/perception/vision/`,
`tools/sim/gazebo/pinky_maze.sdf`도 Task 0에 있다.

### 4.2 `src/`

`rosy-platform/src/`는 추적 파일 0개, 무시된 31개(.omc, egg-info 등)만 남았다. 하위 `hmi`,
`runtime`, `sim`, `site`. `docs/plans/AGENTS.md`가 `src/runtime/gateway`,
`src/products/pinky_pro/bringup`을 참조하는 등 retired D-427 레이아웃이 문서에 남아 있다.
정리는 후속 후보(계획 범위 밖).

### 4.3 kernel 스냅샷

`D:\Dev\Robot\kernel-robot-repo-2`는 별도 제출용 repo다. remote는 origin
`https://github.com/livsbittt/kernel-robot-repo-2.git`, `rosy-source`
`https://github.com/robotics-team-1213/rosy-platform.git`, upstream
`https://github.com/kernel-robot-8th/kernel-robot-repo-2.git`. HEAD `a95b81f`(branch
`docs/rosy-verification`, origin/main 대비 3 ahead). 내부 `rosy/`는 219,128,700B(~219MB)의
source 스냅샷이고 `.git`이 없다. `docs/SUBMISSION.md`가 source commit
commit `38f0c452e410fca6c2c8fc72f45c3c250751d58f`, 제출일 2026-10-19를 문서화한다. 의도된 제출물이므로
수정하지 않는다.

### 4.4 문서 경로 드리프트

- `Rosy/AGENTS.md` 레이아웃이 `F:\Dev\Control\Robot\Rosy`로 적혀 있으나 실제는 `D:\Dev\Robot`.
  같은 파일이 omx_adapter 경로를 `middleware/apps/device/omx/adapter`로 적었으나 실제는
  `middleware/devices/omx/adapter`. scratch를 `X:\DevTemp`로 안내하나 이 머신에 X:가 없다.
- `docs/plans/AGENTS.md`, `docs/assessments/AGENTS.md`의 Internal 의존성이 `src/` 레이아웃을
  가리킨다(stale).
- `Rosy/.worktrees/AGENTS.md`가 repo를 `F:\Dev\Control\Robot\Rosy\rosy-platform`로 적었다.

계획 Task 0의 문서 경로 수정(`AGENTS.md`, `docs/reference/core-drive-responsibilities.md`,
`docs/reference/platform-folder-responsibilities.md:277`)에 위 항목을 더한다.

## 5. 하지 않은 것 / 한계

- 제품 코드·설정·git 상태를 바꾸지 않았다. commit/push/prune/land를 하지 않았다.
- 루트 보고서는 복사만 했고 원본은 남아 있다. 원본 제거는 `-Apply` 재실행이 필요하다.
- 중복 4그룹 외의 "갈라진 사본"의 의미론적 동등성은 소유권 ADR 없이 확정하지 않았다
  (계획 묶음 4와 동일한 이유).
- 동시 세션이 만든 `docs/plans/2026-10-20-duplicate-placement-cleanup.md`와 루트
  `duplicate-placement-progress.md`는 읽기만 하고 편집하지 않았다.
