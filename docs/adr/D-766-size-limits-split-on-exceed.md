## D-766 줄 수 한도는 넘으면 나눈다 — 파일 600줄(웹 800), 크기 단위 10,000줄, 다시 자랄 허용(+150)은 없다

**Status:** Accepted (2026-10-15, 사용자가 "몇 줄을 넘으면 나누는 것으로 기준을 잡아라"라고 지시했고, 세 세션 검토를 반영한 개정 1이 그 기준이다). 이 ADR은 D-168 P6의 판정(`split:`/`accept:`)과 +150 재판정, D-362의 1,000줄 등급을 대체한다. 시험과 문서 변경은 7항의 조각마다 따로 착지하고, 그 전까지 지금 시험이 그대로 돈다. 개정 1은 토론 참여 세션 셋의 검토를 넣은 것이다. 바뀐 자리는 맨 끝 「개정 1」 표에 있다. 개정 2(2026-10-16, 사용자 지시)는 스크립트 `.js`/`.mjs`/`.ts`를 600줄로, 시험 파일을 1,500줄로 한다(「개정 2」).

### Context

D-168 P6은 제품 파일 600줄, 패키지 10,000줄을 예산으로 두고, 넘으면 `SIZE_VERDICTS`에 `split:` 또는 `accept:` 판정을 적게 한다. 판정 시점의 줄 수가 기준선이 되고, 그 위로 150줄(`REGROWTH_ALLOWANCE`)까지 자랄 수 있다. 1,000줄 넘는 파일은 허용이 0이다(D-362, `HARD_TIER`). 패키지 안의 하위 패키지는 `SIZE_UNITS`에 등록하면 자기 단위로 세어지고, 등록된 단위는 크기와 상관없이 늘 판정을 하나 가지며 판정값 +150이 한도다.

이 장치가 지금 만드는 문제는 다음과 같다. 숫자는 모두 main `c1def3006`에서 시험의 `_over_budget()`과 `_allowance()`를 그대로 불러 쟀다(읽기 전용).

1. **나누면 허용이 생긴다.** 새 단위마다 +150이 붙으므로 나누기가 여유를 얻는 길이 됐다. 2026-10-14와 10-15 이틀 동안 Fleet에서 새 크기 단위가 일곱 개 생겼다: `site_ui/console`, `fleet/fleet/server/ledger`(main, `docs/plans/2026-10-14-fleet-console-size-unit.md`, `2026-10-14-fleet-ledger-size-unit.md`), `site_ui/console/work`, `fleet/fleet/server/missions`, `fleet/fleet/server/work`, `fleet/fleet/server/trips`, `fleet/fleet/server/trip_checks`(착지 전 브랜치 `feat/fleet-work-read-sources`, 2026-10-15 날짜 계획 셋). 합친 한도는 그때마다 150씩, 모두 1,050줄 늘었다. 그런데도 그 브랜치 끝에서 `site_ui/console`은 한도까지 2줄, `trip_checks`는 17줄 남았다. 계획 문서는 스스로 "이 등록은 실패하는 시험을 넘기려는 것이다"라고 적는다(`2026-10-15-fleet-console-work-unit.md`).
2. **작은 단위가 큰 단위보다 더 묶인다.** 단위의 한도는 10,000줄이 아니라 판정값 +150이다. `drive/behaviors/swarm`은 949줄인데 한도가 949이고, `decision/.../deliberation/contracts`는 382줄인데 한도가 382다. 등록된 38개 단위 가운데 25개가 1,000줄 아래이고 19개가 500줄 아래다.
3. **변경마다 산수를 한다.** main의 98개 판정 가운데 22개가 한도까지 20줄 이하다(그 가운데 단위 11개). 날짜 계획은 줄 수를 판정 커밋, 브랜치 기점, 지금으로 나눠 다시 재고, "쓴 허용"과 "남은 허용"을 계산하고, 판정 문구 앞에 줄을 붙이고, 독립 재판정을 받는다. 착지 순서도 이 여유에 맞춰 정해졌다. `SIZE_VERDICTS`는 `test_module_structure.py` 2,422줄 가운데 1,836줄(137–1972행)이다. 이 시험 파일은 2026-10-14 이후 main에서만 9번 바뀌었다.
4. **판정이 실제 크기를 따라가지 않는다.** `control`은 판정 35,183에 지금 30,125다. 줄어든 5,058줄만큼 다시 자랄 수 있다. `fleet/fleet/localization`도 판정 1,707에 지금 1,267이다.

D-168은 "예산 초과를 곧바로 분리 의무로 두는 안"을 Alternatives에서 기각했다. `docking/manager.py`(그때 511줄, 단일 소유)처럼 나눌 이유가 없는 파일에 억지 경계를 만든다는 이유였다. 이 ADR은 사용자의 지시로 그 기각을 뒤집는다. 억지 경계 걱정에 대한 답은 결정 3항과 4항이다.

### Decision

