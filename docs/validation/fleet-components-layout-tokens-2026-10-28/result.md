# Fleet 공통 컴포넌트·레이아웃 역할 검증

2026-10-28. 기준 commit `9cadeb907a`, 최종 제품 source commit `2d96683c9c`, 캡처 시험 commit `75868811a1`. 기존 `fix/recording-learning-handoff` 워크트리를 재사용했다. 이전 병합 요청의 immutable snapshot은 이 추가 작업을 포함하지 않는다.

## 적용 범위

관제·설치·현장 지도·Cell의 헤더/전역 탐색을 두 `.html.inc` 정본으로 옮겼다. `applications/fleet/web/shared/fleet_components.py`가 네 정적 HTML의 고정 슬롯만 합성한다. 브라우저는 첫 응답부터 완성된 셸을 받는다. 별도 런타임·프레임워크·외부 의존성·서버 렌더링 변경은 없다. 생성 사본이 정본과 달라지면 `--check`와 회귀가 거절한다.

공통 배치는 `doc-tabs.css`, 값은 `shared/web/tokens.css`가 소유한다. [D-906](../../adr/D-906-fleet-static-components-layout-roles.md)의8개 역할로 본문 폭·여백·동작 간격·탐색 크기·인증 필드/계정 글 폭을 표현한다. Cell/지도에 중복된 본문·label·section·actions·피드백 규칙과 사용하지 않는 토큰 입력 폭 규칙을 제거했다. 네 본문 inset은16px이며 Cell/지도 최대90rem·actions12px·rail56px은 보존했다. 지도/SVG 좌표·물리 단위는 바꾸지 않았다. 갤러리는 역할의 계산된 값을 표시한다.

## 발견과 후속 수정

- 정본 파일을 `.html`로 두자 자산·테마·feature 검사가 독립 화면으로 분류했다. `.html.inc`로 구분해 기존 등록 계약을 유지했다. 생성기에서 비활성 탐색 placeholder 앞 공백도 함께 제거한다.
- 새 DOM 인접 검사가 하위 탐색이 없는 설치 화면까지 요구했다. 실제로 하위 탐색을 가진 세 화면에 한정하고 설치의 기존 탐색 구조는 유지했다.
- 넓은 브라우저 회귀에서 인증된 사용자의 토큰 전환이 막히는 것을 확인했다. [앞선 계정 기록](../fleet-account-layout-2026-10-28/result.md)의 인증 후 token hidden 정책을 이 source가 대체한다. 토큰 접속은 기본 닫힌 계정 메뉴 안에서 계속 접근할 수 있다. 같은 identity 재조회는 열린 메뉴·details·입력값을 보존하고 새 identity일 때만 접는다. 화면별 표시 조건은 다시 추가하지 않았다.

인증·권한·명령 경로·비상 정지 동작은 변경하지 않았다. 브라우저는 fixture 서버/계정을 쓰며 실제 장치나 운영 토큰에 연결하지 않는다.

## 실행 근거

pytest는 모두 공식 `tools/remote/remote_pytest.py`로 커밋된 source를 승인된 시험 PC에 전송했다. 브라우저는 `--` 뒤 `ROSY_RUN_BROWSER_TESTS=1`을 전달했다. 로그 위치는 아래 이름 앞에 `C:/DevTemp/`를 붙인다.

