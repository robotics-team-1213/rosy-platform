## D-1036 게시 증거를 야간 FULL에서 얻는다: 야간 착지 기록, 최근 야간 조상 유지, 빨간 CI 재실행 한 번

**Status:** Proposed (2026-11-17, 착지→게시→서명 지연 개선; 사용자 승인과 첫 실제 야간 관측 전)

잇는 결정: [D-889](D-889-cicd-integration-train-scheduled-publish.md)(부록 12: 야간 FULL, 게시는 명시적 FULL 착지 기록 필요) · [D-441](D-441-site-stack-automatic-update.md)(서명 PC는 origin main의 녹색 CI만 서명).

### 문제

게시(`tools/publish_main.py`)는 브라우저 청크까지 모두 돈 명시적 FULL 착지 기록이 있는 로컬 main SHA만 올린다(D-889). 개별 착지는 이 기록을 거의 만들지 않아, 게시가 며칠씩 "게시할 것 없음"으로 멈췄다. 한편 야간 FULL(`tools/land_nightly.py`)은 같은 전체 계층을 이미 돌리지만 기록은 남기지 않았다.

### 결정

1. **야간 기록.** 야간은 main SHA를 한 번만 읽어 `affected --base <sha> --head <sha>`로 계획을 세운다(계획과 실행 사이 main 이동 경쟁 제거). G1 타이밍 전용 호출도 엄격 영수증이 깨끗하면 캐시 행으로 남긴다(`publish_evidence.clean()`이 요구). 모든 호출에 깨끗한 정확한 행이 있는 녹색 밤에만 `land_record.write(tier="full")`로 그 SHA의 기록을 쓴다. NEW가 하나라도 있으면 아무것도 쓰지 않는다.
2. **조상 창.** `publish_evidence.ancestor_rows`는 최신 녹색 야간 SHA(공유 git 디렉터리의 `rosy-nightly-green`)를 최근 20개 창 밖이어도 후보 조상에 항상 넣는다. 조상 행의 채택 규칙(D-970 3: 후보의 선택기가 그 경로에 닿지 않을 때만)은 그대로다.
3. **빨간 CI 재실행.** 서명 PC는 정확한 main의 최신 실행이 `failure`이면 run id당 한 번 `gh run rerun --failed`를 요청하고 state 파일에 기억한다. 최신 실행 규칙은 바꾸지 않는다(`merge_group` 실행은 받지 않고, 재실행이 끝나 녹색이 되기 전에는 계속 거절). 토큰에 권한이 없으면 감사 기록만 남기고 지금처럼 진행한다.

### 바꾸지 않는 것

`tools/publish_evidence.py`의 어떤 검사도 약하게 만들지 않는다. 야간 기록도 같은 `qualified` 검사(정확한 commit·tree·env·argv·log 해시, 브라우저 청크 전부, 엄격 G1 영수증)를 통과해야 한다. 서명자는 origin main과 녹색 CI 없이는 서명하지 않는다(D-441).

### 검증

`test/test_land_nightly.py`(녹색 밤의 기록이 `green_full`을 통과, NEW 밤은 기록 없음), `test/test_publish_evidence.py`(야간 조상 유지), `test/test_site_auto_sign.py`(재실행 한 번, 권한 없음, 빨강 유지)를 시험 PC에서 돌렸다. 실제 야간·GitHub 권한 아래의 동작은 아직 관측하지 않았다.

### 부록 (2026-11-18): 게시 브라우저 증거는 바뀐 범위만

**사용자 결정 (2026-11-18 밤).** 11-15부터 게시가 멈췄다. 최근 FULL 착지 기록은 모두 `publish_evidence.reason()`에서 "no opted-in canonical browser chunks"로 떨어졌다. 등록된 브라우저 묶음 전부를 도는 것은 명시적 `--tests full` 착지나 녹색 야간뿐인데, 야간은 6밤 중 5밤 빨갰고, 어디서든 브라우저 묶음 하나가 빨가면(주로 OMX) Fleet·R 게시가 함께 막혔다. 사용자는 게시 조건을 "한 SHA에서 전부 녹색"에서 "바뀐 범위가 녹색"으로 바꾸기로 했다.

1. **브라우저 범위.** 필요한 브라우저 묶음은 게시 범위 `origin/main...SHA`가 닿는 묶음이다. 착지가 쓰는 같은 대응(`land_selection.browser_tier` → `test/browser_scope.py`·`land_browser.chunks`)을 기준을 `origin/main`으로 두고 `DESCRIBE`(후보의 새 인터프리터) 안에서 계산한다. 대응 계산이 실패하면 등록된 묶음 전부를 요구한다(fail closed).
2. **기록에 없어도 된다.** 착지 기록이 그 묶음을 나열할 필요는 없다. 대신 각 묶음은 그 SHA의 행이나 닿지 않는 조상의 행(D-970 3과 같은 `land_cache.reach` 규칙)에 깨끗한 정확한 증거가 있어야 한다. 기록이 나열한 호출은 지금처럼 모두 증거가 있어야 한다.
3. **빈칸 채우기.** `python tools/publish_main.py --fill-browsers [--apply]`는 브라우저 증거만 빠진 가장 새 후보에서 빠진 묶음만 `remote_pytest`로 그 SHA에 돌리고, 통과한 것만 `land_nightly.py`처럼 `land_cache.record`로 남긴다(`land_cache.unusable`·`land_browser.vacuous` 검사 동일, exit 0만). `--apply` 없이는 돌릴 목록만 출력한다.
4. **출력.** 후보마다 이유를 지금처럼 출력하고, 필요한 브라우저 묶음 수와 증거가 있는 수를 함께 적는다(`browser chunks n/m evidenced (delta|all scope)`).