1. **한도는 절대값이고 다시 자랄 허용은 없다.** 제품 파일(`.py`/`.cpp`/`.hpp`/`.sh`, D-362의 범위 그대로) 600줄, 웹 자산(`.js`/`.html`/`.css`) 800줄, 크기 단위(패키지 또는 `SIZE_UNITS`에 등록한 하위 패키지) 10,000줄이다. 이 값은 기준선이 아니라 천장이다. 판정 시점 줄 수와 +150은 없다. 줄 수는 지금처럼 물리 줄(빈 줄과 주석 포함)이고 세는 방법은 `_over_budget()` 그대로다.
2. **넘으면 나눈다.** 어떤 파일이나 단위를 한도 위로 올리는 변경은, 같은 커밋 안에서 또는 그보다 앞선 커밋으로 그것을 나눠 나온 파일과 단위가 모두 한도 아래가 되게 한다. 새로 넘는 것에 `accept`는 더 쓰지 않는다. 나누지 않는 길은 하나다: 같은 파일이나 단위 안에서 지워서 한도 아래에 머무는 것이다. 예외는 8항(안전 수정) 하나뿐이다.
   - **커밋마다 녹색이다(bisect).** 나누기 커밋은 그 커밋 하나만으로 크기 검사를 통과한다. 한도를 넘기는 커밋 뒤에 같은 브랜치의 나중 커밋으로 나누는 순서는 허용하지 않는다. 브랜치 끝만 녹색이면 그 사이 커밋에서 bisect가 크기 적색을 만난다. 2026-10-14 원장 계획(`docs/plans/2026-10-14-fleet-ledger-size-unit.md` 「순서」)은 코드 조각을 계획보다 먼저 커밋하고 "한 브랜치로 함께 착지하기 때문에만 받아들여진다"고 적었다. 이 ADR 뒤에는 그 순서가 안 된다. 검사는 7(a) 5번의 범위 검사다.
   - **압축은 나누기가 아니다.** 한도에 맞추려고 줄을 이어 붙이거나, 문장을 한 줄로 합치거나, 독스트링·주석·빈 줄을 기능 변경과 함께 지우는 것은 필요한 나누기를 미룬 것으로 본다. 검토가 거절한다. 줄 수만 줄이는 서식 정리는 기능 변경이 없는 따로 된 커밋이어야 한다. 한도의 95% 이상인 파일(570줄, 웹 760줄)과 단위(9,500줄)는 더하기 전에 나눈다.
3. **나누기의 조건(억지 경계를 막는다).** 줄 수는 언제 나눌지를 정하고, 어디서 나눌지는 정하지 않는다. 경계는 `docs/plans/2026-09-06-module-split-criteria.md`의 C1(host로 시험 못 하는 결정), C2(서로 다른 생명주기), C5(서비스 주인이 둘인 API 모듈), B(B1–B3 하위 패키지 자격) 가운데 무엇이 발화했는지로 고른다.
   - 여유를 만들려고 관련 없는 파일을 다른 폴더로 옮기지 않는다. 옮긴 묶음은 그 자체로 한 책임이어야 한다.
   - 새 단위는 모듈 독스트링(또는 `__init__.py`의 한 줄)과 그 패키지 `AGENTS.md`의 행을 가진다.
   - **새 단위의 바닥은 1,000줄이고, 부모 단위가 2,000줄 이상일 때만 건다.** 1,000줄은 한도의 10%다. 그보다 작은 조각은 넘은 패키지를 한도 아래로 되돌리지 못한다. 부모가 2,000줄 아래면 어떻게 나눠도 한쪽이 1,000줄 아래이므로 바닥을 걸지 않는다. 바닥은 새로 등록하는 단위에만 건다. 이미 등록된 작은 단위는 목록(`SMALL_UNITS`)에 그대로 두고, 바닥을 맞추려고 합치지 않는다. 절대 한도 10,000줄 아래에서 작은 단위는 단위 합계로 넘칠 일이 사실상 없다(오늘 가장 큰 작은 단위가 959줄이라 9,000줄 넘게 남는다). 넘칠 수 있는 것은 그 안의 파일(600줄)이고, 그것은 파일 나누기로 푼다.
   - **나누기로 새로 만든 파일의 바닥은 150줄이다.** 150줄 아래로 떼어 내면 옛 허용 한 번보다 적은 여유를 위해 경계를 하나 만든 것이다. 이 바닥은 시험이 어느 파일이 나누기에서 나왔는지 알 수 없으므로 검토가 본다. 이미 이름이 붙은 역할(예: 앞서 떼어 둔 mixin) 하나를 통째로 옮기는 것은 예외로 본다.
   - 독립 검토는 경계를 본다(어느 기준이 발화했는지, 옮긴 것이 한 책임인지). 줄 수 산수는 시험이 본다.
   - **순수 이동은 경계만 검토한다.** 7(a) 4번의 이동 검사가 "AST identical, only imports/paths changed"를 찍은 나누기는 검토가 경계만 본다. 동작 검토를 다시 하지 않는다. safety 태그 파일(D-430)의 순수 이동은 그 검사 결과를 인용한 짧은 `Safety-Review:` trailer로 된다. D-430 §5의 trailer 검사(`tools/harness/safety_review.py`)는 그대로 돈다. 이동 검사가 차이를 찍으면 그 나누기는 보통 변경과 같이 검토한다.
   - 어느 기준도 발화하지 않으면 그 파일이나 단위에는 더 넣지 않는다. 새 코드는 자기 책임을 가진 다른 자리에 두거나, 같은 곳에서 그만큼 지운다. `docking/manager.py` 같은 파일은 자라지 않는 한 나눌 일이 없다(4항).
4. **이미 넘은 것은 지금 줄 수로 묶는다(ratchet).** 7(a)가 착지하는 커밋에서 잰 줄 수가 그 파일·단위의 천장이 된다. 줄어들 수는 있고, 줄면 천장도 새 줄 수로 내려간다. 다시 올라가지 않는다. 그것을 키우는 변경은 먼저 그것을 나눠 절대 한도 아래로 만든다. 일부만 떼어 내면 천장이 떼어 낸 만큼 내려가므로 여유가 생기지 않는다. 같은 곳에서 더하고 지워 순증이 0 이하인 변경은 된다. 오늘 목록은 아래 「오늘 넘은 것」 표다.
   - **표는 데이터 파일이다.** 천장은 `test/architecture/size_ratchet.txt`에 한 줄에 하나(`<줄 수> <경로나 단위>`)로 둔다. 이 파일은 `tools/harness/affected_tests.py`의 `NOT_TRIGGERS`에 `tools/harness/adr_gaps.txt`처럼 넣는다. 그래서 줄 수를 내리는 변경은 FULL 착지가 아니다(`test/architecture/**`는 지금 FULL 트리거다). 크기 시험은 `GUARD_SET`에 있어 그래도 늘 돈다.
   - **값은 내려가기만 하고, 잰 값으로만 내려간다.** 검사는 표의 값이 잰 줄 수와 같고, 기점(`origin/main`과의 merge-base, merge queue에서는 그 group의 base)의 같은 행보다 높지 않다고 본다. 값을 올리거나 새 행을 더하면 적색이다. 올리려면 검사 자체(`test_module_structure.py`)를 바꿔야 한다. D-762 단계 3에서 관문 경로는 CODEOWNERS 승인을 받는다. 7(a)는 `test/architecture/test_module_structure.py`를 그 관문 경로 목록에 더하자고 제안하고, 그 추가는 D-762의 관문 변경으로 따로 승인받는다. 내리는 데는 승인이 필요 없다. 오늘 `.github/CODEOWNERS`는 `*` 한 줄이라 모든 경로가 같은 owner에게 간다. 이 구분은 단계 3이 경로를 좁힌 뒤에 뜻을 가진다.
   - **merge queue와 맞는다.** 두 PR이 같은 행을 내리면 같은 줄을 고치므로 충돌한다. 그렇지 않더라도 한 PR이 다른 PR이 전제한 줄 수를 바꿨으면 `merge_group` 실행이 합친 트리에서 다시 재고, "잰 값과 같다" 검사가 어긋남을 잡는다.
