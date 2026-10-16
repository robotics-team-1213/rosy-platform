## D-762 main으로 가는 길은 pull request와 merge queue 하나다 — 공유 로컬 main은 단계를 밟아 없앤다

**Status:** Accepted (2026-10-14, 사용자 결정). 승인된 것은 Decision 1–4와 단계의 순서다. 단계마다의 적용은 따로 승인받는다. GitHub 설정(ruleset, merge queue, auto-merge, CODEOWNERS, 계정 권한)은 그 단계를 적용할 때 사용자가 그 자리에서 "적용"이라고 말한 뒤에만 바꾼다. 이 ADR은 문서만 바꾼다. 도구, 워크플로, GitHub 설정은 바꾸지 않았다.

잇는 결정: [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md)(같이 하는 깃) · [D-427](D-427-platform-three-parts-middleware-operations-learning.md) 4항(push 순서) · [D-436](D-436-change-scoped-test-tiers.md)(시험 범위, `ci-result`) · [D-510](D-510-union-merge-and-adr-number-reservation.md)(union 머지, ADR 번호) · [D-553](D-553-cd-speed-parallel-build-and-test-pcs.md)(CD, 시험 PC) · [D-584](D-584-tests-never-run-on-operator-laptop.md)(이 ADR이 범위를 좁힌다) · [D-548](D-548-device-dev-mode-marker.md)(개발 모드 표식). 관계는 아래 표에 있다.

### Context

실험실 PC 한 대의 체크아웃 하나를 여러 에이전트 세션이 같이 쓴다. 착지는 그 PC의 로컬 `main`에 `tools/land.py`로 한다(`git merge main`, lint, 변경 범위 시험, `--ff-only`). `origin/main`은 관리자 계정이 그 로컬 `main`을 직접 push해서 움직인다.

2026-10-13과 10-14에 잰 것과 본 것:

- 로컬 워크트리 279개, 로컬 브랜치 1,246개.
- 폴더 구조 변경 하나가 로컬 `main`에 착지한 뒤 `main`에서 시험 약 50개가 몇 시간 동안 실패했고, 그동안 모든 세션의 착지가 막혔다. `tools/land.py`는 선택기가 FULL로 올리면 가드와 대응 묶음만 돌리고 "the FULL tier is still owed to CI"를 찍은 뒤 착지한다(`select`). 이 착지가 그 경로를 탔다고 보지만, 실제로 FULL로 올라갔는지는 기록으로 확인하지 못했다(「확인하지 못한 것」 4).
- 착지가 서로를 무효로 만들었다. "main moved during the round"로 한 세션이 9분짜리 회차를 세 번 잃었다.
- 로컬 `main`은 `origin/main`보다 85–500 커밋 앞서 있었다. 이 ADR을 쓰는 시점에는 226 커밋 앞이다. 앞선 커밋에는 전체 시험의 증거가 없다. 전체 시험은 push 뒤 GitHub에서만 돈다.
- `main`의 최근 push 실행 100개 가운데 녹색은 56개다. 최근 실패 넷 가운데 셋은 Safety-Review trailer를 보는 `scope` 잡이었다.
- 서버 규칙은 권고였다. ruleset에 필수 검사가 없고(`ci-result`는 있지만 아무것도 요구하지 않는다), 관리자 역할은 규칙을 늘 우회한다. PR은 2026-10-08 이후 쓰이지 않았다.
- `ci.yml`에는 `merge_group` 트리거가 없다. 저장소 설정은 squash만 허용하고 auto-merge는 꺼져 있다.
- 배포 쪽은 고르지 않다. `robot_cd.py`와 현장 자동 서명은 그 sha의 `main` 실행이 녹색이어야 서명한다. `tools/release/ship.py`는 `--revision HEAD`, 곧 아무 로컬 커밋에서나 만들어 보낸다.

같은 이틀 동안 프로그램으로 된 검사(lint, 변경 범위 시험, `--ff-only`, 비밀 검사, 크기 판정)는 매번 실제 결함을 잡았다. 글로만 적힌 규칙은 지켜지지 않았다. 통합 브랜치가 노트북 한 대의 로컬 ref이고 그 문지기가 clone마다 설치하는 훅이면, 관문은 모두가 규칙을 따를 때만 관문이다.

