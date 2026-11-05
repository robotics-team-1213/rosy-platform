# 같은 위계의 공용 UI 통일 — 사용자 제보 후속

2026-11-05 사용자가 Fleet 지도와 설치의 하위 메뉴가 같은 위계인데 서로 다른 정렬·선택 배경·모양을 쓴다고 지적하고 전 화면 통일을 지시했다. 기존 [화면별 기록](surfaces.md)과 [긴 읽기값 후속](readback-header-followup.md)을 보존하며 이 추가 범위를 기록한다. 이 문서는 아래 소스의 검증 범위를 고정한다. 공식 FULL·main 이동은 별도 게이트 결과로 확인한다.

## 기준과 구현

같은2단계 화면/작업 선택은 기존 `shared/web/app-shell.css`의 `.ui-subnav-nav`·`.ui-subnav-item`이 정렬·치수·여백·선택·초점·좁은 배치를 소유한다. Fleet 설치와 Robot 설정/장치의 공용 task-chooser도 이를 소비하며 별도 segment 외양·compact select를 제거했다. URL 링크와 native `button[type=button][role=tab]`은 각각 올바른 의미를 보존한다.

Learning 홈5개 하위 화면 선택은 일반 동작 링크에서 같은 공용 하위 탐색으로 바꾸고 기존 셸 자리에 배치했다. `aria-current=location`도 현재 위치를 표시한다. 기존 hash/query/history·H1·경로 줄·입력·공용 갱신은 유지했다. 전환 거절/시간초과·pause/resume·mounted 초안·키보드·권한·정지의 소유권은 바꾸지 않았다. ResizeObserver는 실제 메뉴 배치에 맞는 tablist 방향만 갱신하고 destroy 때 해제한다.

폼 segment·워크플로 노선·서버 상태·위험 동작은 같은 메뉴로 합치지 않는다. 새 부품·테마·프레임워크·API·실행 권한은 추가하지 않았다. DESIGN의 공용 선택기·현재 위치 설명과 styleguide 및 직접 시험 소비처를 함께 맞췄다.

## 30개 카드 감사 범위

정적 문서와 공용 호출자를 대조하고 Account2화면·Pilot의 동적 생성부까지 추적했다. 실제 제품 수정은4카드, 견본은 DEV1카드다.

| 분류 | 카드 ID | 근거 |
| --- | --- | --- |
| 통일 적용4 | fleet-install, robot-setup, robot-device, learning-home | 공용 task-chooser의3제품 소비처, 홈의5실제 하위 화면 선택 |
| 기존 공용13 | fleet-console, fleet-cell, fleet-site-map, fleet-policy, learning-tasks, learning-omx, learning-review, learning-pixels, learning-vlm, learning-catalog, learning-camera, learning-sim, learning-workspaces | 기존 subnav/review-kinds 소비. 별도 선택 paint 사본을 추가하지 않음 |
| 의미상 별도12 | fleet-accounts, fleet-profile, fleet-login, fleet-learning, learning-evaluate, learning-accounts, robot-console, games, diagnostic, lane-live, monitoring, pilot | 계정 대상/폼·인증·호스트 진입·단일 평가·공간 동시 패널·경기/안전·PARKED·맥락 탭·데이터 필터·접속/조종 상태 |
| DEV1 | gallery | 공용 선택기 견본 동기화, 제품 업무 GO로 세지 않음 |

Account의 `account-page.js`는 계정 행/편집 대상을, `profile-page.js`는 프로필·권한 목록을 생성한다. Account 고정 번들은 업무 하위 메뉴를 주입하지 않는다. Pilot의 `showConnect`/`showDrive`/SIM arm은 제어 가용성에 따른 상태 전환이고 `screens/compose.js`는 입력 widget을 조립한다. 이를 업무 메뉴로 오판하지 않았다. 인증 전 D-961 예외와 첫 레일·폼/상태의 기존 의미를 보존한다.

## 소스와 원격 결과

