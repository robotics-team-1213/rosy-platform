## D-790 워크트리 규칙 보강: 착지한 워크트리 1시간, orphan 보관 후 정리, 옛 이력 브랜치 거절, 부하성 실패 재실행

**Status:** Proposed (2026-10-17). D-761을 고친다(아래 「D-761에서 바뀌는 것」). 사용자가 "ADR + 도구 + PR"로 진행을 승인했다. 이 결정 자체는 아직 승인되지 않았다.

### Context

2026-10-17 하루 동안 D-761의 관문과 청소만으로는 다음이 해결되지 않았다.

1. **상한에 걸렸는데 치울 것이 없었다.** `.worktrees/`가 60개에 닿았다. `main`에 들어갔고 깨끗한 워크트리(예: `camera-calibration-ready`, `hash-repair`)도 남의 것이면 72시간 동안 "active"라서 `new`가 거절했고, 한 세션은 `--force-over-cap`을 써야 했다.
2. **orphan 디렉터리 8개.** git이 더는 등록하지 않는 디렉터리(Windows 파일 잠금 때문에 지우다 만 것)가 `.worktrees/` 아래에 남았다. 몇 개는 비어 있었고, 몇 개는 `.omc/` 상태만 있었고, 하나는 이미 `archive/2026-10-14/wip/fleet-proof` 태그로 남긴 옛 체크아웃이었다. `status`는 보여 주기만 하고 아무것도 치우지 않았다. 손으로 치우던 중 `tar`가 `C:\...`를 원격 호스트로 읽어 보관 파일 하나를 잃었다(`--force-local` 없이).
3. **착지한 뒤에도 같은 워크트리에서 일했다.** `fix/omx-native-ready`(main에 들어감, 미커밋 84개), `feat/webrtc-camera-migration`(main에 들어감, 미커밋 7개).
4. **이력 재작성 이전 줄기의 브랜치.** `feat/integrated-learning-pipeline`, `fix/signed-catalog-restored-0ef4c1bebf`가 `main` 대비 약 13,800 커밋 앞서 있었다. 두 브랜치와 `main`의 공통 조상은 `ad86fca808`(2026-09-22 09:55 +0900)이다. 평범한 미병합 워크트리처럼 보이지만 착지하면 옛 이력을 다시 들여온다.
5. **소유자가 비어 있었다.** 여러 워크트리의 소유자 칸이 비어 누가 무엇을 지워도 되는지 몰랐다. 일부는 git 신원이 없던 때 만들어져 `owner:  <>`로 적혀 있었다.
6. **D-766 크기 판정이 착지 때에야 나왔다.** 크기 ratchet 대상 파일이 3줄 늘어 착지가 두 번 막혔다.
7. **부하로 인한 실패가 착지를 막았다.** 한 착지의 FULL 실행에서 타이밍·UDS 시험 셋(`test_deliberation_free_probe`, `test_platform_g1_timing`, `test_platform_g1_sim`)이 각각 한 번 실패했고, 따로 돌리면 모두 통과했다. `land.py`는 NEW 실패 하나에도 멈춘다. D-762 1단계는 `test/flaky_quarantine.txt`에 적힌 id만 다시 돌린다.
8. **로컬 main과 origin/main이 갈라졌다.** 팀은 origin에서 PR squash 병합으로 옮겼고 로컬 main에만 있는 커밋이 264개다. `land.py`는 로컬 main만 안다.

### Decision

1. **착지한 깨끗한 워크트리는 1시간 뒤 누구나 치운다.** 손실 없는 청소(`prune --apply`)는 브랜치가 `main`에 들어갔고, 그 브랜치 reflog에 자기 커밋(`commit`으로 시작하는 항목)이 있고, 깨끗하고, 잠기지 않았고, 캐시가 아닌 gitignore 파일이 없고, 1시간(`worktree_rules.LANDED_IDLE_HOURS`) 쉰 워크트리를 소유자와 상관없이 지운다. 착지한 것은 잃을 것이 없기 때문이다. 72시간은 착지 증거가 없는 것(방금 만들어 커밋이 없는 워크트리 포함), 더러운 것, 미병합인 것에만 남는다. `--idle-hours`가 1시간보다 짧으면 그 값을 쓴다. 호출한 쪽 자신의 착지한 워크트리는 D-761대로 기다리지 않는다.
2. **orphan은 내용을 보여 주고, 손실 없이 치운다.** `status`의 `orphan` 행은 내용 요약을 붙인다(`empty`, `only caches and .omc/state (N files)`, `N files, X MB to archive`). 캐시 판정은 D-761 6항과 같다(`.omc/state/` 포함, `.omc/`의 다른 파일은 캐시가 아니다). `prune --apply`는 1시간 쉰 orphan을 누가 돌려도 다음처럼 치운다.
   - 파일이 없거나 캐시와 `.omc/state`만 있으면 지운다.
   - 그 밖의 파일이 있으면 Python `zipfile`로 `$ROSY_SCRATCH/worktree-orphans/<이름>-<날짜>.zip`에 보관한다(캐시는 넣지 않는다. 같은 이름이 있으면 `-2`, `-3`). 보관 파일을 다시 열어 `testzip()`이 깨끗하고 멤버 목록이 보관하려던 파일과 같을 때만 디렉터리를 지운다. 확인이 실패하면 디렉터리를 남긴다. `tar`는 쓰지 않는다.
   - `ROSY_SCRATCH`가 없으면 실험실 PC의 `X:\DevTemp`를 쓰고, 둘 다 없으면 파일이 있는 orphan은 남긴다.
   - 지우기 직전에 디렉터리를 다시 읽어 보관할 파일 목록이 처음과 다르면 남긴다. Windows의 읽기 전용 파일(git 객체)은 쓰기 권한을 주고 다시 지운다.