5. **없애는 것과 남기는 것.**
   - 없앤다: 판정 문구(`split:`/`accept:`)와 판정 시점 줄 수, `REGROWTH_ALLOWANCE`, `_allowance()`, 한도 아래 단위의 판정, 숫자 재판정, 날짜 계획의 기준선 표.
   - `HARD_TIER`(1,000줄, 허용 0)는 없앤다. 넘은 파일은 모두 4항에 따라 증가가 0이므로 따로 둘 이유가 없다. 새 파일은 600·800줄에서 이미 막힌다. 상수와 그것을 가리키는 살아 있는 규칙은 같은 변경(7(a))에서 지운다. 2026-10-15 `git grep -i hard_tier`와 D-362 문서의 1000줄 문구로 찾은 참조는 다음과 같다.
     - 지우거나 고친다(살아 있는 규칙): `test/architecture/test_module_structure.py`(상수, `_allowance()`, 모듈 독스트링의 "zero growth allowance above 1000", 판정 문구 안 언급, 모두 14곳), `docs/adr/D-362-per-code-type-file-size-budget.md`(제목, 표의 "파일 > 1000줄" 행, Decision 4항. "D-766이 대체한다" 한 줄과 함께), `docs/plans/2026-09-30-file-size-budget-and-refactor-queue.md`(">1000 엄격 등급" 표 행과 3항).
     - 고치지 않는다(그날의 기록): `docs/logs.md`, `deploy/logs.md`, `middleware/core/api/logs.md`, 날짜 계획 9개(`docs/plans/2026-10-01-fleet-assisted-localization-plan.md`, `2026-10-02-rosy-cell-c4-fleet-route.md`, `2026-10-11-platform-structure-migration.md`, `2026-10-12-core-native-outcome-ports.md`, `2026-10-12-deliberation-role-subpackages.md`, `2026-10-12-discord-fleet-end-to-end.md`, `2026-10-12-incident-ledger-subpackage.md`, `2026-10-14-fleet-console-size-unit.md`, `2026-10-14-fleet-ledger-size-unit.md`), `docs/validation/` 아래 5개 파일, `docs/solutions/workflow-issues/full-host-suite-per-branch-cost-hours-while-failures-sat-in-the-guard-set-2026-10-04.md`. 기록은 그때의 규칙을 적은 것이고, 지금 규칙은 D-362의 대체 줄이 가리킨다.
   - 남긴다: 시험 파일 면제(X4), 웹 800줄(D-362: 마크업 오버헤드, 웹 파일 184개의 p90이 538줄), `SIZE_UNITS`와 가장 안쪽 단위가 줄을 가져가는 셈, Fleet 서버 보관 자리 단위(`FLEET_SERVER_HOLDER_UNITS`, D-763), 운영 루트(`OPS_ROOTS`) 범위, P5의 집합 동일성.
