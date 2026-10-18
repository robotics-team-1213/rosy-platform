# 2026-10-15 인계 — main 관문(D-762), 워크트리 관문(D-761), 착지·푸시 운영

컴퓨터를 옮기기 전에 적은 인계 문서다. 새 컴퓨터에서 이 일을 이어 받는 사람(사람이든 에이전트든)이 읽는다. 적은 시점의 사실이고, 계약은 ADR이 이긴다.

## 1. 지금 상태

- `origin/main`은 `bc4a69fac`까지 푸시됐다(2026-10-15, 다섯 번에 나눠 푸시). 그 뒤 local main에 착지한 것은 아직 푸시 전이다. 새 컴퓨터는 `origin/main`에서 시작한다.
- D-762 단계 0과 1은 main에 있다.
  - 단계 0: `tools/land.py`와 pre-push가 안전 경로 커밋의 `Safety-Review:` 트레일러를 요구한다(면제는 `tools/harness/safety_review_exempt.json`). FULL 착지는 연구실 전체 등급을 돈다.
  - 단계 1: CI에 `merge_group` 트리거가 있다. 불안정 시험 격리는 `test/flaky_quarantine.txt`이고 재시도 한 번이다.
- 2026-10-15에 이 문서와 같이 착지를 기다리던 FULL 둘: `docs/remove-reference-folder`(사용자 결정으로 루트 `reference/` 삭제 커밋), `fix/dependabot-alerts`(Fleet `oauthlib` 4.0.0, LeRobot exporter `torch` 2.10.0). 착지했는지는 `git log origin/main`으로 본다. 브랜치가 남아 있으면 `python tools/land.py --tests auto`로 착지한다.

## 2. 마감이 있는 일

- **2026-11-15:** CI의 `modules` 러너(전체 등급 1,518개 시험 파일)는 지금 판정에 들어가지 않는다. 그날까지 판정에 넣지 않으면 그날 main이 일부러 빨개지도록 걸어 두었다(D-762 단계 1). 그 전에 `modules` 러너의 실패를 0으로 만들고 필수 검사로 올린다.

## 3. 열린 결정(사용자)

1. **두 번째 관리자.** D-762 결정 3(관문 경로 변경은 작성자가 아닌 code owner 승인 + 두 번째 관리자)은 그 사람이 정해져야 성립한다. 정해질 때까지 단계 3(merge queue, 필수 `ci-result`, 관리자 우회 축소, CODEOWNERS, 관리자가 아닌 에이전트 신원)을 적용하지 않는다.
2. **단계 2 이후의 적용.** 단계마다, 그리고 GitHub ruleset·설정 변경마다 사용자가 그 자리에서 따로 승인한다. ADR이 Accepted인 것은 그 승인이 아니다.
3. **Dependabot.** 18건 가운데 5건은 `fix/dependabot-alerts`로 고쳤고, 13건은 2026-10-15 사용자 결정으로 GitHub에서 "tolerable risk"로 닫았다(경고마다 이유 기록). Isaac Sim 5.1이 스스로 고정한 `starlette`·`filelock`·`fsspec`·`wheel`(11건)과, 어느 lerobot 릴리스도 허용하지 않는 `torch` 2.13·`datasets` 5.0(2건)이다. Isaac 6.x로 옮기거나 lerobot이 상한을 올리면 다시 연다. Isaac의 Kit HTTP 서비스가 headless에서 네트워크에 열리는지는 확인하지 못했다.

## 4. 이 클론에만 있는 것 — 새 컴퓨터로 옮기는 법

저장소가 공개라 아래는 `origin`에 올리지 않는다. 특히 `git push --tags`를 쓰지 않는다.

- 보관 태그 `refs/tags/archive/*` 203개(D-172 보관과 2026-10-13/14 정리 때 만든 것), `refs/wip/*`, ADR 번호 선점 `refs/adr/D-*`, `origin`에 없는 로컬 브랜치 87개.
- 모두 번들 하나에 담았다: `X:\DevTemp\rosy-handoff\rosy-platform-all-refs-2026-10-15.bundle`(약 153 MB, ref 1,040개). 마지막 착지 뒤에 다시 만든다.
- 새 컴퓨터에서:

