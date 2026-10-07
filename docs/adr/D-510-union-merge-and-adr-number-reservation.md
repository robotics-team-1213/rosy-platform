## D-510 한 줄이 한 기록인 이어 쓰기 파일(ADR Log, adr_gaps.txt)은 git 내장 union 머지로 합치고, ADR 번호는 `refs/adr/D-nnn` ref를 만들어 선점한다

**Status:** Accepted (2026-10-07, 사용자 결정). 사용자가 이 방향을 승인했다. 이 결정은 처음 D-508로 선점했지만, 그 사이 동료 세션이 도구 없이 main에 다른 D-508(제어 고리)과 D-509를 넣어 `adr_reserve.py next`가 고른 D-510으로 옮겼다. 독립 리뷰(2026-10-07)에 따라 `logs.md`를 union에서 빼고, 로컬 선점 ref를 lint gap으로 보지 않게 고쳤다. 잇는 결정: [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md)(같이 하는 깃, 브랜치 이름) · [D-346](D-346-commit-time-collision-defenses.md)(커밋 시점 충돌 방어, 이 ADR이 4항을 개정) · [D-427](D-427-platform-three-parts-middleware-operations-learning.md) 4항(푸시 순서) · [D-61](D-61-progress-logs-index.md)(모듈 harness lint).

### Context

2026-10-07 하루를 쟀다. `main`이 163번 움직였다. `docs/reference/ROSY ADR Log.md`를 고친 커밋은 54개, `tools/harness/harness.yaml`은 31개, `operations/fleet/logs.md`는 72개다. 주제 브랜치에 `main`을 머지할 때마다 ADR Log와 `harness.yaml`의 `adr_gaps`가 충돌했다. 두 파일 모두 끝에 줄을 더하는 것이 거의 전부인데, 같은 끝에 두 브랜치가 다른 줄을 더하면 git 기본 머지는 충돌로 멈춘다.

번호도 겹쳤다. D-484부터 D-507 사이에서 7개 번호를 두 브랜치 이상이 가져갔다. 기존 4단계는 사람이(또는 세션이) 세 곳을 보고 빈 번호의 다음을 고르는 절차였다. 보는 것과 쓰는 것 사이에 몇 분이 있고, 그 사이 동료가 같은 번호를 고른다. 조회는 원자적이지 않다.

### Decision

1. **union 머지는 한 줄이 한 기록인 파일에만 쓴다.** 저장소 루트 `.gitattributes`에 git 내장 드라이버 `merge=union`을 둔다. 대상은 `docs/reference/ROSY ADR Log.md`와 `tools/harness/adr_gaps.txt` 두 개다. 내장 드라이버라 `git config` 설정이 필요 없다. 같은 자리에 두 쪽이 서로 다른 한 줄 기록을 더하면 두 줄이 다 남는다.
2. **`logs.md`는 union이 아니다.** union은 두 쪽이 똑같이 더한 줄을 하나로 합친다. 여러 줄짜리 `logs.md` 항목 두 개가 `- 결정: 없음`, `- 교훈: 없음`처럼 같은 줄로 끝나면 그 줄과 빈 줄이 한쪽에서 사라지고, lint는 그것을 잡지 못한다. 그래서 `logs.md` 충돌은 그대로 드러나게 둔다. 풀 때는 두 쪽 항목 블록을 통째로 이어 붙인다.
3. **`adr_gaps.txt`.** `adr_gaps`를 `harness.yaml`에서 빼서 줄 단위 파일 `tools/harness/adr_gaps.txt`로 옮긴다. 한 줄이 `D-nnn 이유` 하나다. `#` 줄과 빈 줄은 주석이다. lint는 번호로 중복을 지운다(처음 줄이 이긴다). 이행 기간에는 `harness.yaml`의 `adr_gaps`도 계속 읽는다.
4. **번호 선점 도구.** `python tools/harness/adr_reserve.py next "<주제>"`가 번호를 고르고 바로 `refs/adr/D-nnn` ref를 만든다. 고르는 기준은 모든 로컬 브랜치와 원격 추적 ref 역사의 `docs/adr` 파일과 Log 행·gap 줄, 모든 워크트리의 같은 파일(미추적 포함), 이미 있는 `refs/adr/D-*` 가운데 가장 큰 번호의 다음이다. main의 최대 번호보다 20 넘게 큰 번호는 오타로 보고 출처와 함께 경고하고 무시한다. 가장 큰 번호의 출처도 찍는다. ref는 `git update-ref <ref> <HEAD> 0000…`(이전 값이 "없음"일 때만 성공)으로 만든다. 모든 워크트리가 `.git` 하나를 같이 쓰므로 같은 ref를 두 세션이 만들 수 없다. ref가 이미 있어서 지면 다음 번호로 다시 한다. 다른 이유로 실패하면 git의 오류를 내고 멈춘다. 찍힌 번호를 쓴다. `list`는 선점 목록과 이유를 보인다. `release D-nnn --reason "<주제>"`는 이유가 맞을 때만 선점을 푼다(남의 것은 `--force`).
5. **lint.** `refs/adr`는 로컬 ref라 CI와 다른 clone에는 없다. 그래서 lint는 선점 ref를 gap으로 보지 않는다. 선점했지만 브랜치에 ADR도 gap 줄도 없는 번호는 경고 "reserved locally (refs/adr) but not on this branch"로 알린다. 그 ADR이 이 브랜치와 같이 착지하지 않으면 push 전에 `adr_gaps.txt`에 `D-nnn 이유`를 넣는다. Log 행 순서는 원래 검사하지 않았고 계속 검사하지 않는다.
6. **D-346 4항 개정.** D-346 4항은 분기로 미리 쓰는 번호를 `adr_gaps`에 적어 선점하게 했다. 이제 선점은 `refs/adr` ref로 하고, `adr_gaps.txt`는 착지하지 않을 번호와 버린 번호만 적는다. 표에 행을 넣는 커밋이 번호를 확정한다는 나머지 내용은 그대로다.
7. **4단계 새 절차.** `AGENTS.md` 「같이 하는 깃」 4번, `docs/reference/shared-checkout.md` 같은 절, `rosy-land-on-main` 스킬의 ADR numbers, `docs/reference/team-guide.md` 3.4를 이 도구로 바꾼다.

