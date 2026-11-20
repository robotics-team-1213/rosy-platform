## D-1061 기록은 조각으로 내고, 번호·머리 줄·CONTRACT·Log 행은 기록 봇이 쓴다(Merge Queue 충돌 제거)

**Status:** Accepted (2026-11-21, 사용자가 05:45 방향 승인(robot-7b 전달), 패널 6 판정 1단계 안 A)

잇는 결정: [D-1052](D-1052-self-review-and-zero-full-ci.md)(조각 도구·정기 접기) · [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md)(PR + Merge Queue만) · D-1054(표면별 API 버전, 미착지 브랜치 `feat/api-version-per-surface`; 이 ADR이 4·5항을 대체) · [D-510](D-510-union-merge-and-adr-number-reservation.md)(번호 선점; 이 ADR이 API 번호 부분을 대체).

### Context

모든 API PR이 같은 네 곳을 고친다. API 참조의 `**Version:**` 머리 줄, 그 아래 최신순 `### v1.N` 절, 이력 표 맨 위 행, `contract_version.py`의 `CONTRACT`이다. `logs.md` 끝 덧붙이기, 생성 `index.md`, ADR Log 행도 같다. GitHub와 Merge Queue는 `.gitattributes` merge driver를 쓰지 않는다. D-1055 뒤에는 `land_merge` 자동 해결도 돌지 않는다. 그래서 둘째 PR이 큐에서 DIRTY가 된다. D-1052 도구(`tools/new_record.py`, `refresh-generated-docs.yml`)는 main에 있었지만 아무도 쓰지 않았고 강제하는 장치가 없었다. 근거: `D:/DevTemp/pipeline-gate-1120/decision6.md`, p6-claude·p6-codex·p6-agy.

### Decision