```bash
git clone https://github.com/robotics-team-1213/rosy-platform.git
cd rosy-platform
git bundle verify /path/to/rosy-platform-all-refs-2026-10-15.bundle
git fetch /path/to/rosy-platform-all-refs-2026-10-15.bundle 'refs/tags/archive/*:refs/tags/archive/*' 'refs/wip/*:refs/wip/*' 'refs/adr/*:refs/adr/*'
git fetch /path/to/rosy-platform-all-refs-2026-10-15.bundle 'refs/heads/*:refs/remotes/bundle/*'
```

  로컬 브랜치는 `refs/remotes/bundle/<이름>`으로 들어오고, 필요한 것만 `git branch <이름> bundle/<이름>`으로 꺼낸다.
- 보류 브랜치와 그 이유는 `docs/reference/held-branches.md`에 있다. 이번에 더한 것: `fix/gazebo-map-lap`의 `ebd718fae`는 전방 정지 sweep 배선의 미완성 작업이다. 검토·시험 전이라 착지하지 않는다(안전 경로).

## 5. 저장소 밖에 있어 따로 옮길 것

- 우산 폴더 안내 `F:\Dev\Control\Robot\Rosy\AGENTS.md`는 git 밖이다. 「같이 하는 깃」 절차의 전문이 여기 있다. 그대로 복사한다.
- 에이전트 기억 `C:\Users\<user>\.claude\projects\f--Dev-Control-Robot-Rosy\memory\`(시험 PC 주소, 사용자 규칙). 새 경로의 projects 폴더 이름은 작업 폴더 경로에 따라 바뀐다.

## 6. 새 컴퓨터 준비

- **Tailscale:** 시험 PC는 프로필 `665e`(ggujunhios)에서만 보인다. `tailscale switch --list`에서 `*`가 `665e`에 있어야 한다. 2026-10-15 밤에 이 노트북은 세션이 바꾸지 않았는데도 다른 프로필(`bc4d`)로 두 번 넘어갔고, 그때마다 원격 시험이 exit 255로 죽었다. 원인은 찾지 못했다(Tailscale 앱 또는 수동 전환으로 본다). 그동안은 원격 시험 시작 전에 프로필을 확인한다.
- **ssh 키:** 모델 PC `rosy@100.98.162.71`, AI PC `ai@100.108.76.123`, 현장 PC `robttt@100.82.51.8`. 시험은 `tools/remote/remote_pytest.py`가 고른 PC에서 돈다. 이 노트북에서는 pytest를 돌리지 않는다(D-584). 그 규칙이 새 컴퓨터에도 적용되는지는 D-762 결정 4(연구실 노트북·연구실 에이전트 세션 한정)를 본다.
- **도구:** `gh` 로그인(조직 `robotics-team-1213`), `git` 2.48 이상(`worktree add --relative-paths`), `python`과 `pyyaml`(하네스는 `python3`가 아니라 `python`을 쓴다).
- **임시 파일:** 이 노트북은 스크래치를 `X:\DevTemp\`에 둔다. 새 컴퓨터에 X:가 없으면 같은 역할의 폴더를 정하고 우산 `AGENTS.md`의 X: 경로를 그에 맞춘다.

## 7. 착지·푸시 운영에서 배운 것

- FULL 착지(약 25–30분)는 다른 세션의 착지를 멈춰야 끝난다. main이 움직이면 다음 라운드가 돌고, 델타가 FULL이면 다시 전체를 돈다. 시작 전에 동료에게 멈춤을 요청하고 끝나면 알린다.
- 착지 순서와 FULL 창은 세션끼리 직접 정했다. 2026-10-15 기준 대기열: 위 FULL 둘 → rosy-e9의 D-766 squash, `feat/api-version-reserve`, size-units lane A(모두 FULL) → rosy-84의 D-767 셋(`docs/route-preview-adr`, `feat/route-preview-p0`, `feat/instruction-pose-stamp` — 마지막은 `contracts/foundation`이라 FULL).
- 워크트리는 `python tools/worktrees.py new <짧은이름> <type>/<topic>`으로 만들고, 착지 뒤 `python tools/worktrees.py prune --apply`로 지운다. 상한 60. 2026-10-15에 60에 차서 `--idle-hours 36`으로 손실 없는 정리를 했다(깨끗·main에 들어감·잠기지 않음만 지움).
- 관련 교훈 문서: `docs/solutions/workflow-issues/a-rule-that-only-works-if-everyone-follows-it-is-not-a-gate-2026-10-14.md`, `docs/solutions/workflow-issues/check-supersession-before-resolving-stale-branch-conflicts-2026-10-13.md`.