6. **오늘 진행 중인 브랜치.** 7(a)가 착지하기 전까지는 지금 규칙이 그대로다. 그 전에 착지하는 브랜치(지금 `test_module_structure.py`를 바꾸는 진행 중 브랜치는 `feat/fleet-work-read-sources` 하나다)는 그 날짜 계획과 판정 그대로, 옛 규칙으로 착지한다. 그 브랜치가 만든 1,000줄 아래 단위(`site_ui/console/work`, `fleet/fleet/server/work`, `fleet/fleet/server/trip_checks`)는 이미 있던 작은 단위와 함께 `SMALL_UNITS`에 든다. 7(a)는 착지하는 날의 main에서 표를 다시 만든다. 7(a) 뒤에 main을 머지하는 브랜치는 `SIZE_VERDICTS` 충돌을 7(a)의 표로 풀고 자기 줄 수만 다시 잰다. 날짜 계획 문서는 기록으로 남고 고치지 않는다. 누구의 작업도 이 ADR 때문에 무효가 되지 않는다.
7. **구현 조각.**
   - (a) **시험과 검사 도구.** `test_module_structure.py` 자체를 바꾸는 변경은 이것 하나다. FULL 등급(`test/architecture/**`)이고 `tools/harness/**`도 함께 바뀌므로, 한산한 시간에 착지 창 하나를 디스패처와 잡아 한 번에 착지한다. 진행 중 브랜치는 그 전에 옛 규칙으로 착지한다(6항). 내용:
     1. `SIZE_VERDICTS`를 지우고 `test/architecture/size_ratchet.txt`(4항)를 착지하는 커밋에서 생성한다. 검사: 한도를 넘은 것의 집합이 표의 키와 같다. 값은 잰 줄 수와 같다. 값은 기점보다 높지 않고 새 행이 없다. `NOT_TRIGGERS`에 `test/architecture/size_ratchet.txt`를 더한다.
     2. 단위 바닥: 새 `SIZE_UNITS` 항목은 부모가 2,000줄 이상이면 1,000줄 이상이다. 오늘의 작은 단위는 `SMALL_UNITS` 집합(집합 동일성)에 둔다. 단위의 "분리 계획 인용" 검사는 바닥 검사로 바꾼다.
     3. 안전 초과 행(8항): `size_ratchet.txt`의 `safety <줄 수> <경로> <만료일> <커밋>` 행. 검사는 그 커밋에 `Safety-Review:` trailer가 있는지, 초과가 천장 +30줄 이하인지, 만료일이 커밋 날짜에서 7일 안인지, 오늘이 만료일을 넘지 않았는지 본다. 이 행은 4항의 "새 행 금지"의 유일한 예외다.
     4. 이동 검사(3항): 저장소에 이 일을 하는 도구는 아직 없다. `tools/harness/structure_move.py`와 `d427_move.py`는 경로를 옮기고 참조를 고칠 뿐 AST를 비교하지 않는다. `tools/harness/split_check.py <base> <head>`를 새로 둔다. 그 범위에서 지워진 최상위 `def`/`class`/대입마다 같은 이름을 새 위치에서 찾아 `ast.dump`를 비교한다. import 문, 모듈 독스트링, 경로 문자열 상수는 비교에서 뺀다. 모두 같으면 "AST identical, only imports/paths changed"를 찍고, 다르면 다른 정의 이름을 찍는다. Python만 다룬다. 웹 자산 나누기는 보통 검토다.
     5. 범위 검사(2항): `tools/hooks/pre-push`와 CI가 `safety_review.py`처럼 `BASE..HEAD`의 커밋마다 크기 검사를 돈다. 커밋마다 그 커밋이 바꾼 파일과 그 파일이 속한 단위만 `git show <커밋>:<경로>`로 잰다. 한도를 넘기는 커밋이 하나라도 있으면 적색이다.
     6. `REGROWTH_ALLOWANCE`, `HARD_TIER`, `_allowance()`를 지우고 5항의 살아 있는 참조를 같은 변경에서 고친다. 변이 증명(새 초과, 묶인 것 1줄 증가, 표 값 올리기, 표가 잰 값보다 높음, 바닥 아래 새 단위, 만료된 안전 초과, 넘긴 뒤 나눈 커밋 순서 → 적색 → 복구 → 초록)을 기록한다. 시험은 `tools/remote/remote_pytest.py`로 시험 PC에서 돌린다.
   - (b) **문서.** D-168 P6에 "D-766이 대체한다"는 한 줄, 분리 기준 문서의 X1 각주와 D-168 Alternatives 문장, `test/architecture/AGENTS.md`의 `SIZE_VERDICTS` 행을 고친다. D-362와 HARD_TIER 문서 참조는 (a)와 같은 변경에 넣는다(5항).
   - (c) **첫 강제 분리.** 묶인 것 가운데 다음에 자랄 곳을 먼저 나눈다. 한도를 조금 넘은 단위가 먼저다: `perception/front_camera/perception`(75줄 초과), `core_common`(643줄), `dashboard`(1,085줄). 각각 날짜 계획 하나와 경계 검토 하나로 한다. 이 조각들은 자라야 할 때 시작하고, 이 ADR이 일정을 정하지 않는다.
8. **안전 수정의 예외.** 묶인 파일·단위 안의 안전 수정(커밋에 `Safety-Review:` trailer가 있고 D-430의 독립 리뷰를 받은 것)은 그 천장을 최대 +30줄 넘을 수 있다. 같은 커밋이 `size_ratchet.txt`에 만료일(커밋 날짜 + 7일 이내)이 있는 `safety` 행을 더한다. 만료일까지 그 파일·단위를 절대 한도 아래로 나누고 그 행을 지운다. 만료일이 지나면 크기 검사가 적색이 된다. 안전 수정이 나누기를 기다리지 않게 하되, 예외가 자리를 잡지 못하게 하려는 것이다.

### 오늘 넘은 것

main `c1def3006`, `_over_budget()` 그대로. 이 62개가 4항의 ratchet 대상이다. 7(a)는 착지하는 날 다시 잰다.

| 패키지·단위 | 줄 수 | 한도 | 한도 아래로 가려면 나눌 줄 |
|---|---|---|---|
| `fleet`(서버·decision·discord 보관 자리, 등록 단위 제외) | 31,904 | 10,000 | 21,904 |
| `control` | 30,125 | 10,000 | 20,125 |
| `site_ui/console`(단위) | 18,082 | 10,000 | 8,082 |
| `dashboard` | 11,085 | 10,000 | 1,085 |
| `core_common` | 10,643 | 10,000 | 643 |
| `perception/front_camera/perception`(단위) | 10,075 | 10,000 | 75 |

`feat/fleet-work-read-sources` 끝(`bbf8acb33`)에서는 `fleet` 31,846, `site_ui/console` 17,717이다. 등록 단위를 모두 합친 Fleet 쪽 총합은 71,481줄이다.

파일 56개(제품 코드 1,653개 가운데 600줄 초과 47개, 웹 자산 184개 가운데 800줄 초과 9개). 경로는 colcon 루트 또는 저장소 루트 기준이다.

