## D-466 머리와 사이드바는 각각 한 자리만 갖는다

**Status:** Accepted (2026-10-05, 사용자 지시 — 헤더와 사이드바 레이아웃을 토큰으로 고정하고 자리를 더 쪼개지 않는다). 장치·현장 수용은 포함하지 않는다.

잇는 결정: [D-292](D-292-design-tokens-and-component-layout-contract.md) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-405](D-405-icon-first-controls-and-measured-size-discipline.md) · [D-421](D-421-fleet-cancel-all-driving-separate-from-latched-estop.md).

### Context

화면 크롬이 표면마다 다른 격자로 늘었다. 로봇 셸은 64rem 미만에서 `brand role estop` / `nav nav estop`이고, Fleet은 90rem 미만에서 `brand pill cell clock more estop`, 30rem 미만에서 다시 두 줄이다. 호환 콘솔은 영역 이름 없이 열 수만 바꾼다. 같은 세 단인데 머리 레시피가 여러 개로 보인다.

절차를 고르는 열도 두 폭이다. 로봇 작업 준비·설치·정비는 `minmax(13rem, 18rem)`, Fleet 설치 작업은 `minmax(12rem, .22fr)`이다. 화면 전환은 머리 안에 있고, 명렬·지도·감지/관측/조작은 본문 열이다. 어느 것이 사이드바인지 코드가 말하지 않는다.

사용자는 토큰으로 생각하고, 레이아웃을 더 나누지 말고, 헤더와 사이드바의 자리를 명확히 잡으라고 했다. 처리 방식은 ADR이다.

### Decision

1. **머리의 자리는 셋이다.** `ui-topbar`의 바깥 자리는 `brand`, `cluster`, `estop`이다. `brand`는 워드마크다. `cluster`는 화면 전환·상태·조용한 도구다. 그 안의 순서는 표면이 정한다. `estop`은 오른쪽 끝의 비상 정지이고, 모든 폭의 첫 화면에 있다. 넷째 자리를 만들지 않는다.
2. **머리의 접기는 기존 세 단만 쓴다.** 64rem 미만은 두 줄이다. 첫째 줄은 이름과 상태, 둘째 줄은 화면 전환, 비상 정지는 두 줄을 차지한다. 30rem 미만은 그 두 줄에서 여백과 부제만 줄인다. 열 구성을 다시 정하지 않는다. Fleet의 90rem 설정 접기(접속·역할·테마)는 `surfaces.yaml`에 이미 등록된 예외이고, 접힌 뒤의 바깥 자리도 brand·cluster·estop이다. 새 `@media` 폭을 만들지 않는다.
3. **사이드바는 절차 작업을 고르는 열 하나다.** 표시는 `.ui-sidebar`다. 소비자는 로봇 작업 준비·설치·정비의 작업 레일과 Fleet 설치 작업 선택이다. 넓은 단(64rem 이상)의 폭은 `--sidebar-track: minmax(13rem, 18rem)` 하나다. 13–18rem은 절차 칸이 쓰던 값이고, 이 ADR이 그 값을 토큰으로 올린다(D-292 §6). 64rem 미만에서는 레일을 숨기고 기존의 선택 필드를 보여 준다. 세 번째 제시를 만들지 않는다.
4. **사이드바가 아닌 것.** 화면 전환(`#surface-switch`, 입구의 작업 화면 목록, 호환 콘솔의 운용/점검)은 머리의 cluster다. Fleet 명렬, 지도, 로봇 콘솔의 감지·관측·조작 열은 본문이고 표면이 소유한다(D-292 §4). 인증 서랍과 영상 모서리 그림은 크롬 자리가 아니다.
5. **범위를 늘리지 않는다.** 콘솔을 합치지 않는다. Pilot `grammar`는 `spatial`이다. 한국어 본문, 정지 동사, 아이콘 이름은 그대로다. 게임·진단·Gazebo 뷰어는 이 결정의 소비자가 아니다.

### Alternatives

- **화면 전환을 넓은 창의 왼쪽 열로 옮긴다.** 거부한다. 좁은 창의 계약은 전환이 비상 정지 왼쪽에 있는 것이고, 넓은 콘솔은 이미 감지·관측·조작 세 열이다. 네 번째 열은 그 자리를 줄인다.
- **Fleet 30rem 머리를 로봇 셸과 같은 영역 이름으로 다시 짠다.** 거부한다. 바깥 자리는 이미 brand·cluster·estop이다. 영역 이름을 맞추는 변경은 잠긴 머리 시험을 깨고 보이는 순서를 바꾸지 않는다.
- **사이드바 폭을 칸 비율(`.22fr`)로 둔다.** 거부한다. 관제 폭에서 열이 계속 커진다. 절차 칸의 13–18rem이 작업 이름이 들어가는 상한이다.

### Consequences

- `--sidebar-track`이 절차 열 폭의 한 곳이다. 로봇 `.procedure-tasks`와 Fleet `.install-tasks`의 넓은 단이 그 토큰을 쓴다.
- 작업 레일은 `.ui-sidebar`를 함께 단다. 64rem 미만의 숨김은 `task-chooser.css`가 유지한다.
- 머리의 기존 영역 문자열은 유지한다. 이 결정은 그 문자열이 한 레시피의 cluster 내용이라고 이름을 붙인다.
- 호스트 계약이다. 태블릿·관제 모니터의 사람 확인은 아니다.

### Validation

- `shared/web/test/test_chrome_layout.py`가 토큰 값, 두 절차 열의 소비, 머리 영역 문자열, `.ui-sidebar` 표시를 잠근다.
- 새 `@media` 폭이 없으므로 기존 반응형 허용 목록 시험이 그대로 본다.