| 소스 | 범위 | 실제 결과 |
| --- | --- | --- |
| commit f8cb261e26c86c4d09327327965225b0dcf1967f | 실제 Fleet 비교6·Robot resize1·Home6 RED | 13FAIL/0skip/NEW13, exit1,65초 |
| commit 744b287a4f0ba412677223245055f9dc1f29c5c4 | 공용 소비·자리·직접 호출자 후속 | 7PASS/6FAIL/0skip/NEW6, exit1,42초. 남은 차이는 링크/버튼 focus offset2px/1px |
| commit 0de561052a5b205eb0c729e056ce5f440b3e6466 | 공용 focus token1줄 후 동일13개 | 13PASS/0skip/NEW0, exit0,42초 |
| commit 0de561052a5b205eb0c729e056ce5f440b3e6466 | G1 10파일 | 128PASS/1FAIL/0skip/NEW1. 기존64/48 전용 구조 시험이 승인된22rem 경계를 거부 |
| commit 9d5278e6cebd4ef6ec124cba2abb4a8625252465 | 전체 shell seats·layout canon·operator copy | 36PASS/0skip/NEW0, exit0,14초. 현재22–64rem subnav 블록 단언과 DESIGN의location 누락 정정 |
| commit 67d6a8f765ffaa1df849deebd2a01f11b15d36dc | 최초 선택적 캡처14개 | 7PASS/7FAIL/NEW7. 메타데이터가 DIV tablist를nav로만 조회한 오류. 부분95원본은 GO에 합산하지 않음 |
| commit 1a390c9d406af849e3138d15d34f9034142ffddb | 공용 클래스 조회 최소 수정 뒤 실제 비교 캡처14개 | 14PASS/0skip/NEW0, runner/classifier0,45.69초 |
| commit 1a390c9d406af849e3138d15d34f9034142ffddb | 기존 Robot surface budget 보충2개 | 2PASS/0skip/NEW0, runner/classifier0 |
| commit 1a390c9d406af849e3138d15d34f9034142ffddb | 기존 소비처·권한·전환·초안·viewport19대상 | 315PASS/2FAIL/0skip/NEW2, exit1,838초 |
| commit a27e97c186c9746f0838d2562507614f67149b80 | 마지막 두 소비처의 전체2파일 | 36PASS/0skip/NEW0, known/flaky0, exit0,125초 |

마지막2건은 현재 지도옵션의 실제 권한 안내를 읽고, 의도적으로 유지되는 접속 overlay를 Escape로 닫은 뒤 실제 모바일 탭을 클릭하는 시험 흐름으로 정정했다. 기존4권한 문구·역할 잠금·동일 DOM·입력·단일 패널·복구·overflow·오류 단언은 유지했다. Escape 후 hidden/aria-expanded=false/선택 탭 초점도 확인한다. 강제 클릭·DOM 숨김·pointer 우회·제품 변경은 없다.

1a와a27의 제품/캡처 훅12개 소유 경로는 diff0이다. 서로 다른 실행을 하나의 새 SHA 전체 통과 수치로 합산하지 않는다. 각 로그의 NEW 분류와 runner 종료를 따로 보존했다.

## 원본 결속과 시각 수용

원본은 작업공간 `Rosy/docs/workspace-records/2026-11-05/ui-map/task10-subnav-1a390-final/`에 둔다. `receipt.json`, `command.json`, `source-host-binding.json`, `runner.txt`, `run/run-1.txt`, `classification.txt`가 실제14개 실행/출처를 결속한다. 보충2개는 같은 구조의 `setup-witness/` 아래 보존한다. 환경 주소 등 원본 값을 이 문서에 전사하지 않는다.

[표준 SHA256 목록](hierarchy.sha256)은 해당 작업공간 `ui-map/` 기준153행이며77PNG+70JSON과보충6PNG를 포함한다. 원격/회수 해시가 같고 컨트롤러도153개를 재해시해 불일치0을 확인했다. 목록의 Git blob(LF 정규화) SHA256은 `72b604224e13c28452e6f77334123ca5ef19d09ab813759c6bdde75b0eae5fe1`이다.

- Fleet 두 문서의2선택×3폭×2테마:24PNG.
- Home5선택×3폭×2테마:30관측PNG+6overview.
- Robot device2선택×3폭×2테마:12관측PNG와기존readback/identity5PNG.
- 보충6PNG는console/setup/device3문서×2폭이다. setup 자체는default dark390/320 **2셀**이다.

실제 viewport 높이는 개별 receipt에 따른다. Fleet320은568, Robot320은844, Home은900 등으로 같다고 가정하지 않는다. computed66행은 최소높이48px·글자14px·start정렬·gap4px·문서overflow0이다. 메뉴focus/focusVisible은65/66이며 Home storage dark320은 본문focus 사진이라 메뉴focus 증거에서 제외한다. 다른Home 상태의 같은 선택자 초점으로 공용 표현을 수용했다. setup의넓은/밝은/키보드focus 전체행렬 통과로 확대하지 않는다.

독립 검토자는 실제30PNG를 직접 열고83PNG를 재해시했으며8기준(정직·증거 상태·색·위계·불가역·어휘·질문·문법)을 scoped PASS/신규Critical·Important·Minor0으로 승인했다. setup2셀과공통mount→chooser 경로를device6셀 근거와함께 수용했고 추가 필수 차단 셀을 요구하지 않았다. 메뉴와 본문이320/390에서 접근 가능하며 링크/tab의 의미와workflow/권한은 구분된다. hover전용 상태는 직접 검토 범위가 아니다.

별도의 독립 소스 검토도 제품·focus 후속·캡처/계약 후속·마지막2시험 소비처에 필수 지적0건이다. 소스 검토와 시각 수용을 원격 FULL·main·실물 수용으로 대신하지 않는다.

