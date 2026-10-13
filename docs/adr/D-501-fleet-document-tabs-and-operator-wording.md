## D-501 Rosy Fleet 네 문서는 같은 탭 줄을 쓴다 — 다른 문서로 가는 길은 탭 하나, operator 역할의 한국어는 "운영자"

**Status:** Accepted (2026-10-07, 사용자 결정). Fleet 웹 네 문서(`/console`, `/console/install`, `/console/site-map`, `/console/cell`)의 문서 사이 이동과 operator 역할 표기만 정한다. 각 문서의 머리(접속·역할·테마·시계·비상 정지) 구성과 본문 배치, 웹 경로, API, 저장소 키는 바꾸지 않는다.

**부분 대체:** [D-493](D-493-fleet-console-map-first-layout.md) 4항의 "다른 문서 링크는 머리의 접힘 칸 안에 하나씩"을 대체한다. 링크는 탭 줄로 옮긴다.

잇는 결정: D-359 · D-410 · D-446 · [D-487](D-487-site-console-displays-as-rosy-fleet-birdseye.md) · [D-493](D-493-fleet-console-map-first-layout.md).

### Context

2026-10-07 critique(D-493 Context)의 3단계 항목이다. 문서 사이를 오가는 길이 문서마다 달랐다.
- `/console`: 머리 접힘 칸의 링크 셋(D-493).
- `/console/install`: 본문 위 설명 칸 "설치·보정 화면"과 "운용 화면" 링크.
- `/console/cell`, `/console/site-map`: 본문 중간의 "관제 화면으로 돌아가기" 링크, 이름표 링크.

같은 역할의 이름도 갈렸다. 역할 표지와 Cell·현장 지도는 "운영자", 권한 안내(`OPERATOR_REASON`)와 설치 화면 일부는 "운용자"였다. ADR은 운영자 321회·운용자 115회다.

### Decision

1. **탭 줄.** 네 문서는 머리 바로 아래에 같은 `<nav class="doc-tabs" aria-label="Rosy Fleet 문서">`를 둔다. 순서는 관제 · 설치·보정 · 현장 지도 · Cell이고, 현재 문서는 `aria-current="page"`다. 모양은 `/console/assets/doc-tabs.css` 하나가 정한다(토큰만, CSP 그대로).
2. **다른 길은 없앤다.** `/console` 머리의 링크 칸, 설치 화면의 설명 칸, Cell·현장 지도의 "관제 화면으로 돌아가기"를 없앤다. 이름표 `ui-brand`의 `/console` 링크는 그대로다.
3. **지도 높이.** `/console`의 지도는 탭 줄 높이만큼 줄여 1920×1080에서 문서가 스크롤되지 않는다(D-493 2항).
4. **표기.** operator 역할의 한국어는 "운영자"다. Fleet 웹(`operations/fleet/fleet/server/web`)과 그 시험의 "운용자"를 "운영자"로 바꾼다. 로봇 쪽 화면(`middleware/ui`)과 PRODUCT.md의 사용자 이름은 이 ADR 범위 밖이다.

### Consequences

- 각 문서의 머리는 아직 둘로 갈린다. `/console`·설치는 접속·역할·테마·시계가 머리에 있고, Cell·현장 지도는 접속 칸이 머리 아래 줄이다. 머리 통일은 다음 단계다.
- 시작점 설정은 관제 지도 캔버스로 위치를 고르므로 관제에 남는다. 설치 화면으로 옮기려면 그쪽에 지도가 필요하다.

### Validation

- `operations/fleet/test/test_doc_tabs.py`: 네 문서가 같은 순서의 탭을 갖고 자신만 현재로 표시하며, 돌아가기 문장·설명 칸·머리 링크가 없다.
- `test/test_fleet_console_browser.py`: 1920×1080 적합, 탭의 설치 링크가 보인다.