1. **API 변경은 번호 없는 조각.** PR은 `python tools/new_record.py api --surface fleet|core|cell --slug <slug> --title ...`로 `docs/reference/api-changes/<slug>.md` 하나만 더한다. 형식은 [api-changes/README.md](../reference/api-changes/README.md)에 있다(머리말 `surface`·`kind`(additive|breaking)·`slug`·`date`·`title`·`history`·`reason`). 본문의 번호 자리는 `(v1.next)`로 쓴다. 의도한 파괴 변경은 `--kind breaking --reason ...`이며 번호 규칙은 같다.
2. **기록 봇.** `refresh-generated-docs.yml`이 main push와 하루 두 번 `new_record.py consolidate`를 돈다(concurrency 그룹 하나, 한 번에 하나). 조각을 (date, slug) 순서로 다음 번호에 매기고, 머리 줄·최신순 절·이력 행·CONTRACT를 함께 쓰고, 조각을 지운다. 로그 조각을 `logs.md`에 접고, Log 행 없는 ADR 파일에 행(최신순, 전문 링크, Status 줄)을 넣고, index·STATUS를 다시 만든다. 모두 `bot/records-refresh` PR 하나로 올린다. 끝에 엄격 lint를 돈다.
3. **이번 단계는 머리 줄 하나·CONTRACT 하나를 유지한다.** 표면은 절 제목과 이력 행에 `(Fleet)`·`[CORE]`처럼 적고 번호는 한 줄로 이어진다. `test_protocol_version_alignment.py`는 바꾸지 않는다(봇이 머리 줄·CONTRACT·이력 행을 한 번에 올린다).
4. **컷오버 규칙(lint).** 컷오버 시각은 `docs/reference/api-changes/README.md`가 origin/main에 들어온 first-parent 커밋 시각이다(이 PR 착지 시각, 손으로 정한 상수 없음). PR의 가장 오래된 자기 커밋(author date, rebase·main 병합에도 유지)이 그 뒤이면, 위 공유 줄·모듈 `logs.md`·ADR Log 행 직접 수정은 lint 오류다. 그보다 앞선 PR(#318·#281·#360·#361·#357 등)은 옛 방식으로 끝낸다. `bot/records-*` 브랜치는 예외다. 규칙은 pull_request와 로컬 실행에서만 돈다(merge group diff에는 앞 PR 변경이 섞인다).
5. **엄격도.** index.md 신선도와 'Log 행 없는 ADR'은 PR·큐·push 실행에서 경고, 봇·schedule·`ROSY_RECORDS_STRICT=1`·`bot/records-*`에서 오류다.
6. **ADR 번호 보호.** lint는 `docs/adr`에서 같은 D-번호 파일 둘을 오류로 본다. PR이 더한 D-N 파일과 다른 이름의 D-N 파일이 base 또는 origin/main에 있어도 오류다. `adr_reserve.py next`는 먼저 origin main을 fetch한다. 그다음 `git push --force-with-lease=refs/adr/D-N: origin refs/adr/D-N`(create-only)을 시도한다. 원격에 이미 있으면 다음 번호로 가고, 원격이 거부하면(룰셋·권한·오프라인) 경고만 하고 로컬 선점으로 남긴다.
7. **api_reserve.py.** 컷오버 표식이 있는 트리에서 `next`·`bump`는 "번호는 봇이 매긴다"를 알린다. 옛 PR을 위해 명령은 그대로 동작한다.

### 후속(이 ADR 범위 밖)

- **표면별 파일(D-1054 합치기).** D-1054의 앱별 `contract_version.py` 세 개와 표면별 정렬 시험을 가져온다. 봇이 표면마다 따로 번호를 매기게 한다(조각의 `surface`가 이미 있다). D-1054 4·5항(로컬 선점, `land_merge.api_version`)은 이 ADR이 대체한다.
- 2단계: 번호를 릴리스(게시) 때 매긴다.
- 3단계: PR의 OpenAPI를 main과 비교해 삭제·타입 변경을 막는다(robot-7b). `kind: breaking` 조각이 의도한 예외다.
- 4단계: 기능 유무는 capabilities로 확인한다.
- 5단계: 표면별 문서로 나눈다.

### Consequences

- 같은 표면·다른 표면 API PR 둘이 공유 줄을 갖지 않는다. 번호·CONTRACT는 봇 PR이 병합될 때까지 늦다. 번호를 읽는 코드는 CORE OpenAPI 설명문뿐이다.
- 봇 PR은 저장소 secret `RECORDS_BOT_TOKEN`(GitHub App 설치 토큰 또는 fine-grained 토큰)으로만 연다. 그 토큰으로 연 PR에서는 pull_request 워크플로(`ci-result`, `review-gate`)가 그대로 돈다. 큐에는 `tools/pr_land.py`와 같은 `gh pr merge --auto --merge --match-head-commit`으로 넣는다. `GITHUB_TOKEN`으로 연 PR에서는 어떤 워크플로도 돌지 않아 필수 검사를 채울 수 없으므로 쓰지 않는다.
- secret이 없으면 봇은 확인 모드로 돈다. 러너 안에서만 consolidate를 돌리고, 밀려 있는 변경을 job summary에 적고, 아무것도 push하지 않는다. 그때는 아무 세션이나 손으로 처리한다. origin/main에서 `bot/records-<날짜>` 브랜치를 만들고 `python tools/new_record.py consolidate`를 돈 뒤 `python tools/pr_land.py --evidence`로 올린다(절차: [api-changes/README.md](../reference/api-changes/README.md)). `bot/records-` 접두사가 컷오버 규칙 예외와 엄격 lint를 함께 준다.
- 같은 slug를 두 클론이 쓰면 add/add 충돌이 남는다(드묾, 리뷰에서 이름을 바꾼다).
- 이 ADR의 Log 행은 새 방식대로 봇이 넣는다(PR에서는 경고).

### Validation

- `test/test_records_fragments.py`: 같은 표면 조각 둘의 연속 번호, (date, slug) 순서, `(v1.next)` 치환, breaking 절, CONTRACT, 조각 삭제, 재실행 무변경. 새 PR의 공유 줄 수정 오류, 옛 PR·봇·큐 예외, 조각만 쓴 PR 통과. 컷오버 시각 계산, ADR 번호 중복·선점 충돌, 엄격도 분리, ADR Log 행 동기화.
- `test/test_land_conflict_free_records.py`: 워크플로 push 트리거와 concurrency.
