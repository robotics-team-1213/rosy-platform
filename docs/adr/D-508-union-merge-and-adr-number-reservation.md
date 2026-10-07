## D-508 이어 쓰는 기록 파일은 git 내장 union 머지로 합치고, ADR 번호는 `refs/adr/D-nnn` ref를 만들어 선점한다

**Status:** Accepted (2026-10-07, 사용자 결정). 사용자가 이 방향을 승인했다. 잇는 결정: [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md)(같이 하는 깃, 브랜치 이름) · [D-346](D-346-commit-time-collision-defenses.md)(커밋 시점 충돌 방어) · [D-427](D-427-platform-three-parts-middleware-operations-learning.md) 4항(푸시 순서) · [D-61](D-61-progress-logs-index.md)(모듈 harness lint).

### Context

2026-10-07 하루를 쟀다. `main`이 163번 움직였다. `docs/reference/ROSY ADR Log.md`를 고친 커밋은 54개, `tools/harness/harness.yaml`은 31개, `operations/fleet/logs.md`는 72개다. 주제 브랜치에 `main`을 머지할 때마다 ADR Log와 `harness.yaml`의 `adr_gaps`가 충돌했다. 두 파일 모두 끝에 줄을 더하는 것이 거의 전부인데, 같은 끝에 두 브랜치가 다른 줄을 더하면 git 기본 머지는 충돌로 멈춘다.

번호도 겹쳤다. D-484부터 D-507 사이에서 7개 번호를 두 브랜치 이상이 가져갔다. 기존 4단계는 사람이(또는 세션이) 세 곳을 보고 빈 번호의 다음을 고르는 절차였다. 보는 것과 쓰는 것 사이에 몇 분이 있고, 그 사이 동료가 같은 번호를 고른다. 조회는 원자적이지 않다.

### Decision

1. **union 머지.** 저장소 루트 `.gitattributes`에 git 내장 드라이버 `merge=union`을 둔다. 대상은 `docs/reference/ROSY ADR Log.md`, 모든 `logs.md`(`**/logs.md`, `docs/logs.md` 포함), `tools/harness/adr_gaps.txt`다. 내장 드라이버라 `git config` 설정이 필요 없다. 같은 자리에 두 쪽이 줄을 더하면 git이 두 쪽 줄을 다 남긴다.
2. **`adr_gaps.txt`.** `adr_gaps`를 `harness.yaml`에서 빼서 줄 단위 파일 `tools/harness/adr_gaps.txt`로 옮긴다. 한 줄이 `D-nnn 이유` 하나다. `#` 줄과 빈 줄은 주석이다. lint는 번호로 중복을 지운다(처음 줄이 이긴다). 이행 기간에는 `harness.yaml`의 `adr_gaps`도 계속 읽는다.
3. **번호 선점 도구.** `python tools/harness/adr_reserve.py next "<주제>"`가 번호를 고르고 바로 `refs/adr/D-nnn` ref를 만든다. 고르는 기준은 모든 로컬 브랜치 역사의 `docs/adr` 파일과 Log 행·gap 줄, 모든 워크트리의 같은 파일(미추적 포함), 이미 있는 `refs/adr/D-*` 가운데 가장 큰 번호의 다음이다. ref는 `git update-ref <ref> <HEAD> 0000…`(이전 값이 "없음"일 때만 성공)으로 만든다. 모든 워크트리가 `.git` 하나를 같이 쓰므로 같은 ref를 두 세션이 만들 수 없다. 지면 다음 번호로 다시 한다. 찍힌 번호를 쓴다. `list`는 선점 목록과 이유를, `release D-nnn`은 선점 해제를 한다.
4. **lint.** `refs/adr/D-nnn`이 있는 번호는 빠져 있어도 정당한 gap으로 본다. ADR 파일과 Log 행이 브랜치에 들어오면 ref는 상관이 없다(남아도 lint 오류가 아니다). Log 행 순서는 원래 검사하지 않았고 계속 검사하지 않는다.
5. **4단계 새 절차.** `AGENTS.md` 「같이 하는 깃」 4번, `docs/reference/shared-checkout.md` 같은 절, `rosy-land-on-main` 스킬의 ADR numbers를 이 도구로 바꾼다.

### Consequences

- union은 줄을 겹치거나 순서를 바꿀 수 있다. gap 줄 중복은 lint가 지운다. Log 행이 번호 순서가 아니어도 lint는 통과한다. 같은 번호의 Log 행이 둘이면 D-346의 중복 행 검사가 그대로 잡는다. 그때는 손으로 하나를 지운다.
- union은 이어 쓰기에만 맞다. 이 파일들에서 기존 줄을 고치거나 지우는 변경은 같은 줄을 고친 다른 쪽과 섞여 엉뚱한 결과를 낼 수 있다. 그런 변경은 머지 뒤 `git diff`로 결과를 확인하고 lint를 돌린다. 충돌 표시 없이 섞이므로 lint의 중복 행·중복 항목 검사가 마지막 그물이다.
- 생성 파일(모듈 `index.md`, `STATUS.md`)은 union 대상이 아니라 계속 충돌한다. 충돌하면 `python tools/harness/rosy_harness.py generate`로 다시 만든다.
- BOM과 CRLF: 저장소는 LF로 저장하고 `core.autocrlf=true` 작업 사본은 CRLF다. 머지는 저장소 형태에서 일어나고 첫 줄의 BOM은 두 쪽 공통이라 그대로 남는다. 시험으로 확인했다.
- `refs/adr/*`는 로컬 ref라 push 되지 않는다. 다른 PC의 세션과는 이 도구로 겹침을 막지 못한다. 그 경우는 이전처럼 Log 행 커밋 순서와 lint가 잡는다.
- 선점만 하고 쓰지 않은 번호는 ref로 남는다. 버린 번호는 `release`로 지우거나, 다른 ADR이 그 위 번호로 들어왔다면 `adr_gaps.txt`에 이유와 함께 적는다.

### Validation

- `git check-attr merge -- "docs/reference/ROSY ADR Log.md" docs/logs.md operations/fleet/logs.md tools/harness/adr_gaps.txt`가 모두 `union`이다.
- `test/test_harness_contracts.py`: 임시 저장소에서 두 브랜치가 BOM·CRLF Log에 서로 다른 행을 더한 뒤 `git merge`가 충돌 없이 두 행을 남긴다. gap 파일 중복 제거와 형식 오류, 선점 ref의 gap 인정, `adr_reserve next`의 기준 번호, 선점 충돌 뒤 다음 번호, `release`를 시험한다.
- `python tools/harness/rosy_harness.py lint`가 오류 0이다.
