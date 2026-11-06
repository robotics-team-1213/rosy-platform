# 화면 지도 완료 후속 — 2026-11-06

## 범위와 읽는 순서

원래 30개 카드의 범위는 그대로다. 기존 [표면별 카드](surfaces.md), [당시 결과](README.md), [경합 해소](final-closure.md), [main 병합 후속](main-merge-followup.md)을 수정하거나 새 소스의 전체 통과로 소급하지 않는다. 이 날짜의 기록은 정상 병합 뒤 Fleet viewer 회귀·범위 안내·Gallery 근거와 남은 공식 수용을 추가한다. DEV 견본과 운영 제품의 수용은 구분하며 `29개 + DEV 1개`를 제품 30개 완료로 계산하지 않는다.

외부 원본의 작업공간 위치는 `Rosy/docs/workspace-records/2026-11-05/ui-map/`다. 아래 `review-reports/`와 `official-ui-*`는 그 하위 경로다. 원본의 접속값·계정·개인 경로는 이 문서에 전사하지 않는다.

## 정상 병합과 viewer 수정

정상 병합 commit 5fe2e42874f5bffd62a1348ec016bc307b43d7fc 뒤, RED commit b7cb2c24c36e0563ea5ee132bba275300c6b3972는 viewer 시험 하나를 추가했다. GREEN commit c48929874d84ec05f6f60c1dab6be680d4e18787는 `applications/fleet/web/console.js`의 manual-control reason closure 한 줄과 `index.html`의 범위 안내 한 문단만 바꿨다. RED 시험 blob은 GREEN에서도 같다. 기존 시험 함수·단언·8개 종료 조건은 보존했다.

closure는 접속 잠금의 재접속 사유, nonoperator의 기존 운영자 사유, operator의 기존 판단 순서를 유지한다. 주기적 manual 갱신과 시작/유지/정지의 공통 blocked 경로가 같은 역할 사유를 소비한다. 서버 권한·403·CORE의 최종 주행/안전 권한은 변경하지 않았다. 안내 문단은 Fleet의 선택 로봇 저속 hold 조종과 Robot 화면의 기능, 로봇 독립 비상정지·CORE 소유를 구분한다.

| 실제 실행 | 소스·run | 결과와 원본 |
| --- | --- | --- |
| viewer RED | commit b7cb2c24c36e0563ea5ee132bba275300c6b3972, AI `b7cb2c24c3-b6e994` | 1 FAIL/0 skip/NEW 1, known/flaky 0; pytest 6.40초, runner 11초. `review-reports/viewer-role-red-b7cb2c-{wrapper-receipt.json,run-1.txt}` |
| 6개 전체 파일 GREEN | commit c48929874d84ec05f6f60c1dab6be680d4e18787, AI `c48929874d-ab2457` | 160 PASS/0 skip/NEW-known-flaky 0, 기존 의존성 경고 2개; pytest 492.06초, runner 499초. `review-reports/viewer-role-green-c489-{wrapper-receipt.json,run-1.txt}` |

RED는 250ms 대기 뒤 실제 방향 버튼이 enabled여서 disabled 단언에서 실패했다. GREEN은 같은 viewer node와 기존 release/blur/selection/timeout/keyboard/cancel/hidden/pagehide 8개 종료 node를 모두 실제 PASS로 기록한다. 160개는 다음 6개 파일 전체의 수치다.

- `test/test_fleet_manual_control_browser.py`
- `operations/fleet/test/test_console_roles_browser.py`
- `operations/fleet/test/test_fleet_role_consumers_browser.py`
- `operations/fleet/test/test_start_point_browser.py`
- `test/test_fleet_console_browser.py`
- `test/test_fleet_ui_review_browser.py`

RED 원본 3,347바이트의 SHA256은 `7660a54c68afdbf18c14dce38b02d8709249f64def093becd96344263ca2e28b`, GREEN 원본 20,829바이트의 SHA256은 `e3f516146c4495409c383edab244121d66692d86a0d4ab2ee85856347dea5f87`다. 독립 실행 검토는 보존본·실제 TEMP 원본 바이트, full source·argv·run·runner/classifier 종료를 대조했다. `review-reports/viewer-role-code-review-c489.md`와 `viewer-role-evidence-review-c489.md`는 각각 코드/실행 범위 GO다. 코드 GO를 실행으로, 실행 GO를 FULL로 바꾸지 않는다.