### 토론 (2026-10-14)

- **설계 세션.** 로컬 ff 착지를 그대로 두고, push 한 번을 통합 PR 하나로 merge queue에 넣는 안(A)을 권했다. 브랜치마다 PR을 여는 안(B)은 나중으로 미뤘다.
- **검토 세션.** A는 통합 브랜치를 노트북 한 대에 남기고 clone별 훅으로 지킨다. 요구가 없애려는 "믿어야 하는 규칙"이 그대로다. GitHub은 PR을 fast-forward로 넣지 못하므로 로컬 `main`이 `origin/main`의 진짜 머지를 받아야 한다. 두 번째 사람에게는 "로컬 main"이 없다. 덧붙인 위험: 필수 검사는 그 검사가 막는 PR이 정의한다(PR이 `ci.yml`이나 선택기를 고칠 수 있다). 관리자는 여전히 적색을 머지할 수 있다. `main`이 녹색이 되기 전이나 `merge_group` 트리거가 생기기 전에 검사를 필수로 걸면 아무것도 못 들어간다. 불안정 시험 비율을 잰 적이 없다. `--bench`가 배포 구멍을 다시 연다. 이어 쓰는 파일(`logs.md`, ADR Log)은 큐에서 충돌한다.
- **UI 조각 세션.** B를 골랐다. 잃은 것은 "시험이 다 통과했는데 그 사이 main이 움직였다" 세 번이었다. 주제 묶음 PR(UI 조각 여섯 개는 결국 하나로 착지했다)과 큐가 막혔을 때의 비상구가 필요하다. 브라우저 증거는 손으로 적는 칸이 아니라 sha에 묶인 CI 검사여야 한다(`test/browser_scope.py`로 범위를 정한 Chromium 잡). 검사를 필수로 걸기 전에 불안정 시험의 격리 목록과 한 번 재시도 규칙이 있어야 한다. 시험 PC의 가용성도 빠진 위험이다. 하루 사이에 모델 PC는 메모리가 모자랐고, 현장 PC는 여유 하한 아래였고, AI PC는 SSH가 끊겼다.
- **주행·시뮬레이션 세션.** "작은 수정 → 리뷰 → 착지 → 모델 PC에서 주행"의 짧은 고리 때문에 A를 선호했다. 조건은 로컬 `main`이 origin에서 떨어질 수 있는 거리에 상한을 두는 것이다. "FULL"은 넓은 경로 일치가 아니라 실제 영향(폴더 이동, 패키징, 가드 규칙 변경)으로 좁히자고 했다. lint가 읽는 `Evidence:` 커밋 trailer(`Evidence: SIM docs/validation/<dir>`, `Evidence: none (unit only)`)와 주행 증거의 요약 형식을 제안했다. API 버전은 핀 파일 아홉 개를 손으로 고치지 말고 착지할 때 도구가 매기자고 했다(`vNEXT` 자리표시). 실험실 시험 PC는 같이 쓰는 자원이고 관문의 일부다. 주행 중인 PC로 시험을 보내면 안 된다. 여유 0인 공유 예산(Fleet 크기 판정, D-753)은 CI 관문이 되는 순간 큐를 멈추므로 재판정 절차가 관문보다 먼저 있어야 한다.
- **두 작업 세션 공통.** 증거는 기계가 읽을 수 있어야 한다. 사람이 체크하는 목록은 받지 않는다.

### Decision