## 판단과 한계

- 기존 공용2단계 표현을 선택했다. 잘못되면 공유 배치/초점/폰 접근에 회귀가 생길 수 있어 실제 렌더·전환 회귀로 확인했다.
- Home 메뉴를 기존 셸 자리에 뒀다. 잘못되면 높이 예산/hash·초점이 깨질 수 있어 실제 자리·본문 예산과이동을 확인했다.
- 현재22rem 블록을 검사하는 기존 구조 시험을 유지했다. 같은 조건의 추가 중복 블록까지 거부하는 완전한 CSS parser는 아니며 그 보장을 주장하지 않는다.
- setup2셀·공통소비자/device6셀과메뉴focus65/66 범위로 scoped 시각 수용했다. 미관측 setup넓은/밝은/hover·개별focus 회귀를 놓칠 위험은 기존 viewport/키보드 및 정식 FULL과 구분해 유지한다.
- 마지막2건은 실제 생산자와 사용자 동작을 검증하는 시험으로 닫았다. 잘못되면 실제가림을 숨길 수 있어 열린overlay·Escape·초점·정상click과기존guard를 함께 검사했다.

CE: 해당 없음 — 공용 소유권·기존 헤더 정책·실제 코드/회귀·본 검증 기록으로 판단을 재구성할 수 있다. GitHub 게시·서비스 배포·현장/실물·모델 품질 수용은 이 UI 후속의 실행 범위 밖이다.

## 후속: Learning 메뉴 바깥 여백과 캡처 가드

아래는 여백 보완 이후의 별도 소스 증거다. 위153개 원본·당시 실행·감사4카드·시각 수용 범위는 그대로 보존한다. 원본을 새 후보 전체 PASS로 다시 표시하지 않는다.

최종 소스 검토에서 Learning `app.css`의 옛 좁은 `.ui-subnav-nav{padding-block:0}`가 공용 `--inset-rail`을 덮는 Minor를 확인했다. 홈6개 기존 사례에 메뉴 **컨테이너**의 computed paddingTop/Bottom과 공용 토큰 비교를 추가했다. 휴대폰4개는 실제0px/0px 대8px로 실패했고 desktop2개는 통과했다. 해당 override·설명2행과 공용 owner로 이동한 뒤 남은 console의 stale22rem registry2행만 제거했다. 별도 Home 덧칠·새 allowance·권한·동작 변경은 없다. `.review-kinds`의 사진·제목·키보드 순서 규칙은 보존했다.

실제 여백 소비자는 `/learning`, `/catalog`, `/learning/camera`, `/learning/workspaces`, `/learning/record`, `/learning/tasks`(workflow), `/learning/tasks/manage`(tasks), `/learning/sim`, `/learning/public`의9개다. 최초4카드 통일 작업과 이 후속의 기존 Learning 메뉴 소비 범위를 구분한다.

| 실제 실행 소스 | 범위 | 결과와 한계 |
| --- | --- | --- |
| commit 72cb483bd523a92ff68e165b9b514e1c371f8939 | Home 기존6개 RED | desktop2PASS/phone4FAIL/0skip/NEW4,23초 |
| commit 107217dd8b0c2af6e034d5a6c01d6c68eee8be65 | 동일6개 GREEN | 6PASS/0skip/NEW0,22초 |
| commit 107217dd8b0c2af6e034d5a6c01d6c68eee8be65 | Learning context·기존사진/첫화면예산·responsive registry7대상 | 98PASS/0skip/NEW0,214초. 이전 후보에서 이미 admission된 실행이며 새 후보의 전체 통과로 바꾸지 않음 |
| commit a9d0f95a6918d30953ad65743f097b18b5a2578f | Home6개와 실제 다른8메뉴 route의 선택적 캡처 | 14PASS/0skip/NEW0,31.37초. 원본 run/receipt/classifier 근거이며 JUnit은 요청되지 않음 |
| commit a9d0f95a6918d30953ad65743f097b18b5a2578f | 캡처 env를 켠 원래 no-nav `/` 사례 RED | 1FAIL/0skip/NEW1,32.32초. 새 optional block이 없는 nav를 조회해 timeout |
| commit b95508565644877ac8aae619360b4bcd8c9a4c09 | 가드 한 줄 수정 후 원래 current-path16경로 전체 | 16PASS/0FAIL/0error/0skip/NEW0. 원본 JUnit16 testcase와 runner/classifier0 직접 대조 |