### Consequences

- union은 줄을 겹치거나 순서를 바꿀 수 있다. gap 줄 중복은 lint가 지운다. Log 행이 번호 순서가 아니어도 lint는 통과한다.
- union은 이어 쓰기에만 맞다. 한쪽이 Log 마지막 행의 Status를 고치고 다른 쪽이 행을 더하면 union은 멈추지 않고 옛 행과 새 행을 다 남긴다. D-346의 중복 행 검사(`D-n: duplicate index row`)가 이것을 잡는다. 중복 행이 생기면 새 상태의 행을 남긴다. 기존 줄을 고친 머지 뒤에는 `git diff`로 결과를 보고 lint를 돌린다.
- `logs.md`, 생성 파일(모듈 `index.md`, `STATUS.md`)은 union 대상이 아니라 계속 충돌한다. `logs.md`는 두 쪽 블록을 이어 붙여 풀고, 생성 파일은 `python tools/harness/rosy_harness.py generate`로 다시 만든다.
- BOM과 CRLF: 저장소는 LF로 저장하고 `core.autocrlf=true` 작업 사본은 CRLF다. 머지는 저장소 형태에서 일어나고 첫 줄의 BOM은 두 쪽 공통이라 그대로 남는다. 시험으로 확인했다.
- `refs/adr/*`는 push 되지 않는다. 다른 PC의 세션과는 이 도구로 겹침을 막지 못한다. 그 경우는 이전처럼 Log 행 커밋 순서와 lint가 잡는다.
- 선점만 하고 쓰지 않은 번호는 ref로 남고 lint가 경고한다. 버린 번호는 `release`로 지우거나, 다른 ADR이 그 위 번호로 들어왔다면 `adr_gaps.txt`에 이유와 함께 적는다.

### Validation

- `git check-attr merge`가 ADR Log와 `tools/harness/adr_gaps.txt`는 `union`, `docs/logs.md`와 `operations/fleet/logs.md`는 `unspecified`다.
- `test/test_harness_contracts.py`: 임시 저장소에 저장소의 `.gitattributes`를 복사해서 시험한다. (a) 두 브랜치가 BOM·CRLF Log에 서로 다른 행을 더하면 `git merge`가 충돌 없이 두 행을 남긴다. (b) 두 브랜치가 `logs.md`에 항목을 하나씩 더하면 충돌한다. 같은 시험에서 `logs.md`를 union으로 바꾸면 같은 끝줄이 사라짐을 보인다. (c) 한쪽의 Status 수정과 다른 쪽의 행 추가를 union으로 합치면 lint가 중복 행을 보고한다. (d) gap 파일 중복 제거와 형식 오류, 선점 ref는 gap이 아니고 경고라는 것, `adr_reserve next`의 기준 번호(원격 추적 ref 포함, 출처 표시, 20 넘는 번호 무시), 선점 충돌 뒤 다음 번호, 다른 이유의 실패에서 멈춤, `release`의 이유 확인과 `--force`.
- `python tools/harness/rosy_harness.py lint`가 오류 0이다.