1. **끝 상태는 B다.** 모든 변경은 pull request로 `main`에 들어가고, merge queue를 거쳐 auto-merge 된다. 공유 로컬 `main`은 없앤다. 한 번에 바꾸지 않고 아래 단계로 간다. 오늘의 로컬 착지(`tools/land.py`)는 날짜가 있는 이행 경로이지 목적지가 아니다.
2. **에이전트는 관리자가 아닌 write 전용 신원으로 push하고 PR을 연다.** 관리자 우회는 이름이 있고 기록이 남는 비상구로만 남긴다.
3. **관문 자체를 바꾸는 변경은 작성자가 아닌 code owner의 승인이 필요하다.** 대상 경로는 `.github/workflows/**`, `tools/harness/**`, `test/known_failures.txt`, `.github/CODEOWNERS`다. 이 결정은 owner·admin인 두 번째 신뢰할 사람이 있어야 성립한다. 그 사람은 아직 정해지지 않았다. 「열린 항목」 1이고, 정해질 때까지 단계 3을 적용하지 않는다.
4. **D-584를 좁힌다.** "노트북에서 돌리지 않는다"는 실험실 노트북과 실험실 에이전트 세션의 규칙이다. 다른 기여자는 자기 PC에서 pytest를 돌려도 된다. 변경을 `main`에 들이는 증거는 PR CI다. pre-push는 어디서나 도는 정적 부분과, 실험실 시험 PC가 설정된 곳에서만 도는 시험 부분으로 나눈다. D-584에는 같은 날짜의 「개정」 절을 붙였다.

### 단계

순서는 토론에서 정한 그대로다. "막는 것"은 그 단계가 끝난 뒤 더는 일어날 수 없는 일이다. 시간은 2026-10-14에 읽은 실행 기록이다(전체 push 실행 9–13분에 잡 17개, PR 실행 4–7분).

| 단계 | 하는 일 | 선행 조건 | 막는 것 | 비용 | 되돌리기 |
|---|---|---|---|---|---|
| 0 | 서버를 바꾸지 않는다. (가) Safety-Review trailer 누락을 pre-push와 `land.py`에서 오류로 올린다. (나) `main`을 녹색으로 만들고 밀린 커밋을 push한다. (다) `land.py`의 FULL 경로는 가드만으로 착지하지 않는다. FULL은 실제 영향(폴더 이동, 패키징·매니페스트, harness와 가드 규칙)으로 좁히고, 그 부류는 후보 커밋의 전체 CI가 녹색인 뒤에만 착지한다 | 없음 | trailer 없는 safety 커밋이 `main`에 닿는 일. 구조 변경이 전체 시험 없이 로컬 `main`에 닿는 일 | 구조 변경 착지마다 전체 CI 한 번(9–13분). 그 밖의 착지는 그대로 | 도구 커밋을 되돌린다 |
| 1 | `ci.yml`에 `merge_group` 트리거와 그 이벤트 처리(Safety-Review의 base, harness의 base ref)를 넣는다. 녹색인 sha 하나에 약 열 번 dispatch해서 불안정 비율을 재고 기록한다. 격리 목록과 한 번 재시도 규칙을 둔다 | 단계 0의 (나) | 필수 검사를 건 날 큐가 멈추는 일(트리거 없음, 불안정 시험) | 전체 실행 약 열 번(한 번만). 워크플로 변경 한 건 | 트리거를 뺀다. 큐를 켜기 전에는 아무 효과가 없다 |
| 2 | 릴리스 출처. `ship.py`는 `main`에서 그 sha 그대로 녹색인 실행이 없는 revision을 거절한다. 벤치 예외는 개발 모드 표식(D-548)이 있는 로봇만 받아들이고, 그 검사는 장치 쪽에서 한다 | 단계 0의 (나) | 시험 증거 없는 커밋이 현장 로봇에 실리는 일 | 빠른 배포가 `main` CI 한 번을 기다린다(9–13분). 장치 쪽 검사는 릴리스 한 번에 실린다 | 도구 커밋을 되돌린다. 장치 쪽 검사는 다음 릴리스로 되돌린다 |
| 3 | 한꺼번에, 하나씩은 아니다. merge queue, 필수 검사 `ci-result`, 관리자 우회를 pull-request 방식으로 축소, 관문 경로의 CODEOWNERS, 관리자가 아닌 에이전트 신원 | 단계 0과 1 완료. 야간 실행 N회 연속 녹색(N은 단계 1의 측정을 보고 사용자가 정한다). 두 번째 owner 지명 | `main`으로의 직접 push. 적색 머지. 작성자가 스스로 승인한 관문 변경 | 착지마다 큐 실행 한 번(묶음당 10–13분, 추정) | ruleset에서 필수 검사를 빼고 우회 방식을 되돌린다. 설정 변경이라 그 자리의 승인이 필요하다 |
| 4 | 두 번째 사람을 푼다. pre-push 분리. 로그 항목 하나가 파일 하나, ADR Log는 생성물. D-584 좁히기의 도구 반영 | 단계 3(PR CI가 들이는 증거가 된 뒤) | 실험실 PC에 닿지 못하는 clone의 push가 훅에서 실패해 `--no-verify`로 가는 일. 이어 쓰는 파일의 큐 충돌 | 기록 형식 이전 한 번, 생성기와 lint 변경 | 커밋을 되돌린다. Log는 다시 생성한다 |
| 5 | `tools/land.py`가 "브랜치 push, PR 열기, auto-merge 켜기, 기다리기"가 된다. 로컬 `main`을 없앤다. 주제 묶음 PR을 허용한다. API 버전은 착지할 때 매긴다 | 단계 3과 4 | "시험은 통과했는데 그 사이 main이 움직였다". 로컬 `main`과 origin의 거리 | 착지 한 번이 큐 실행만큼 걸린다. 작은 수정에서 주행까지의 고리가 그만큼 길어진다 | `land.py` 커밋을 되돌리면 로컬 착지가 돌아온다. 단계 3의 설정이 남아 있으면 push는 여전히 PR이다 |

