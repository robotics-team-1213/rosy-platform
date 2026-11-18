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

### 부록 (2026-11-19): 같은 SHA 재실행 통과는 녹색으로 친다

**사용자 결정 (2026-11-19).** 야간 FULL은 6밤 중 5밤 빨갰다. 11-18 밤의 NEW 11개는 다음 main에서 모두 통과했고(120 passed), 8번 호출은 실행마다 다른 부하 flaky 시험(station camera, config_transaction)으로 떨어졌다가 같은 SHA의 세 번째 실행에서 통과했다. 녹색 밤만 게시용 FULL 기록을 쓰므로 부하 flaky 하나가 하루 게시를 막았다.

1. **재실행 한 번.** 계층이 끝난 뒤 NEW가 있는 호출은 같은 SHA·같은 argv로 한 번 다시 돈다(로그 `nightly-<n>-rerun.txt`). 재실행이 깨끗하면(exit 0, 요약 있음, `land_cache.unusable` 통과, 전용 증거·비어 있지 않은 브라우저 실행) 그 행을 `land_cache.record`로 남기고 그 ids를 NEW에서 뺀다. 재실행도 실패하면 지금처럼 MAIN-RED다.
2. **flaky 후보.** 실패 뒤 통과한 id는 착지의 LOAD-FLAKY와 같은 후보 파일(`<git-common-dir>/rosy-flaky-candidates.txt`)에 적어 담당자가 `test/flaky_quarantine.txt` 검토를 하게 한다(이 도구는 격리 목록에 넣지 않는다).
3. **격리만 실패한 호출.** NEW 없이 격리(quarantine) 시험만 실패해 exit 1인 호출도 한 번 다시 돌려 깨끗한 행을 남긴다(11-18에는 이런 호출에 행이 없어 게시 증거가 빠졌다).
4. **기록 로그.** 게시용 `land_record.write`는 행을 만든 로그(재실행으로 기록됐으면 재실행 로그)를 적는다.
5. **상한.** 한 밤에 다시 도는 호출은 최대 `MAX_RERUNS`(8)개다. 안전 루트 아래 id가 있는 호출은 다시 돌지 않는다(D-762). `[nightly] rerun:` 요약 줄을 출력한다.

**그대로 엄격한 것.** 게시 검사(`publish_evidence`)는 바뀌지 않는다. 재실행 행도 같은 정확한 commit·tree·env·argv·log 검사를 받는다.

**검증.** `test/test_land_nightly.py`(재실행 통과 → 녹색·기록·후보, 두 번 실패 → 빨강, 격리만 실패한 호출의 재실행 기록, 상한)를 시험 PC에서 돌린다. 실제 야간 관측은 아직 없다.
