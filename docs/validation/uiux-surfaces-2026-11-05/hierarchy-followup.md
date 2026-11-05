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