단계별 보충:

- **단계 0 (다)의 방식은 구현에서 고른다.** 후보 브랜치에 대한 workflow dispatch를 쓴다. PR은 쓰지 않는다. 로컬 `main`이 origin보다 앞서 있는 동안 PR을 열면 그 브랜치와 상관없는, 아직 push하지 않은 커밋이 같이 공개된다.
- **단계 0 구현 기록 (2026-10-14, `feat/main-gateway-stage0`).** (가) `tools/land.py`는 착지가 `main`에 더하는 커밋에, `tools/hooks/pre-push`는 `origin/main..`push 커밋에 CI `scope` 잡과 같은 `tools/harness/safety_review.py`를 돌리고, trailer가 없으면 착지와 push를 거절한다. (다) 선택기(`tools/harness/affected_tests.py`)는 폴더를 넘는 rename, 지운 Python 모듈, `package.xml`, `_source_layout.py`, `test/architecture/**`, `test/known_failures.txt`를 FULL에 더하고, 트리거 아래의 Markdown 기록과 `adr_gaps.txt`, node 시험 파일은 FULL에서 뺀다. FULL 착지는 위 보충과 달리 workflow dispatch가 아니라 실험실 시험 PC에서 실험실 전체 티어(`full_invocations`: CI 전체 matrix를 나누지 않은 것, 루트 `test/`, 등록된 모든 모듈 묶음, 그 선택 자신의 묶음)를 돌리고 NEW 0일 때만 착지한다. 그 사이 `main`이 움직이면 다음 회차는 전체를 다시 돌리지 않고, 전체 티어를 통과한 `main`부터 새 `main`까지의 변경에 대한 선택(affected와 가드, 그 변경이 FULL이면 다시 전체)만 돌린다. 후보 브랜치를 GitHub에 올리는 것도 아직 push하지 않은 커밋을 공개하기 때문이다. 시험 PC가 없으면 착지하지 않는다(D-584). 「열린 항목」 4의 상한은 걸지 않고, 착지 뒤 로컬 `main`이 `origin/main`보다 몇 커밋, 몇 시간 앞인지만 찍는다. (나)는 이 구현에 들어 있지 않다. 예외 목록 `EXEMPT`는 `tools/harness/safety_review_exempt.json`(`commit`, `reason` 행)으로 옮겼고, 파일이 없거나 깨졌으면 검사는 exit 1로 멈춘다. 남은 우회와 한계: `--tests none`은 FULL 티어를 건너뛴다(Safety-Review는 돈다). 손으로 하는 `git merge --ff-only`는 모든 검사를 건너뛴다. 브랜치가 자기 `safety_review.py`나 예외 파일을 고치면 그 사본으로 자신을 검사한다. 이 셋을 막는 것은 단계 3(서버 쪽 필수 검사와 CODEOWNERS)이다. rename은 git 기본 유사도 50%로만 잡는다. 시험 파일만 옮기는 폴더 이동도 FULL이다. `test/learning/perception`의 `*.test.mjs` 세 파일(`web/account-session.test.mjs` 포함)은 오늘 `main` 앞의 어떤 실행기에서도 돌지 않는다. CI에는 node 단계가 없고 `land.py --node`는 `test/web`만 찾는다(알려진 빈칸). FULL의 상위 집합은 CI처럼 bringup의 lint 시험 세 개(`test_flake8.py`, `test_pep257.py`, `test_copyright.py`, `--ignore=`)를 덮지 않는다. 착지 중 `main` 변경분이 이 브랜치에서 사라진 경로(옮기거나 지운 파일)를 고쳤으면 그 회차는 변경분만이 아니라 다시 전체 티어를 돈다.
- **단계 1 구현 기록 (2026-10-14, `feat/ci-merge-group-stage1`).** `ci.yml`에 `merge_group` 트리거를 넣었다. merge group은 `pull_request`가 아니므로 전체 티어를 돈다. Safety-Review는 `merge_group.base_sha`..HEAD를 보고, harness의 `HARNESS_BASE_REF`도 같은 base를 쓴다. push, pull_request, schedule, dispatch의 값은 그대로다. `concurrency:`는 넣지 않았다. 큐나 `main` push 실행을 취소하면 그 실패가 가려지고, 워크플로 단위 그룹은 `workflow_call` 호출에도 걸린다. CI 전체 matrix가 빠뜨리던 등록 모듈 묶음 21개(시험 파일 130개)는 `modules` 러너 하나로 돈다. `harness.yaml`에서 도출하므로 새 모듈도 따라 들어온다. CI 컨테이너에서 처음 도는 묶음이라 첫 녹색 실행까지는 보고만 한다(`gating: false`). 덮지 않는 파일은 `CI_FULL_EXCLUDED`(bringup lint 템플릿 셋)뿐이다. `test/test_affected_tests.py`가 이 빈칸이 다시 열리면 실패한다. 실험실 측정으로 이 묶음은 약 35초다. 비판 경로(10–13분)는 그대로이고, 전체 실행마다 러너가 하나(잡 17개에서 18개), 잡 분이 2–3분 늘 것으로 본다. 격리 목록은 `test/flaky_quarantine.txt`다(node id, 증거, 제거 조건, 날짜, 소유자). 목록에 있는 실패만 같은 환경에서 한 번 다시 돈다. CI 시험 단계와 `tools/remote/remote_pytest.py`가 그렇게 한다. 다시 돌아 통과하면 `test/known_failures.py`가 FLAKY로 찍고, 두 번 실패하면 NEW다. 목록에 없는 시험은 다시 돌지 않는다. 불안정 비율은 `docs/validation/ci-flake-rate-2026-10-14/result.md`에 적었다. `main` sha b1e84dd79의 dispatch 다섯 번 가운데 셋이 적색이었고(60%), 실패한 시험은 셋이며 서로 달랐다. 하나는 격리했다. 안전 경로인 둘(비상정지 지연, 수동 조작 중 모드 충돌)은 격리하지 않고 소유자에게 넘겼다. 측정은 열 번이 아니라 여섯 번이다. 단계 3에 남은 것: 이 브랜치가 `main`에 들어간 뒤 `modules`의 첫 녹색과 gating 전환, 격리하지 않은 두 실패의 수정, 재측정, 그 결과를 보고 사용자가 정할 야간 연속 녹색 N, 「확인하지 못한 것」 1–3. 브라우저 시험 둘(경기 보드 320×568 복구, 콘솔 큐 ABORT 위치)은 어떤 실행기도 다시 돌리지 않는다. 그래서 목록이 아니라 그 파일의 주석에 후속 항목으로 남겼다. 검토 반영(같은 날): 재시도는 pytest가 exit 1이고 모든 실패가 목록에 있을 때만 한다. 다시 돈 실행이 exit 0이고, 모든 id가 `PASSED`이며 `FAILED`·`ERROR`가 없어야(teardown 오류 포함) 녹색이다. CI와 실험실은 같은 함수(`known_failures.should_rerun`, `rerun_passed`)로 정한다. `test/flaky_quarantine.txt`는 `platform_parts.yaml`의 `concern: safety` 루트다. 그래서 id를 더하는 커밋에는 `Safety-Review:` trailer가 필요하다. safety 루트 아래의 시험은 목록에 둘 수 없다. 단계 3의 선행 조건으로 정한다. 큐의 병합 방식은 merge commit이어야 한다. squash면 Safety-Review 범위에 PR의 trailer 달린 커밋 대신 큐의 squash 커밋이 들어간다. `modules` 러너는 2026-11-15까지 gating으로 바꾼다. `test/test_affected_tests.py`가 그 날짜 뒤에 실패한다. 단계 3 설계 항목(만들지 않음): 큐에 든 PR 하나는 전체 티어를 두 번 돈다(`merge_group`, 그리고 `main` push). 각각 잡이 약 20개라 Free 동시 한도에 닿는다.
- **단계 2의 안전한 쪽.** `main`이 적색이거나 큐가 막히면 새 릴리스가 나가지 않고, 로봇은 마지막으로 좋았던 릴리스에 머문다. 이것이 의도한 실패 방향이다. 급한 현장 수정이 막힐 수 있다는 비용은 벤치 예외가 아니라 `main`을 고치는 것(따로 정할 것 5)으로 푼다.
- **단계 3을 묶는 이유.** 큐 없이 검사만 필수로 걸면 녹색 PR 둘이 합쳐져 `main`을 깨뜨릴 수 있다. `merge_group` 트리거 없이 걸면 큐의 검사가 영원히 오지 않는다. CODEOWNERS 없이 걸면 PR이 자기를 막는 검사를 고칠 수 있다. 에이전트가 관리자 신원으로 push하는 동안에는 우회가 그대로 남는다.
- **큐의 병합 방식.** 설계 세션의 권고는 merge commit이다. squash는 커밋 sha를 바꿔서 조상 검사(D-761 제안)와 착지 기록의 sha 연결이 끊긴다. 단계 1 기록(2026-10-14): merge commit은 단계 3의 선행 조건이다(위 단계 1 구현 기록). 그때까지 저장소 설정은 squash 하나다.
- **이행 중의 로컬 착지.** 단계 5 전까지는 `tools/land.py`와 D-427 4항의 push 순서가 그대로 쓰인다. 로컬 `main`이 origin에서 떨어질 수 있는 거리의 상한은 「열린 항목」 4다.

