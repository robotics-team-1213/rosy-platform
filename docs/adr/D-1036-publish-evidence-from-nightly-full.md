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