| 파일 | 줄 수 | 한도 |
|---|---|---|
| `perception/web/diagnostic.html` | 1857 | 800 |
| `deploy/robot/pinky_pro/native/rosy_auto_update.py` | 1591 | 600 |
| `foundation/core_common/protocol/schemas.py` | 1359 | 600 |
| `fleet/fleet/server/console/console.py` | 1325 | 600 |
| `deploy/robot/pinky_pro/native/rosy-face.py` | 1273 | 600 |
| `devices/omx/adapter/omx_adapter/action_store.py` | 1141 | 600 |
| `site_ui/console/console.js` | 1080 | 800 |
| `deploy/robot/pinky_pro/native/sync-image-layer.py` | 1023 | 600 |
| `fleet/fleet/server/ledger/task_store.py` | 1014 | 600 |
| `fleet/fleet/server/app.py` | 983 | 600 |
| `fleet/fleet/server/cell/cell_job_store.py` | 963 | 600 |
| `robot_ui/pilot/styles.css` | 956 | 800 |
| `site_ui/console/map-view.js` | 952 | 800 |
| `web/components.css` | 943 | 800 |
| `fleet/fleet/server/ledger/mission_store.py` | 936 | 600 |
| `fleet/fleet/cli.py` | 923 | 600 |
| `core/gateway/core/bridge/ros_bridge.py` | 908 | 600 |
| `robot_ui/robot/app.js` | 898 | 800 |
| `fleet/fleet/server/ledger/trip_runner.py` | 898 | 600 |
| `overhead/rosy_vision/ingest.py` | 869 | 600 |
| `site_ui/console/shared/styles.css` | 862 | 800 |
| `deploy/robot/pinky_pro/native/rosy-ssh-access.py` | 862 | 600 |
| `tools/harness/rosy_harness.py` | 858 | 600 |
| `simulation/gazebo/scripts/lane_live_view.html` | 856 | 800 |
| `drive/motion_limits/adapter/node.py` | 847 | 600 |
| `fleet/fleet/server/auth/enrollment.py` | 847 | 600 |
| `drive/behaviors/line_follow/manager.py` | 822 | 600 |
| `deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py` | 817 | 600 |
| `deploy/robot/pinky_pro/release/secret_scan.py` | 815 | 600 |
| `web/ui.js` | 814 | 800 |
| `deploy/robot/pinky_pro/sd/verify-media-readback.py` | 806 | 600 |
| `fleet/fleet/server/proposal_store.py` | 797 | 600 |
| `drive/behaviors/docking/manager.py` | 788 | 600 |
| `perception/front_camera/perception/lane.py` | 771 | 600 |
| `learning/curation/perception/review_app.py` | 756 | 600 |
| `perception/sensors/line_observation/line_observer_node.py` | 755 | 600 |
| `tools/perception/rosy_ml.py` | 749 | 600 |
| `core/events/core_events/events/audit.py` | 748 | 600 |
| `devices/omx/adapter/omx_adapter/pose_plan.py` | 728 | 600 |
| `perception/front_camera/perception/lane_bev.py` | 717 | 600 |
| `simulation/gazebo/scripts/lane_live_view.py` | 709 | 600 |
| `tools/device_twin/scenarios.py` | 703 | 600 |
| `deploy/site/rosy_model_code.py` | 698 | 600 |
| `tools/release/publish_payload_release.py` | 697 | 600 |
| `devices/omx/adapter/omx_adapter/command_owner.py` | 696 | 600 |
| `drive/behaviors/swarm/manager.py` | 691 | 600 |
| `deploy/robot/pinky_pro/release/updater.py` | 686 | 600 |
| `learning/curation/perception/lane_derived_drivable.py` | 678 | 600 |
| `robot_ui/face/emotion/info_screen.py` | 676 | 600 |
| `deploy/robot/pinky_pro/native/rosy-hw-probe.py` | 641 | 600 |
| `overhead/rosy_vision/track/background_blob.py` | 633 | 600 |
| `drive/behaviors/traffic_policy/manager.py` | 630 | 600 |
| `learning/registry/perception/deliver.py` | 629 | 600 |
| `fleet/fleet/swarm/session.py` | 628 | 600 |
| `deploy/site/rosy_site_autoupdate.py` | 616 | 600 |
| `tools/device_test/run.py` | 609 | 600 |

한도 아래의 등록 단위 36개는 판정이 없어진다. 그 가운데 1,000줄 아래 25개(브랜치가 착지하면 28개)가 `SMALL_UNITS`에 그대로 든다.

### 값의 근거

- **600·800·10,000은 그대로 둔다.** 제품 코드 1,653개의 중앙값은 113줄, p90 430줄, p99 847줄이고 600줄 초과는 47개(2.8%)다. 웹 자산 184개의 p90은 538줄이고 800줄 초과는 9개다. 패키지 27개 가운데 22개가 단위를 나누기 전 원래 합계로도 10,000줄 아래다. 한도를 올리면 넘은 목록이 짧아지지만 사용자가 요청한 것은 기준을 잡는 것이지 넓히는 것이 아니다.
- **단위 바닥 1,000, 부모 2,000 이상.** 1,000은 한도의 10%다. 1,000줄 아래 조각은 넘은 패키지를 한도 아래로 되돌리는 데 거의 기여하지 못한다. 2,000은 둘로 나눴을 때 양쪽이 바닥을 맞출 수 있는 가장 작은 부모다.
- **파일 바닥 150.** 옛 허용 한 번의 크기다. 그보다 작게 떼어 내는 것은 경계보다 여유를 사는 모양이다.
- **95% 선.** 600줄 파일의 30줄, 단위의 500줄이다. 기능 하나를 더하는 흔한 변경 크기라, 그 안쪽에서는 더하기 전에 나누는 편이 압축의 유혹을 없앤다.
- **안전 초과 +30, 7일.** 2026-10-14·15 날짜 계획에 적힌 안전·검토 반영 수정이 3–15줄이었다(예: Cell Job 상세 범위 +3, 이벤트 루프 밖 읽기 +7, D-760 4단계 약 +15). 7일은 나누기 하나를 계획·검토·착지하기에 넉넉하고 예외가 굳기 전이다.

### Alternatives