### 따로 정할 것

여기서 풀지 않는다. 각 항목은 적힌 단계를 적용하기 전에 자기 결정(ADR 또는 이 ADR의 개정)을 갖는다. 맡는 쪽은 제안이고 사용자가 확정한다.

| # | 항목 | 정할 내용 | 맡는 쪽(제안) | 언제까지 |
|---|---|---|---|---|
| 1 | 브라우저 증거 | sha에 묶인 CI 잡. 범위는 `test/browser_scope.py`. 손으로 적는 칸은 두지 않는다 | UI 작업 세션 | 단계 3 전 |
| 2 | `Evidence:` trailer | lint가 읽는 형식과 주행 증거 요약 형식 | 주행·시뮬레이션 세션 | 단계 5 전 |
| 3 | 시험 PC 가용성 | GitHub 러너에서 도는 것과 실험실 PC에 남는 것, 기다림 상한, 우회를 승인하는 사람, 주행 중인 PC로 시험을 보내지 않는 규칙 | 디스패처 | 단계 0 (다) 전 |
| 4 | 크기 예산 재판정 | PR마다 도는 잡. 순증가가 0 이하이면 사람 없이 통과하고, 기준선을 올릴 때는 작성자가 아닌 사람의 승인. 여유 0인 예산(D-753)이 큐를 멈추지 않게 한다 | harness 담당 | 단계 3 전 |
| 5 | 적색 `main` 되돌림 | revert PR 절차서. 누가, 어떤 신호에서, 어떤 명령으로 | 디스패처 | 단계 3 전 |
| 6 | 막힌 큐의 비상구 | 누가, 얼마나 기다린 뒤에 여는지. 연 뒤에도 CI는 돈다는 것. Decision 2의 비상구 기록 형식 | 사용자 | 단계 3 전 |
| 7 | `pull_request_target` | 쓰지 않는다. 포크 PR의 코드가 저장소 비밀을 볼 수 있게 된다. 워크플로 리뷰에서 거절한다 | code owner | 단계 1부터 |
| 8 | 빌드·릴리스 워크플로 dispatch | 누가 어느 브랜치에서 돌릴 수 있는지 | 사용자 | 단계 2 전 |