3. **옛 이력 브랜치(`stale-history`).** 브랜치의 자기 커밋 가운데 `main`에 없는 것이 2,000개(`STALE_COMMITS`)를 넘거나, `main`과의 merge-base가 이력 재작성 기준(`REWRITE_BASE` `ad86fca808`, 그 커밋 시각 `REWRITE_TIME`) 이하이거나, 공통 조상이 없으면 `stale-history`다. `status`는 그 판정과 이유를 보이고, 병합·착지하지 말고 필요한 것을 `main`에서 새 브랜치로 다시 만들라는(D-172) 경고를 찍는다. 청소는 `--snapshot --all`로도 이 워크트리를 지우지 않는다. 사람이 보관 태그를 만든 뒤 치운다. `new --from <ref>`(기본 `main`)는 그런 ref에서 만들지 않는다. `tools/land.py`는 그런 브랜치를 착지하지 않는다(라운드 전에 멈춘다).
4. **`landed-dirty`.** 브랜치가 `main`에 들어갔고(1항의 착지 증거가 있고) 워크트리에 미커밋 파일이 있으면 `landed-dirty`다. `status`는 소유자에게 이 워크트리에서 계속 일하지 말고 `python tools/worktrees.py new`로 새 워크트리를 만들어 옮기라는 경고를 찍는다. 손실 없는 청소는 지우지 않는다. `--snapshot`은 `needs snapshot`과 같이 다룬다(소유자 본인, 또는 `--all`, 72시간, `refs/wip`).
5. **소유자.** `new`는 D-761처럼 git 신원과 환경의 세션 id를 적고, `--owner "<누구>"`가 있으면 그것을 적는다(빈 값은 거절). `status`는 소유자 기록이 없거나 `<>`처럼 빈 신원이면 `unknown`이라고 적는다. 청소의 안내 문구도 `unowned` 대신 `unknown`을 쓴다.
6. **상한에서 이름을 댄다.** `new`가 상한으로 거절하면 지금 누구나 치울 수 있는 워크트리를 하나씩 이름, 판정, 소유자와 함께 적고(`removable now by anyone: <이름> (...)`), 그 전부를 치우는 명령 하나를 적는다. 소유자만(또는 `--snapshot --all`로 사람·디스패처만) 치울 수 있는 것도 이름과 소유자를 적는다.
7. **부하성 실패 재실행(`LOAD-FLAKY`).** `land.py`는 `known_failures` 비교에서 NEW가 나온 invocation마다, NEW id가 1~5개(`MAX_RERUN`)이고 안전 루트 아래가 아니면 각 id를 따로 하나의 invocation으로 시험 PC에서 한 번씩 다시 돌린다(같은 `remote_pytest.run` 호출 안에서 id마다 invocation 하나, 브라우저 opt-in 토큰은 유지). 모두 exit 0이면 `LOAD-FLAKY <id>`로 알리고 착지를 계속한다. id와 두 로그 경로, sha, 날짜를 공통 git 디렉터리의 `rosy-flaky-candidates.txt`에 덧붙인다. 이 파일은 사람이 보고 D-762 증거 규칙에 맞으면 `test/flaky_quarantine.txt`에 옮기는 후보 목록이다. 도구가 격리 목록에 넣지 않는다. 하나라도 다시 실패하거나, NEW가 5개를 넘거나, 안전 루트(`platform_parts.yaml`) 아래 시험이면 지금처럼 멈춘다. `LOAD-FLAKY`가 있었던 착지는 pre-push가 재사용할 land record를 남기지 않는다.
   - 후보 파일이 저장소 안(`test/`)이 아닌 이유: 착지 중에 추적 파일에 쓰면 착지하는 워크트리가 더러워지고(4항의 `landed-dirty`), 시험한 커밋에 들어가지 않은 변경이 생긴다.