정상 후보 재구성에서 기존 RED는 commit df972a49f00c0a9da908ad7c04dbb143becc5e90, 제품 보완은 commit 02e319a92942a083f569958006e13a359dd8c406으로 replay했다. 이전 RED와 새 RED의 해당 시험 diff는0이며, 이전 GREEN107과 새02의 Learning web·공용 app-shell/task-chooser/surfaces 제품 diff도0이다. commit a9d0f95a6918d30953ad65743f097b18b5a2578f의 같은 제품 blob도107과 동일하다. Account peer 변경은 별도 출처로 보존했으며 여백 수정으로 세지 않는다. 서로 다른 SHA의 별도 실행을 이 표에 합산하지 않는다.

### 추가 원본과 해시

작업공간 `ui-map/learning-padding-final-a9d/`에68PNG+62JSON **130개**, `ui-map/padding-hook-guard-green-b955/`에36PNG+36JSON+원본JUnit **73개**를 보존한다. 두 폴더의 `command.json`, `receipt.json`, `remote-original-sha256.json`, `source-host-binding.json`, `runner.txt`, `run/run-1.txt`, `classification.txt`가 실제 argv·소스·호스트 역할·결과를 결속한다. 첫 실행은 모델 PC, 후속16경로는 AI PC의 정상 원격 admission이며 현장 장치 실행은 없다.

[추가 표준 SHA256 목록](learning-padding.sha256)은 같은 작업공간 `ui-map/` 기준 **203개 고유 경로**다. 두 remote-original manifest의130+73개, receipt의 모든 PNG digest, 실제 원본을 다시 대조해 누락·중복·해시 불일치0을 확인했다. digest는 원본 파일 바이트 기준이며 PNG/JSON/JUnit의 줄바꿈을 정규화하지 않는다. checksum 목록 텍스트 자체만 LF·마지막 개행의 Git blob 기준으로 다룬다. 목록 LF 바이트의 SHA256은 `dca7a07cf0953c1c08d9b633fb3a65e4becf6d808408659e165c1fc8ab8cd4ed`다. 기존 [153행 목록](hierarchy.sha256)은 바꾸지 않았다.

첫 캡처의62 computed행 중52개 narrow쌍은9메뉴의 실제390/320 두 테마이며 outer padding8px/8px와 computed inset8px가 일치한다. desktop Home10행은12px/16px로 별도다. Home 높이는900, 다른 narrow variant는390×844/320×568이며 같은 높이로 가정하지 않는다. `/learning/public`의 currentCount0은 실제 상태로 남기고 첫 항목의 초점을 선택 상태로 지어내지 않았다. 독립 G3는 이 여백 Minor를 ADDRESSED로 판단했으며, 마지막 가드 scoped 재검토도 새Critical/Important/Minor0이다.

### 원래 경로와 시각 수용의 한계

새 capture block은 실제 nav가 있을 때만 실행한다. 원래16개 route/본문 단언은 한 줄도 빼지 않았다. `/`, `/pixels`, `/learning/omx`, `/learning/vlm`, `/learning/evaluate`, `/classes`, `/learning/imitate`의7경로는 **기존 본문 시험 PASS, 추가 nav capture N/A**이며 pytest skip이 아니다. 새 메뉴·선택·가짜 사진은 만들지 않았다. `guard-body-byteproof.json`은 정확한 가드 한 줄 치환 외 원래 시험 파일이 byte 단위로 같음을 확인하고 `product-ui.diff`는 비어 있다.

SIM320의 두 테마에서 실제 현재 항목은 x272.671875–351.453125px, nav는 x0–320px로 오른쪽31.453125px가 가로 영역 밖이다. 두 캡처 소스 모두 같은 사각형이며 focus/focusVisible=true는 항목 전체가 보인다는 뜻이 아니다. 320의 공용 가로 스크롤 배치에서 발생한 관측으로, 세로 여백 수정이 원인이라는 증거는 없다. 키보드/resize 때 현재 항목이 자동으로 완전히 드러나는지는 **미검증**이다. 별도 확인에는 키보드 선택·좁아지는 resize 전후의 current item/nav 사각형과 scrollLeft를 같은 시점에서 비교해야 한다. 자동 노출이 안 되면 사용자가 가로 이동해야 할 수 있으며 이번 기록은 해결됐다고 주장하지 않는다.

별도 로그 무결성 선행 작업 commit 3caa67b6c324df635189e9af2d094907ee412554는148PASS/0skip/NEW0와 독립 검토 근거가 있지만 공식 착지 대기다. 이는 UI 최종 G1/FULL 통과가 아니다. **현행 UI 후보의 최종 G1·공식 FULL·실제 main 반영은 아직 완료되지 않았다.** 추가 metadata를 포함한 최종 소스에서 controller가 이 gate를 확인한다. 제품·시험 재실행·Git stage/commit/merge는 이번 문서 마무리 작업에서 하지 않았다.

CE: 해당 없음 — 공용 여백 계약, 정확한 optional guard, 원본 route 회귀와 소스별 증거로 원인과 보존 조건을 재구성할 수 있다.