### 하지 않는 것

- **모든 PR에 승인 필수.** 변경 대부분을 에이전트 세션이 만들고 사람은 적다. 시간당 다섯 번쯤인 착지가 한 사람을 기다리게 된다. 승인은 관문 경로에만 건다(Decision 3).
- **선형 이력 필수.** 큐가 merge commit을 쓰면 성립하지 않는다. squash와 rebase는 sha를 바꾼다.
- **실험실 PC를 self-hosted 러너로.** 공개 저장소라 포크 PR이 그 PC에서 코드를 돌릴 수 있다(D-553 5항과 같은 이유).
- **브랜치 이름 ruleset.** 이번 사고의 원인이 아니다. 이름은 만드는 쪽 도구가 본다(D-372, D-761 제안).
- **origin에서 ADR 번호 선점.** 관문은 merge group에서 도는 CI의 중복 lint다. 로컬 선점(D-510)은 참고용으로 남는다.

### 열린 항목

| # | 질문 | 권장 답 | 정하는 사람 |
|---|---|---|---|
| 1 | 두 번째 owner·admin은 누구인가 | 이름은 여기서 정하지 않는다. 관문 경로를 읽고 거절할 수 있는 팀원 한 명. 단계 3을 막는 항목이다 | 사용자 |
| 2 | archive 태그와 wip 스냅샷을 어디에 두는가 | 공개 origin에는 두지 않는다. 비공개 미러에 둔다. wip ref는 어떤 경우에도 공개 원격에 push하지 않는다. 지금 있는 것의 목록은 `docs/reference/held-branches.md`에 둔다 | 사용자 |
| 3 | `--bench`의 범위 | 개발 모드 표식이 있는 로봇에서만, 이유를 기록하고, 현장 수용 증거로는 쓰지 않는다 | 사용자 |
| 4 | 이행 기간에 로컬 `main`이 origin에서 떨어질 수 있는 상한 | 커밋 수와 시간 두 값으로 둔다. 숫자는 단계 0 (나) 뒤의 착지 속도를 보고 정한다(2026-10-14 기준 24시간에 122 커밋). 작성 세션의 시작값 제안은 50 커밋 또는 12시간 가운데 먼저 오는 쪽이고, 토론에서 합의한 값이 아니다 | 사용자 |