| 범위 | commit | 결과 | 로그 디렉터리 |
|---|---|---|---|
| 정본/역할 RED | 1b96e468d1 | 5 failed | fleet-components-red |
| 첫 응답·geometry RED | 5debdfa33d | 8 failed / 19 deselected | fleet-component-geometry-red |
| 초기 정적 계약 | bc5dca0cde | 2 failed / 62 passed | fleet-components-green |
| 정적 계약 수정 후 | 1442b1ddab | 64 passed / skip0 | fleet-components-contract-green |
| 헤더·세션·갤러리 | bc5dca0cde | 57 passed / skip0 | fleet-component-geometry-green |
| 추가 입력 폭 역할 후 | 83240491af | 4 failed / 71 passed | fleet-component-measures-green |
| 정본·등록·실제 헤더 수정 후 | 94f9a7211f | 90 passed / skip0 | fleet-components-discovery-green |
| 추가 거버넌스14대상 | 5d49903269 | 607 passed / skip0 | fleet-components-governance-green |
| 공식 영향 선택 첫 실행 | 1442b1ddab | 4 failed / 8196 passed / 1008 skipped | fleet-components-affected-final |
| 공식 브라우저101파일/9묶음 | 1442b1ddab | 41 failed / 1444 passed / skip0 | fleet-components-browser-final |
| 토큰 전환 수정 후 교통 화면 | 2d96683c9c | 9 passed / skip0 | fleet-components-traffic-green |
| 토큰 전환 수정 후7개 브라우저 파일 | 2d96683c9c | 306 passed / 1 known failed / skip0 | fleet-components-token-switch-green |
| Cell·설치 작업 흐름 후속 | 2d96683c9c | 85 passed / skip0 | fleet-components-workflows-green |
| 최종 공식 영향 선택69/2/21대상 | 2d96683c9c | 8807 passed / 1008 skipped / NEW0 | fleet-components-affected-clean |
| 명시적 열린 입력·재조회·캡처 | 75868811a1 | 16 passed / 11 deselected / skip0 | fleet-components-final-captures |

초기 정적 계약2실패는 새 생성 주석과 두 번째 task container 선언에 대한 기존 문자열 가정이었다. 주석을 제외한 하위 탐색 좌석 검사를 유지하고, 셸/task 각 컨테이너 소유권 검사와 실제 DOM 인접 검사를 추가했다. 제품 동작 검사를 완화하지 않았다.

공식 selector는 `affected --base 9cadeb907a --json`이며 affected/no escalation이다. 공유 토큰을 바꿨지만 이 버전의 selector는 FULL을 요구하지 않았다. 첫 영향 실행4실패는 조각 분류/생성 공백이며 90건 후속에서 해결했다. 브라우저41실패 중4건은 설치 DOM fixture 가정,36건은 토큰 전환 불가였다. 나머지 테마 단추1건은 기존 known failure와 일치했다(메뉴가 닫혀 클릭 불가). 비교 결과는 NEW40/known1이며 해당 테마 파일도 후속 실행에 포함했다. 실패를 known failure에 추가하지 않았다. 조건부1008 skip은 브라우저 실행 증거로 계산하지 않으며 브라우저101파일을 별도로 실행했다.

위10개 브라우저 파일 후속은400 passed/NEW0/known1/skip0이다. 최초101파일을 최종 source에서 모두 다시 돌렸다는 뜻은 아니다. 모든 신규 실패를 포함한 파일 전체를 다시 실행했고 초기 통과 파일의 기록은 앞 source에 묶어 둔다. 남은 known1은 `test_the_fleet_topbar_selector_switches_the_theme_live`이며 실제 서버를 띄우는 공통 헤더의 테마3회 순환·접근성 검사는27건에 포함되어 통과했다. 정적 호스트 기반 테마 시험의 기존 실패를 제품 전체 테마 불능이나 완전한 수용으로 확대 해석하지 않는다.

최종 영향 선택은 `C:/DevTemp/fleet-components-latest-selection-utf8.json`이며 `remote_pytest.py --affected-json <selection> --log-dir <dir>`로3묶음을 전부 실행했다. 세 로그 모두 NEW0/known0/flaky0이다. 최종 제품 source 이후 변경은 캡처 시험·검증 기록뿐이다. 정본 CLI check,9개 커밋 size_range, safety_review, 커밋 추가 줄 비밀 검사 모두 통과했다. 기록 추가 뒤 lint는0 error/41 warning(기존 gate 신선도 등의 경고)이며 생성 색인을 갱신했다. 이 결과는 별도 원격 문서 검사나 최종 문서 커밋의 실행을 선행했다고 주장하지 않는다.

로그 집합도 같은 파일명+SHA-256/LF 방법으로 식별한다. 아래 디렉터리에는 최종 `run-*.txt`만 집합에 포함했다.

