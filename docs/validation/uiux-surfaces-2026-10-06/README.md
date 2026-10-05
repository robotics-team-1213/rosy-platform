# ROSY UI/UX 품질 확인 — 2026-10-06

**판정: 제품 전체 HOLD.** 이 회차는 `PRODUCT.md`의 UI/UX 목표를 현재 화면에서 확인하기 시작한 LOCAL 점검이다. D-280의 성격과 `DESIGN.md`의 토큰·표면 문법을 유지하며, GO 기준은 D-153 G1/G2/G3 그대로다. 브랜치 `uiux/rosy-operate-quality`에서 작성했다.

## 이번 회차의 질문과 근거

| 표면·질문 | 현재 LOCAL 캡처 | 확인한 것 | 남은 것 |
|---|---|---|---|
| 로봇 운용: 지금 움직여도 되는가? | [1366×768](captures/robot-console-1366x768.png), [390×844](captures/robot-console-390x844.png) | 데스크톱 감지·관측·조작이 같은 폭이다. 390px에서 조작이 카메라·지도보다 먼저 오고 비상 정지가 첫 화면에 있다. | 선언된 역할·상태 전체 G2, 실제 CORE/장치 상태, G3 전체 근거 검토. |
| Fleet: 어느 로봇에 주의가 필요한가? | [1920×1080](captures/fleet-console-1920x1080.png), [320×844](captures/fleet-console-320x844.png) | 데스크톱 현장·개입 칸이 같은 폭이다. 전화의 **기본** 목록은 릴레이 오류가 있는 `rosy_03`부터 보여 주며 비상 정지가 첫 화면에 있다. | 선언된 상태 전체 G2, 연결된 카메라·실제 사이트 PC/로봇 readback, G3 전체 근거 검토. |
| 게임 보드: 경기장·공·로봇·골이 보이는가? | [진행 1280×800](captures/games-play-1280x800.png), [최초 1280×800](captures/games-initial-1280x800.png), [지연 1280×800](captures/games-delayed-1280x800.png), [HOLD 1280×800](captures/games-hold-1280x800.png), [지연 390×800](captures/games-delayed-390x800.png) | 관측 정보가 적을 때 관측 카드를 내용 높이로 줄여 피치를 초점으로 둔다. 지연 화면은 마지막 수신 정보임을 밝히고 모바일에서도 정지가 보인다. | 현재 트리의 전체 상태 G2, 실물 카메라·경기 readback, G3 전체 근거 검토. |

로봇·Fleet 캡처는 FastAPI/Playwright fixture, 게임 캡처는 실제 PreviewServer와 fixture payload를 쓴 LOCAL 증거다. Fleet 전화의 `fleet_console_mobile_{width}.png`는 시험이 **전체 로봇 보기**를 누른 뒤 찍는 캡처여서 기본 예외 목록의 근거로 쓰지 않는다. 기본 목록은 위 `fleet-console-320x844.png`와 해당 브라우저 단언으로 확인했다.

현재 트리의 관련 G1 팔레트·토큰·반응형·Fleet 문법 시험은 **83 passed**다. Fleet 지도 적합·키보드 목표 확인 2 passed, 전화 기본 예외·넘침 검사 2 passed이고 세 실행 모두 `known_failures.py`가 0 NEW를 보고했다. 이는 이 회차에서 실행한 범위의 증거이며 D-153 G1 전체를 대체하지 않는다.

게임 보드 브라우저 전체는 **18 passed**, 게임 모듈은 **113 passed**였다. 관측 카드 축소 뒤 진행·최초·HOLD·정지 적합 4 passed와 데스크톱·390px 배치 1 passed를 다시 확인했다. 이 화면들은 관측 frame 없는 fixture이며 실제 카메라와 로봇 상태를 나타내지 않는다.

## 제품 범위와 판정 경계

D-153의 여섯 카드 중 운용자 콘솔·Fleet·게임 보드에만 이 회차의 새 캡처가 있다. 장비 런타임(`/setup`·`/device`)과 로봇 얼굴은 이전 [2026-09-29 회차](../uiux-surfaces-2026-09-29/README.md)의 LOCAL 검토를 현재 트리 전체 검증으로 승격하지 않는다. control 레거시 진단은 D-153에 따라 PARKED다. `shared/web/surfaces.yaml`에 이후 추가된 Cam·학습 검수 같은 활성 표면은 각자 질문·선언 뷰포트·상태 카드를 정해야 제품 전체 GO를 논할 수 있다.

**다음 판정 작업:** 각 활성 표면의 선언 상태·뷰포트 G2를 현재 트리에서 채우고, D-153의 여덟 G3 항목에 근거 셀을 적는다. 실제 장치·현장 수용은 LOCAL 캡처와 분리한다. 이 증거가 없으면 디자인이 마음에 들어 보이더라도 GO로 쓰지 않는다.