### 확인하지 못한 것

1. 무료 조직의 공개 저장소에서 merge queue를 쓸 수 있는지.
2. GitHub의 서버 쪽 머지가 `merge=union`(D-510)을 따르는지. 따르지 않는다고 보고 단계 4를 넣었다.
3. 동시 잡 한도가 두 배가 된 전체 matrix(push와 merge group)를 받아 주는지.
4. 2026-10-13의 구조 변경 착지가 실제로 FULL로 올라갔는지.

1–3은 단계 1과 3을 적용하기 전에 확인한다. 1이 "쓸 수 없다"이면 Decision 1의 끝 상태를 이 ADR의 개정으로 다시 정한다.

### 다른 결정과의 관계

| ADR | 관계 |
|---|---|
| D-372 | 브랜치 이름과 "남의 미커밋은 지우지 않는다"는 그대로다. 공유 `main` 체크아웃에 착지하는 절차는 단계 5에서 끝난다 |
| D-427 4항 | push 순서(fetch, rebase, generate, pre-push)는 단계 5까지 유효하다. 그 뒤에는 PR 브랜치의 push에만 적용된다 |
| D-436 | `ci-result`와 시험 범위를 그대로 쓴다. 단계 0이 FULL로 올리는 조건을 좁히고, 단계 3이 `ci-result`를 필수로 건다 |
| D-510 | 로컬 번호 선점은 참고용으로 남고 관문은 CI의 중복 lint다. 서버가 union 머지를 따르지 않으면 단계 4가 Log를 생성물로 바꾼다 |
| D-553 | 그 sha의 녹색 실행 뒤에만 서명하는 규칙을 `ship.py`까지 넓힌다(단계 2). 착지 기록으로 pre-push 묶음을 건너뛰는 addendum 3은 단계 5에서 PR CI로 대체된다 |
| D-584 | Decision 4가 범위를 좁힌다. D-584의 「개정」 절 참조 |
| D-753 | 여유 0인 Fleet 크기 판정은 그대로다. 그 판정이 큐를 멈추지 않도록 재판정 절차(따로 정할 것 4)가 단계 3보다 먼저 온다 |
| D-761 | Proposed. 도구(`tools/worktrees.py`)는 2026-10-14에 `main`에 들어갔다. 로컬 워크트리의 관문이다. 이 ADR은 `main`으로 가는 길의 관문이다. 서로를 대신하지 않는다 |
| D-172 | archive 태그 규칙은 그대로다. 태그를 어디에 두는지가 열린 항목 2다 |
| D-548 | 벤치 예외를 받아들이는 로봇을 가리는 데 개발 모드 표식을 쓴다(단계 2). 표식의 뜻과 권한 범위는 바꾸지 않는다 |