| 디렉터리 (`C:/DevTemp/` 기준) | 로그 | SHA-256 |
|---|---|---|
| fleet-components-affected-clean | 3 | 1403d403e883bbe2f02594141c579689a1666303e6c6e0dd3365b4534f568b27 |
| fleet-components-token-switch-green | 7 | c1c184a177f50bcf225b9970d61157f14a95c2936ce170c823cf247af708b31c |
| fleet-components-workflows-green | 1 | 967574431b0acd98ee9c6cec23ae5988f6e8f9709bf66d7b3dabb4d04c48a2f5 |
| fleet-components-traffic-green | 1 | df7121f7c5fd69113e6f801499f53f1f183775fe49f3a4bdc0d2792fd7946e1e |
| fleet-components-final-captures | 1 | 858d151968ec4c970cb0a39528851eae0f3ffa979c48a9cc9940c0745152a2a3 |

위 선택 JSON의 SHA-256은 `b078ef1109336e784169d3f1691085c1950ed6147377deee4f0dcb5a98c4eab0`다.

## 화면과 독립 검토

`C:/DevTemp/fleet-component-layout-screenshots/`의32PNG는 source commit `bc5dca0cde`에서 계정 닫힘/피드백 상태×4문서×320/390/768/1440을 캡처했다. 독립 검토자가32장 전부 열어 확인했다. 좁은 폭의 피드백/본문 왼쪽은16px, desktop 관제·설치는88px, 지도·Cell은320px로 일치했다. P1/P2 잘림·겹침 지적은 없다. 관제 피드백390/768/1440은 캡처 순간 live로 돌아왔으므로 동일 disconnected 상태 비교 근거로 쓰지 않는다.

최종 source의 명시적 열린 토큰 입력과 Escape 뒤 상태는 `C:/DevTemp/fleet-component-final-screenshots/`의32PNG다. 실제 재조회 뒤 입력값 보존·헤더 높이 변화<=1px·문서 가로 넘침 없음을16회 확인했다. 독립 검토자는 열린 메뉴16장 전부를 확인했고 닫힌 상태16장은 이번에 열지 않았다. 입력 초점 테두리·접속 단추·비상 정지가 화면 안에 있고 P1/P2 잘림·겹침이 없었다. 320px의 메뉴 줄바꿈에 따른 높이 증가는 반응형 차이이며 같은 identity 재조회 전후 높이 안정성과 구분한다.

캡처 디렉터리의 SHA-256은 파일명 순으로 정렬한 `파일명 + 공백 + 파일 SHA-256 + LF`를 UTF-8로 합쳐 계산했다. 아래 해시는 PNG 원본 집합을 식별하며 이미지는 Git에 커밋하지 않는다.

| 디렉터리 (`C:/DevTemp/` 기준) | PNG | SHA-256 |
|---|---|---|
| fleet-component-layout-screenshots | 32 | 55c454193cfcaf9620aff0a5bfc57982e240fae47528a729194ed84c5c8d4d7c |
| fleet-component-final-screenshots | 32 | b0d9c6484df2fb81886b44d41bf7cf6e03400e72823d8c6811afad0a5081b2da |

독립 소스 검토는 canonical 생성기·8역할·실제 소비처·D-906 일치를 확인했고 P1/P2 또는 불필요한 추상화 지적이 없었다. Console 본문은 assistant-layout 내부이므로 공통 main 규칙은 의도적으로 descendant에 적용한다. 이미지 검토와 DOM 정량 검사를 구분하며 전체 접근성 수용이나 실제 스크롤 조작을 모두 확인했다고 주장하지 않는다.

## 한계와 CE

범위는 Fleet 네 화면의 공통 chrome·레이아웃이다. 전체 플랫폼의 모든 하드코딩 제거, 모든 상태의 수동 사용성 수용, 운영 배포·실물 비상 정지·ARM64 실행·현장 수용을 뜻하지 않는다. 추가 push/병합은 수행하지 않았다.

CE: 해당 없음. 조각/페이지 구분과 토큰 전환·반복 인증의 상태 보존 판단이 생성기·회귀·D-906에 남아 별도 교훈 문서 없이 복원된다.
