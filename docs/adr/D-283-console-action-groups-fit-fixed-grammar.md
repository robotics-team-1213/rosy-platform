## D-283 운용 콘솔은 고정 3영역을 유지하고 조작 그룹을 선택한다

**Status:** Accepted (2026-09-26). 이 ADR은 운용 화면 배치 원칙을 정한다. 구현·실기 수용을 뜻하지 않는다.

잇는 결정: [D-201](D-201-fixed-grammar-surfaces-fit-contract.md) · [D-274](D-274-local-core-browser-review-and-device-acceptance.md) · [D-278](D-278-role-based-surface-ux-and-palette-review.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · concept 16 §7.1.

**Context:**

현재 역할별 `/console`을 실제 FastAPI + `CoreServices`의 CORE 경로에서 검토했다. ROS·실기 데이터를 연결하지 않은 최초 기동 상태이며, administrator와 operator 모두 조작 panel 4개를 받는다. 1366×768에서 현재 데스크톱 CSS는 sense와 observe를 먼저 놓고 act를 다음 행에 두어 문서가 823px 더 길다. 따라서 안전 조작은 헤더에 보이지만 조작 패널은 첫 프레임 아래에 밀린다. 390×844에서는 가로 넘침 없이 E-stop이 보이나, 페이지는 세로 스크롤한다.

세 영역을 나란히 두는 한 번의 CSS 후보도 시험했다. 지도와 카메라는 들어왔지만 조작 panel의 실측 경계가 y=1017에 닿아 마지막 조작을 화면 밖으로 잘랐다. 단순히 `overflow: hidden`을 주면 D-201의 미분쇄 조건과 사용자가 조작을 찾고 수행할 수 있어야 한다는 조건을 깨뜨린다. 조작 영역 자체를 스크롤시키는 방식은 concept 16 §7.1이 고정하도록 한 영역을 바꾼다. 따라서 화면 안에 모든 조작을 평면 배치하는 대신, 고정 act 영역에서 작업 묶음을 선택하게 한다.

**Decision:**

1. **선언 뷰포트의 공간 문법을 지킨다.** 1366×768 이상에서 console은 감지(sense)·관측(observe)·조작(act) 3영역을 한 프레임에 둔다. 페이지는 스크롤하지 않고, 감지 목록만 영역 안에서 스크롤할 수 있다. 관측과 조작은 고정되며, 활성 조작 그룹의 컨트롤은 잘리거나 분쇄되지 않는다. 지도는 종횡비를 지키며 남은 높이에 맞춰 줄어들 수 있다. E-stop은 공통 상단 바에서 항상 보인다.
2. **조작은 세 그룹 중 하나를 고른다.** act 영역의 그룹은 `운전`, `도킹`, `차선 추종`이다. `운전`에는 운전 모드와 수동 운전을 둔다. 각 그룹은 기존 role/capability manifest에 실제 제공되는 panel만 보여준다. `not_provided` 기능의 빈 탭을 만들지 않는다. 조작 그룹이 하나도 없는 역할에는 그룹 선택 UI를 렌더하지 않는다.
3. **첫 진입은 일반 운전을 보여준다.** `운전` 그룹을 기본 선택으로 둔다. 선택 상태는 현재 페이지 수명에만 두고 재접속·새 세션에서 복원하지 않는다. 선택은 표시만 바꾸며 API 권한, capability, 확인 대화상자, 서버 판단을 변경하지 않는다.
4. **전환은 안전 상태를 확인한 뒤 처리한다.** 수동 운전 중 다른 그룹을 선택하면 기존 teleop을 먼저 중지하고 0 명령 응답을 확인한 뒤 패널을 숨긴다. 차선 추종은 `OFF`, 도킹은 `DOCKING`/`UNDOCKING` 이외의 상태가 확인되어야 그룹을 떠날 수 있다. 상태 조회 실패, 정지 미확인, 이동 중인 도킹은 패널과 조작을 화면에 유지한다. 탭 전환은 세션을 유지하거나 명령을 재개하지 않는다. 매니페스트 교체와 인증 만료도 같은 안전 확인을 거치며, 확인할 수 없으면 기존 화면을 유지한다.
5. **작은 화면의 절차적 스택은 유지한다.** 720px 미만에서는 페이지가 세로로 쌓이고 스크롤될 수 있다. E-stop은 상단 바에 남고 가로 넘침을 만들지 않는다. 이 뷰포트에서는 데스크톱 3열 적합 판정을 주장하지 않는다.

**Alternatives:**

- act 영역에 스크롤을 허용하는 안은 화면 안에서 정지·운전을 한눈에 둔다는 D-201과 충돌해 제외한다.
- `overflow: hidden`으로 모든 panel을 고정 높이에 자르는 안은 조작을 발견할 수 없게 하므로 제외한다.
- 네 조작 panel을 계속 평면 배치하고 글자·대상 크기를 줄이는 안은 D-194의 최소 조작 대상 크기와 가독성 기준을 훼손하므로 제외한다.
- 조작을 `/setup`으로 옮기는 안은 운용 capability를 준비 절차에 섞고 D-278의 화면 책임을 흐려 제외한다.

**Consequences:**

보조 조작에 그룹 선택 한 번이 추가된다. 각 그룹 이름은 조작 목적을 직접 드러내고, 현재 선택 상태는 중립 강조로 표시한다. E-stop과 일반 조작의 의미색은 바꾸지 않는다. 탭을 실제 구현하기 전까지 D-201의 desktop 적합 상태는 HOLD다. 이 ADR은 운용 화면의 palette, API, role/capability 정책, teleop 속도·hold 계약 또는 다른 표면의 레이아웃을 바꾸지 않는다.

**Implementation and validation:**

| 단계 | 확인할 것 | 통과 기준 |
|---|---|---|
| G1 | 그룹 선택, panel mount/unmount 및 정지 동작 시험 | 그룹 전환 때 활성 teleop의 terminal zero가 확인되고 그룹 밖에서 명령이 재개되지 않음. 차선 추종 중지 전·도킹 진행 중·정지 확인 실패 시 현재 그룹이 유지됨. Viewer에는 조작 그룹 없음. |
| G2 | 실제 CORE 경로의 administrator/operator 캡처, 1366×768 및 390×844 | 선언 desktop에서 문서 scroll=0, sense/observe/act 고정, 활성 panel과 E-stop 모두 프레임 안, 축소/잘림 없음. 모바일은 가로 overflow=0, E-stop 가시. |
| G3 | 운용자 8명에게 2초 내 “움직일 수 있는가?”와 도킹/차선 조작 찾기 평가 | 역할과 상태가 다른 장면에서 정지·운전 구분을 확인하고, 보조 그룹 탐색의 혼동이 없어야 함. |

LOCAL CORE fixture 결과는 ROS-SIM·DEVICE·FIELD 증거가 아니다. G1/G2 통과만으로 D-153의 전체 제품 승인이나 D-201의 현장 수용을 주장하지 않는다.

**References:** [D-153](D-153-ui-ux.md), [D-194](D-194-shared-browser-controls.md), [D-201](D-201-fixed-grammar-surfaces-fit-contract.md), [D-218](D-218-web-dialogs-name-the-action.md), [D-274](D-274-local-core-browser-review-and-device-acceptance.md), [D-278](D-278-role-based-surface-ux-and-palette-review.md), [D-280](D-280-calm-intelligence-product-design-philosophy.md), concept 16 §3, §4, §7.1.