8. **크기 판정은 원격 시험 전에, 고치는 방법과 함께.** `land.py`는 이미 라운드마다 원격 시험 전에 `tools/harness/size_range.py <main> <후보>`를 돌린다. 실패 문구에 고치는 방법(새 모듈로 옮겨 한도 아래로, ratchet 행은 올리지 않는다)과 착지 전에 직접 확인하는 명령 `python tools/harness/size_range.py main HEAD`를 더한다.

### D-761에서 바뀌는 것

- D-761 3항의 72시간은 착지 증거가 없거나 더럽거나 미병합인 워크트리에만 적용한다. 착지한 깨끗한 워크트리는 1시간이다(1항).
- D-761 7항의 "비어 있는 orphan만 지운다"를 2항으로 바꾼다. orphan의 대기 시간도 1시간이다.
- D-761 8항 상한 거절의 소유자별 개수를 6항의 이름 목록으로 바꾼다.
- D-761 5항의 "unowned"는 "unknown"이다.
- D-761의 다른 항(관문, 부수 효과 없음, 스냅샷, 캐시 목록, 상한 60, lint 경고)은 그대로다.

### 일부러 하지 않는 것

- 착지 증거는 브랜치 reflog의 커밋이다. `fix/omx-native-ready`처럼 그 브랜치에서 한 번도 커밋하지 않은 워크트리는 새로 만들어 일하는 중인 워크트리와 구별할 수 없어 `landed-dirty`가 되지 않는다. `status`는 그 행을 `merged`, 미커밋 수와 함께 보여 줄 뿐이다.
- `stale-history`를 자동으로 보관하거나 지우지 않는다.
- 부하성 실패를 `test/flaky_quarantine.txt`에 자동으로 넣지 않는다. 그 파일은 Safety-Review가 필요한 안전 루트다.
- 실행 중인 다른 세션의 워크트리를 1시간 규칙으로 지울 수 있다. 착지한 브랜치의 워크트리를 깨끗한 채로 계속 쓸 것이면 `git worktree lock`으로 잠근다(D-761과 같다).

### 열린 항목

- **로컬 main과 origin/main(8번).** 팀은 origin의 PR squash 병합을 쓰고 `land.py`는 로컬 main에 fast-forward한다. 이 결정은 PR 절차를 바꾸지 않는다. 남은 질문: `land.py`의 기준을 `origin/main`으로 옮길지, PR 브랜치용 모드(병합·시험만 하고 fast-forward하지 않음)를 둘지, 로컬 main만의 커밋(2026-10-17에 264개)을 어떻게 끝낼지. 그 사이 `python tools/worktrees.py new ... --from origin/main`으로 PR용 워크트리를 만들 수 있다(3항의 옛 이력 검사는 그대로 적용된다).
- 2,000과 1시간은 하루 관측에서 고른 값이다. `tools/worktree_rules.py`의 상수 하나씩으로 조정한다.

### Consequences

- 상한 60은 착지한 워크트리가 한 시간 안에 비워지므로 정상 운영에서 닿기 어렵다.
- orphan 보관 파일은 `ROSY_SCRATCH` 아래에 쌓인다. 지우는 것은 사람이다.
- `status`, `new`, `land.py` 시작 알림은 미병합 워크트리마다 `rev-list --count`(최대 2,001)와 `merge-base` 두 번, 병합된 워크트리마다 reflog 읽기 한 번을 더한다. 2026-10-17 실험실 저장소(45개)에서 `status`가 약 9초였다.
- 같은 NEW가 다시 나오면 착지 하나에 원격 왕복이 한 번 늘어난다(id마다 한 invocation).

### Validation

- `test/test_worktrees_tool.py`: 착지한 남의 워크트리의 1시간 규칙과 착지 증거 없는 것의 72시간, `landed-dirty` 경고와 스냅샷, orphan 요약·삭제·보관과 보관 확인 실패 시 보존, `ROSY_SCRATCH`, `stale-history` 판정·경고·`new --from` 거절, `--owner`와 `unknown`, 상한 거절의 이름 목록.
- `test/test_land.py`: NEW가 따로 돌려 통과하면 `LOAD-FLAKY`로 착지하고 후보 파일에 적는 것, 다시 실패하거나 5개를 넘거나 안전 루트이면 멈추는 것, 옛 이력 브랜치 거절, 크기 실패 문구.
- `python tools/worktrees.py status`를 2026-10-17 실험실 저장소에서 읽기만 해서 돌렸다. 두 옛 이력 브랜치가 `stale-history`, `feat/v13-map-projected-labels`가 `landed-dirty`로 나왔다. `prune --apply`는 실제 저장소에서 돌리지 않았다.