릴리스 출처(단계 2)는 따로 ADR로 떼지 않았다. 같은 관문의 한 단계이고, 아직 구현 결정(장치 쪽 검사의 형식)이 없어 떼어 낼 본문이 없다. 구현이 페이로드나 장치 계약을 바꾸면 그때 별도 ADR로 쓴다.

### Consequences

- 끝 상태에서는 착지 한 번이 큐 실행 한 번만큼 걸린다. 오늘은 실험실 PC에서 몇 분이다. 주행·시뮬레이션 세션의 짧은 고리는 브랜치에서의 시험과 주행으로 옮겨 가고, 착지는 그 뒤가 된다.
- 단계 3 전까지 서버는 CI를 요구하지 않는다. 그때까지 `main`의 품질은 `tools/land.py`와 pre-push, 곧 한 clone의 도구에 달려 있다. 기여 문서는 이 사실을 그대로 적는다.
- 두 번째 owner가 없으면 단계 3 이후가 모두 멈춘다. 단계 0–2는 그와 무관하게 갈 수 있다.
- 이 ADR이 Accepted라는 것은 방향과 순서가 정해졌다는 뜻이다. 어느 단계도 아직 적용되지 않았다.

### Validation

- 문서만 바꿨다. `python tools/harness/rosy_harness.py generate` 뒤 `lint`가 오류 0이다.
- Context의 숫자는 2026-10-13과 10-14에 `git`과 GitHub API로 읽은 값이고 검토 세션이 다시 확인했다. 확인하지 못한 것은 위 목록에 따로 있다.

### 2026-10-16 운영 개정 — 한 명의 GitHub 게시와 두 에이전트 검토

사용자는 GitHub에서는 한 사람이 올리고, 이곳의 작성·독립 검토 두 에이전트가 규칙에 따라 확인하는 운영을 요청했다. 이에 현재 main ruleset의 사람 승인 수를 1에서 0으로 변경했다. 필수 `ci-result`, PR 요구, squash 병합, 대화 해결 요구, 삭제·force-push 제한과 관리자 우회를 PR 경로로 제한하는 설정은 유지했다. 확인한 ruleset은 `main-protection`(24502267)이다.

현재 게시 절차의 정본은 [PR 파이프라인](../reference/pr-pipeline.md)이다. 작성자는 검토 base/head SHA와 실제 시험 결과를 주고, 다른 읽기 전용 에이전트가 검토한다. 수정 후에는 변경 범위를 다시 검토받는다. 게시 담당 한 명이 사용자에게 허용받은 push·PR·병합을 수행하고 최신 SHA의 CI 결과를 확인한다. 에이전트 검토를 GitHub의 다른 사람 승인으로 가장하지 않는다.

이 운영 개정은 위 단계 3 전체를 적용했다는 뜻은 아니다. merge queue·auto-merge와 관문 code owner·에이전트 신원 분리, 단계 4·5의 도구 전환은 후속이다. 기존 날짜의 Context·Consequences는 당시 상태 기록이며, 현재의 사람 승인 수·필수 검사·게시 방식은 이 운영 개정을 따른다. 로컬 `tools/land.py`는 계속 로컬 착지 도구이며 공개 `main`의 직접 push 경로로 쓰지 않는다.