**그대로 엄격한 것.** 기록은 tier `full`과 올바른 계획이어야 하고, `DESCRIBE`가 계산한 정본 FULL 호출(`full_invocations`)을 모두 담아야 하며, 각 호출은 지금처럼 정확한 깨끗한 증거가 있어야 한다. 환경 동일성, 전용(exclusive) 검증, `clean()` 로그 규칙, 준비 후보 출처, 최종 로그 검사는 바뀌지 않는다. 야간 FULL·명시적 FULL 착지는 여전히 브라우저 전부를 돈다.

**검증.** `test/test_publish_evidence.py`의 `test_scoped_*`(브라우저 없는 범위 통과, 증거 없는 묶음 이름과 채우기, 닿지 않는 조상 증거, 대응 실패 시 전부, 정본 FULL 누락 거절)를 시험 PC에서 돌렸다. 실제 게시 실행은 아직 관측하지 않았다.

### 부록 1 (2026-11-18): 게시 증거를 앱 범위로 나눈다

사용자 승인 2026-11-18 ("끝까지 나눠라", 릴리스 분리 패널 sep-r2 A·B의 합의안, 앱 필드는 `platform_parts.yaml`의 `app:`·`affected_repo.app_of`).

**규칙.** 게시 후보 sha의 델타 `origin/main...sha`에 닿는 앱 집합을 `app_of`로 구한다(`tools/publish_scope.py`).

1. 델타가 `core`, 안전 태그 경로(`safety_review.is_safety`), 또는 선택기가 FULL로 올리는 경로(후보 체크아웃에서 `affected`가 `mode: full`)에 닿으면 위의 결정을 그대로 쓴다: 정본 FULL 기록과 브라우저 청크 전부.
2. 그 밖의 앱 델타는 후보 체크아웃에서 `rosy_harness.py affected --base origin/main --head <sha> --json`(FULL 아님)의 선택과 그 델타가 매핑되는 브라우저 청크를 필요 계획으로 삼는다. 각 호출은 sha 또는 선택기가 닿지 않는 조상에서 깨끗한 정확한 증거가 있어야 한다. 증거 판정은 `publish_evidence`의 변형·clean·reach 검사 그대로이고 두 번째 판정기는 없다. FULL 기록은 요구하지 않는다.
3. 열린 MAIN-RED(야간 FULL 또는 착지가 남긴 `land_mainred` 기록)는 그 실패 시험 파일을 소유한 앱(`app_of`)을 델타가 건드릴 때만 게시를 막는다. 다른 앱의 적색은 막지 않는다.
4. 게시 출력(stderr `[publish] scope …`, 드라이런 문구, PR 본문)에 후보마다 `apps=`, `mode=app|full`, `required=`/`evidenced=` 개수와 막힘 이유를 남긴다.
5. 앱 모드는 최신 후보 20개까지만 시도한다(후보마다 체크아웃 비용). 그 뒤는 기존 FULL 기록 규칙뿐이다.

**전역으로 남는 것.** D-430 `Safety-Review` 범위 검사, D-868 merge commit(squash·rebase 금지), 비밀값 검사, 서명기와 `ci-result`·`review-gate`. 앱 모드도 이 단계를 모두 지난다. 안전 경로 변경은 위 1항으로 FULL이다.

**검증.** `test/test_publish_scope.py`: 앱 델타가 자기 선택으로 증명됨, core·안전 경로·선택기 FULL은 FULL 유지, 다른 앱의 적색은 막지 않음, 건드린 앱의 적색은 막음. 아직 시험 PC와 실제 야간에서 관측하지 않았다.

### 부록 2 (2026-11-19): 배포되지 않는 경로는 앱 `repo`

사용자 승인 2026-11-19(앱 분리, 패널 int-r1 A·B 합의). 부록 1의 `core` 6,761개 파일 중 대부분이 문서·시험·도구여서 거의 모든 델타가 FULL로 갔다. 그래서 배포되지 않고 게시 관문도 아닌 경로에 앱 값 `repo`를 준다: `docs/`, 루트 `test/`(인프라·`test/architecture`·한 앱으로 확정할 수 없는 루트 시험; `test/learning`은 `learning`), `.claude/`, 운영자 PC에서만 쓰는 도구(`tools/validation`·`calibration`·`capture`·`device_test`·`device_twin`·`icons`·`ops`·`remote`·`ssh`). `repo`는 배포하지 않으므로 델타에 있어도 FULL을 부르지 않고 앱 집합에도 들어가지 않는다. 문서만 바뀐 델타는 앱 모드로 자기 선택(`affected`)의 깨끗한 증거만 요구한다. `core`에는 공유 실행 코드(middleware/core·contracts·shared·gateway·deploy 루트), 배포물을 만드는 도구(`tools/release`·`packaging`, OMX 셀이 실행 경로에 넣는 `tools/sim`), 관문 코드(`tools/harness`·`hooks`, `tools/` 바로 아래의 `land*`·`publish*`·`urgent_lane.py`, `.github`), `test/flaky_quarantine.txt`가 남는다. 선택기의 FULL 승격(`conftest.py`·`test/architecture/**`·`tools/remote/remote_pytest.py` 등 `FULL_TRIGGERS`)과 `safety_review.is_safety`는 바꾸지 않으므로, `repo` 안의 관문 파일을 바꾸면 여전히 FULL이다. `repo` 시험 파일의 MAIN-RED는 어느 앱 델타도 막지 않는다(부록 1에서 `core` 소유 적색이 앱 델타를 막지 않던 것과 같다). 검증: `test/test_publish_scope.py`(문서만 → 앱 모드, 문서 + `tools/land.py` → FULL), `test/architecture/test_capability_owners.py`(관문은 `core`, 배포 안 되는 경로는 `repo`).