- **+150을 유지한다.** 지금의 문제(나누기가 여유를 만들고, 작은 단위가 더 묶이고, 변경마다 산수와 재판정)가 그대로 남는다. 기각.
- **한도를 올린다(예: 파일 1,000, 단위 15,000).** 목록이 짧아지지만 기준선과 +150이 남으면 같은 산수가 더 높은 곳에서 되풀이된다. 기준선을 없애면 이 ADR과 같고 값만 다르다. 값은 위 분포가 받친다. 기각.
- **나누기마다 허용을 하나만 주고 단위들이 나눠 쓴다(공유 허용).** 단위가 몇 개든 합친 한도가 늘지 않아 허용 농사는 막지만, 누가 공유 여유를 쓸지 정하는 착지 순서 조정이 생긴다. 지금 Fleet에서 실제로 일어난 일이다. 기각.
- **D-168대로 초과를 판정 신호로만 둔다.** 사용자의 지시와 반대다. `accept`가 98개 판정 가운데 73개다.
- **천장 표를 시험 파일 안에 둔다(개정 전 안).** 줄 수를 내리는 변경마다 FULL 착지가 된다. 기각, 4항의 데이터 파일로 바꿨다.
- **작은 단위를 바닥까지 합친다.** 합칠 부모가 묶여 있으면 부모가 자라 4항을 어긴다. 단위가 작아서 생기는 위험(단위 합계 초과)은 10,000줄 아래에서 사실상 없다. 기각.

### Consequences

- 묶인 큰 단위는 자라려면 진짜 분리가 먼저다. `fleet` 서버 단위(31,904)는 한 줄이라도 자라려면 21,904줄을 실제 책임 단위로 옮겨야 한다. `control`(30,125)도 같다. Fleet의 새 기능은 여유가 있는 등록 단위(예: `fleet/fleet/server/ledger` 1,871줄, `missions` 2,575줄, `trips` 2,269줄. 브랜치 기준)에 두면 된다. 그 단위들은 이제 10,000줄까지 자랄 수 있다.
- 묶인 파일 56개는 자라지 않는다. 그 파일에 기능을 더하려면 먼저 C1/C2/C5/B 경계로 600(웹 800)줄 아래까지 나눈다. 바로 쓰는 파일(`console.js`, `app.py`, `trip_runner.py`, `task_store.py`)은 곧 강제 분리가 필요하다. 순수 이동이면 검토는 경계만 본다.
- 안전 수정은 나누기를 기다리지 않는다. 대신 7일 안에 나누기가 따라온다.
- 순증 0 리팩터링(더하고 같은 곳에서 지우기)은 늘 된다. 지우기가 여유를 얻는 유일한 길이다. 압축은 그 길이 아니다.
- 위험: 억지 경계. 3항의 기준·바닥·경계 검토가 막는다. 그래도 경계가 없으면 거기에 넣지 않는다는 답이 맞다.
- 위험: 7(a) 착지 날 진행 중 브랜치의 충돌. 6항의 순서와 생성 표가 줄인다. 착지 창은 하나다.
- 위험: 이동 검사의 맹점. 이름이 바뀐 정의나 둘로 쪼갠 함수는 "identical"이 아니므로 보통 검토로 간다. 맹점은 덜 보는 쪽이 아니라 더 보는 쪽이다.
- `SIZE_VERDICTS` 1,836줄이 `size_ratchet.txt` 약 62줄과 `SMALL_UNITS` 약 28줄이 된다.

### 정한 질문

개정 전 열린 질문 셋은 토론 참여 세션 셋의 검토로 정했다. 단위 바닥은 1,000줄이고 부모 2,000줄 이상의 새 단위에만 건다(3항). `HARD_TIER`는 참조와 함께 지운다(5항). 웹 자산은 800줄을 유지한다(1항).

### Validation

이 브랜치: `python tools/harness/rosy_harness.py generate`와 `lint`(오류 0). 7(a): `test/architecture` 전체와 `tools/harness` 시험을 `tools/remote/remote_pytest.py`로 시험 PC에서 돌리고 `test/known_failures.py`와 비교한다. 7(a) 6번의 변이 증명 일곱을 기록한다. SOURCE 구조 증거이며 장치·현장 수용과 무관하다.

### 개정 1

2026-10-15. 토론 참여 세션 셋의 검토. 1, 2, 4항은 모두 동의했고 3, 5항은 조건부 동의였다. 조정자가 모은 조건 여덟을 아래 자리에 넣었다.

| 조건 | 바뀐 자리 |
|---|---|
| 1. 순수 이동은 경계만 검토, safety 파일은 짧은 Safety-Review | Decision 3항 「순수 이동」, 7(a) 4번(`split_check.py`, 기존 도구 없음을 확인) |
| 2. 단위 바닥은 새 단위와 부모 2,000줄 이상에만, 작은 단위는 합치지 않음 | Decision 3항 바닥 문단, 7(a) 2번, 값의 근거, Alternatives 마지막 |
| 3. 안전 수정 +30줄, trailer, 7일 안 나누기, 만료 뒤 적색 | Decision 8항(새로), 2항 예외 문장, 7(a) 3번, 값의 근거 |
| 4. 압축 금지, 95% 선 | Decision 2항 「압축은 나누기가 아니다」, 값의 근거 |
| 5. 나누기 커밋은 혼자 녹색(bisect) | Decision 2항 「커밋마다 녹색」, 7(a) 5번 |
| 6. HARD_TIER는 참조와 같은 변경에서 지움, 참조 목록 | Decision 5항 참조 목록, 7(a) 6번, 7(b) |
| 7. 천장 표는 `NOT_TRIGGERS`의 데이터 파일, 내리기만, 잰 값으로만, merge queue 호환 | Decision 4항 세 문단, 7(a) 1번, Alternatives |
| 8. `test_module_structure.py` 변경은 한산한 시간의 착지 창 하나, 진행 중 브랜치는 옛 규칙 | Decision 6항, 7(a) 머리 |
| Status | Proposed → Accepted, Log 행 같이 |

### 덧붙임 — 7(a) 구현 (2026-10-15)

7(a)를 만들면서 바꾸거나 정한 것이다. 결정 1–8항은 그대로다.