viewer는 정상 online/MANUAL/fresh 로봇 자료와 실제 session API 형태를 사용한 fixture다. pointer·일반 Tab skip·현재 focus에서 Space를 거쳐 이동 요청 0과 오류 0을 검사한다. disabled control에 직접 focus/event를 주입하거나 active hold 도중 역할 전환을 재현한 시험은 아니다. 403 mock을 유지하지만 실제 서버의 403 실행·물리 정지를 이 시험으로 입증하지 않는다. JUnit은 요청하지 않았다.

## Gallery — 원래 DEV 계약과 제한된 기존 근거

Gallery는 원래 계획·D-129·DESIGN의 공용 부품 합성 견본/기반이다. 별도 운영 업무·장치 제어 Gallery를 새로 요구하거나 DEV라는 이유로 동작 검증을 면제하지 않는다. 실제 `shared/web/component-gallery.html`과 `/styleguide`는 관련된 별도 견본이다.

`static-final/gallery-unavailable-1440.png`는 정상 렌더된 합성 견본이다. `-unavailable-`은 공통 촬영 스크립트의 일반 파일명 접미사이며, Gallery backend 접속 실패를 관측했다는 뜻이 아니다. 촬영 commit c5142a2e20e9134f221e3369d7011b02efe9525d의 receipt는 세 폭과 page errors/blocked requests 없음·문서 폭 일치를 기록한다. 해당 1440 PNG의 SHA256은 `bc6417586fdd453be73139c62736cd906560d8515e6c7db7b1c46d656168db1e`이며 기존 `captures.sha256`과 같다. 원래 파일명·캡처·당시 기록은 보존한다.

commit 48f43d6e54a9918a2f2d89afa8ade08e8ecfd25e의 실제 opt-in `official-ui-124943-conflict/run-pre-15.txt`는 `shared/web/test/test_component_kit_browser.py`를 포함한 **13개 파일 묶음의 192 PASS/0 skip**다. Gallery 단독 192개가 아니다. pytest 479.20초와 runner wait 78/run 475초, 당시 PNG 경고 2개를 그대로 둔다. 1,013바이트 원본의 SHA256은 `5e3f19657cc606afe86f27ce9c15dffb8c649d43a0e6bb1234c5b8748a98ec15`다. quiet 출력은 파일별 수집 수/node 목록을 제공하지 않으므로 이를 별도 KIT 전용 receipt로 재작성하지 않는다. 해당 전체 gate의 이후 STOP도 성공으로 바꾸지 않는다.

`review-reports/gallery-completion-scope-note.md`는 source48→c489에서 component-kit 시험, shared manifest/41개 자산, 적용 conftest, fixture가 추출하는 Fleet link/table 입력의 동일성을 한정해 확인했다. Gallery HTML/JS/CSS는 촬영 소스부터도 같다. Styleguide의 후속 변경, 다른 12개 파일의 전체 c489 입력, 외부 pytest/Chromium package·실행 환경의 새 검증으로 확대하지 않는다. 이는 기존 DEV 구현·실제 opt-in 묶음·Gallery 소비입력 동등성의 근거다.

## 공식 수용은 아직 대기

공식 151711은 원래 UI commit 3ee26595e7aca5d189e452d5c124043229edaafc에서 요청됐지만 실제 prepared source는 commit d2bb9492b3e26a9d31e4b543045c0593a6f93a35다. 작성 시점 **FULL RUNNING**, terminal/main 수용 미완료다. c489의 160개 후속 결과는 이 frozen 실행에 포함시켜 세지 않는다.

`official-ui-151711-in-progress/receipt.json`은 native pass/cache·원본 hash·argv·환경으로 종료가 입증된 gpre 3개와 pre 1개, 별도 lint 2개만 보존했다. 2026-11-05 17:00:51 UTC wrapper checkpoint의 SHA256은 `eee3d2f5d966c4775b36fd7a371c8add9455b649ec6435a08d616ae68ec16d36`다. classifier 진행 수를 종료 파일 수나 FULL 완료로 간주하지 않으며, 원본 skip·warning과 다른 소스의 Gallery 근거를 유지한다.

실제 main 착지·새 최종 G1/공식 FULL·게시·배포·실물/현장 수용은 별도 후속 조건이다. 수용 완료 시 새 날짜 기록으로 source·terminal·main ancestry를 결속한다. 현재 module progress/last_verified를 넓히지 않는다.

CE: 해당 없음 — closure와 250ms 실제 RED/GREEN이 원인·재발 방지를 설명한다. BOM은 기존 교훈의 바이트/정본 main 헤더 보존을 적용했으며, 별도 교훈 문서를 늘리지 않았다.