- **단위 목록도 데이터 파일이다.** 5항은 `SIZE_UNITS`를 시험 안에 남긴다고 했다. 구조 검토(architecture review)가 단위 등록도 FULL 착지가 되지 않게 하자고 제안해서, 단위는 `test/architecture/size_units.txt`(`<경로>` 또는 `<경로> small`)에 두고 `NOT_TRIGGERS`에 넣었다. `small` 표시가 `SMALL_UNITS`다(오늘 25개). 검사: 단위는 `__init__.py` 하위 패키지이거나 선언된 보관 자리여야 하고, 줄을 세며, 부모가 2,000줄 이상이면 1,000줄 이상이다. `small` 표시는 기점보다 늘지 않고, 1,000줄을 넘으면 지운다.
- **보관 자리 인정을 넓혔다.** `FLEET_SERVER_HOLDER_UNITS`(5항 「남긴다」) 대신 `fleet/_source_layout.py`의 `SERVER_HOLDERS`, `control/_source_layout.py`의 `PACKAGE_DIRS`/`FLAT_ROOTS`/`CONTROL_ROOTS`, 패키지 CMake의 `install(DIRECTORY …)` 폴더를 모두 보관 자리로 본다.
- **세는 규칙은 `tools/harness/size_limits.py`에 있다.** 시험과 범위 검사(`size_range.py`)가 같은 함수를 부른다. main `3906def17`에서 옛 `_over_budget()`과 같은 결과(넘은 것 62개, 단위 줄 수 같음)를 냈다.
- **기점.** `ROSY_SIZE_BASE`, `main`과의 merge-base, `origin/main`과의 merge-base 가운데 `size_ratchet.txt`가 있는 가장 새 것, 없으면 그것이 있는 가장 가까운 첫 부모 조상이다. git 기록이 없으면 시험이 실패한다(건너뛰지 않는다). 기점에 있던 `safety` 행은 바꿀 수 없다(갱신 없음).
- **순수 이동은 행을 옮긴다.** 4항의 "새 행 금지"에 예외를 하나 더 둔다. 같은 변경에서 같은 종류(파일 또는 단위)의 기점 행 하나가 없어지고 새 행이 그 값 이하이면 이름 바꿈으로 본다. 묶인 파일(예: `proposal_store.py` 797줄)을 새 보관 자리로 옮기는 순수 이동이 이 길로 된다. 독립 검토가 제안했다.
- **`safety` 행에서 커밋 칸을 뺐다.** 7(a) 3번의 형식은 `safety <줄 수> <경로> <만료일> <커밋>`이지만, 행을 더하는 커밋은 자기 해시를 적을 수 없다. 형식은 `safety <줄 수> <경로> <만료일>`이고, 검사가 `git log -S`로 그 행을 더한 커밋을 찾아 trailer와 날짜를 본다.
- **범위 검사(7(a) 5번).** `tools/harness/size_range.py BASE HEAD`는 커밋마다 git으로 트리를 재고 그 커밋의 표와 비교하며, 그 커밋이 건드린 파일·단위·행만 보고한다. `tools/hooks/pre-push`와 CI(Safety-Review 단계 옆, 같은 범위)가 돌린다. `tools/land.py`(588줄)에 걸면 600줄을 넘으므로 걸지 않았다.
- **이동 검사(7(a) 4번).** `split_check.py`는 바뀐 `.py` 파일의 정의를 `ast.dump`로 비교하고(한 기점 파일에서 온 정의는 순서도 같아야 한다), 문자열 상수는 이름별로 값이 같아야 하며(경로 모양만 바뀔 수 있다), import는 이름 → 대상으로 비교한다(새 대상은 옮긴 파일 집합 안만). `.py`가 아닌 파일이 바뀌면 순수 이동이 아니다.
- **변이 증명(7(a) 6번)은 `test/test_size_limits.py`다.** 새 초과, 묶인 것 1줄 증가, 표 값 올리기, 표가 잰 값보다 높음, 새 행, 바닥 아래 새 단위, 만료된·trailer 없는·+30 넘는 안전 초과, 넘긴 뒤 나눈 커밋 순서가 각각 적색이다.
- **관문 경로 제안(4항)은 아직이다.** `test_module_structure.py`와 `tools/harness/size_limits.py`를 D-762 단계 3 관문 목록에 더하는 것은 따로 승인받는다.

### 덧붙임 — 세지 않던 루트와 `.kt` (2026-10-15)

modularization 계획의 열린 항목(검토 지적 8)을 닫는다. 결정 1–8항은 그대로다.

- **모든 생산 코드를 센다.** colcon 루트와 운영 루트 아래 추적되는 코드 파일(`.py`/`.cpp`/`.hpp`/`.sh`/`.kt`, `.js`/`.mjs`/`.ts`/`.html`/`.css`)은 패키지, 단위, 운영 루트 가운데 하나가 센다. `test_every_product_code_file_is_measured`가 이것을 보고, 예외는 `SIZE_UNMEASURED`(이유 필수, 오늘 비어 있다)다.
- **Kotlin은 600줄이다.** 1항의 제품 파일 한도를 그대로 쓴다. `.mjs`/`.ts`는 웹 자산(800줄)이다.
- **Fleet 보관 자리는 `fleet/_source_layout.py`의 `SOURCE_ROOTS`와 같다.** `operations/situation`(운영 루트에서 옮김)과 `operations/site_execution`을 더했고, 시험이 두 목록이 같은지 본다. 두 폴더는 자기 단위(`situation` 1,446줄, `site_execution` 1,012줄, 바닥 1,000 이상)로 등록해 `fleet` 행(17,788)이 그대로다.
- **package.xml 없는 루트는 패키지처럼 센다.** `size_limits.STANDALONE`: pyproject 배포 11개(`contracts/learning`·`motion`·`skill`, `integrations/robots/omx`, `middleware/devices/omx/agent`, `middleware/robot_execution/local`, `middleware/skills/api`·`manipulation`, `operations/apps/fleet`, `operations/processes/palletizing`, `operations/world`)와 Gradle 앱 `operations/site_ui/cam`(`rosy-cam` 9,964줄, 95% 선 위라 더하기 전에 나눈다). `operations/signal_observation`(파일 하나)은 운영 루트다. 운영 루트는 웹 자산도 800줄로 잰다(`learning/curation/perception/review_app_web`).
- **처음 잰 것의 행은 이 변경에서만 새로 생긴다.** 4항의 "새 행 금지"에 대한 한 번의 예외다. 이 변경으로 처음 잰 파일 가운데 한도를 넘은 것은 `site_ui/cam/.../camera/CameraController.kt` 791줄 하나이고, `size_limits.COVERAGE_ROWS`에 그 값으로 적어 새 행을 허용한다. 그 값 위의 새 행은 적색이고, 목록에 더하려면 검사 자체를 바꿔야 한다(4항). 행이 기점에 들어간 뒤에는 보통 행처럼 내려가기만 한다.

### 개정 2 — 스크립트 600, 시험 파일 1,500 (2026-10-16)

사용자가 "800줄은 너무 긴 것 같다. 600줄이나 몇백 줄로 하면 얼마나 더 리팩토링해야 하는지 보고, 과하지 않은 수준으로 규칙으로 처리하자"고 지시했다. 엄격 측과 실용 측 두 세션이 한 번씩 반박하는 토론을 했고, 조정자가 남은 쟁점 하나를 정했다. 1–8항의 나머지는 그대로다(커밋마다 녹색 2항 포함).

| 대상 | 개정 전 | 개정 2 | 새로 묶인 것 |
|---|---|---|---|
| 제품 코드 `.py`/`.cpp`/`.hpp`/`.sh`/`.kt` | 600 | 600 | 없음 |
| 스크립트 `.js`/`.mjs`/`.ts` | 800 | **600** | 6개 |
| 마크업 `.html`/`.css` | 800 | 800, `.html` 안 `<script>` 합계는 **600** | 없음(`diagnostic.html` 1,857줄 가운데 스크립트 1,289줄, 이미 묶임) |
| 시험 파일(`test`/`tests` 폴더 아래, 브라우저 시험 포함) | 세지 않음(5항 X4 면제) | **1,500** | 9개 |
| 경고(400줄 등) | 없음 | 두지 않는다 | — |

- **값의 근거.** 2026-10-16 `git ls-files` 기준이다. 제품 코드를 500으로 내리면 116개, 400으로 내리면 212개가 묶인다. 300–600줄 파일의 10-01 이후 커밋 수 중앙값은 2이고 300줄 아래는 1이다. 그래서 더 내릴 근거가 없다. 600 아래로 내리면 이미 2항이 금지한 압축(`3c3ff0bc2` "one split literal joined", `6d3d5fc1c` "net zero")만 늘린다. 600–800줄 웹 파일 8개 가운데 6개가 JS 로직이다. CSS는 1개뿐이고 결합된 제어 흐름이 없다. 시험 파일은 1,000줄 이상 27개가 10-01 이후 평균 20.1번 바뀌었다(300줄 아래는 3.4번). 그러나 그 27개를 묶으면 회귀 시험 하나를 더할 때마다 먼저 나눠야 한다. 이 27개는 14일 동안 559번 바뀌었다. 1,500은 가장 큰 9개(3,884·3,059·3,049줄 포함)만 묶고 1,000–1,500줄의 18개는 둔다.
- **경고는 두지 않는다.** 400줄을 넘는 제품 파일이 이미 212개라 거의 모든 변경에 경고가 뜬다. 나누기 전 확인은 95% 선(2항)이 맡는다. 스크립트 570, 시험 1,425다.
- **큰 표는 데이터 파일로 옮긴다.** 면제하지 않는다. `SIZE_VERDICTS`(2,422줄 → 약 530줄)와 `tools/harness/fleet_test_seconds.json`이 그 예다. 검토가 본다.
- **처음 묶이는 15개 행.** 이 변경에서만 새 행이 된다. `size_limits.COVERAGE_ROWS`에 그 값으로 적었다(덧붙임 「세지 않던 루트」와 같은 길). 시험 파일 키는 저장소 기준 경로다. 시험 줄은 패키지·단위 합계에 들지 않는다.
- **열린 질문(정하지 않음).** 2항 「커밋마다 녹색」의 비용이 토론에서 드러났다. `97d4eee71`은 포트 커밋들이 각자 행을 넘어서 브랜치 18개를 한 커밋으로 합쳤고, 그 결과 bisect 단위를 잃었다. 2026-10-16에는 602줄 중간 커밋 하나 때문에 착지를 다시 짰다. 브랜치 끝 기준으로 바꿀지는 이 개정에 넣지 않는다. 개정 1의 조건 5를 뒤집는 일이라 사용자가 따로 정한다.
- **구현.** `tools/harness/size_limits.py`(`SCRIPT_SUFFIXES`, `INLINE_SCRIPT_LIMIT`, `TEST_LIMIT`, `is_test`, `inline_script_lines`)를 바꿨다. `size_range.py`는 커밋의 규칙이 개정 2 이전이면 옛 호출을 쓴다. 시험 구조 검사는 루트 `test/`도 잰다. 변이 증명은 `test/test_size_limits.py`의 두 시험이다.

**References:** D-168(P6, Alternatives), D-362, D-430(§5 `Safety-Review:`), D-436(`GUARD_SET`, FULL 트리거), D-753, D-762(단계 3 CODEOWNERS, `merge_group`), D-763, [module split criteria](../plans/2026-09-06-module-split-criteria.md), [file size budget](../plans/2026-09-30-file-size-budget-and-refactor-queue.md), `docs/plans/2026-10-14-fleet-console-size-unit.md`, `docs/plans/2026-10-14-fleet-ledger-size-unit.md`, `test/architecture/test_module_structure.py`, `tools/harness/affected_tests.py`, `tools/harness/safety_review.py`.
