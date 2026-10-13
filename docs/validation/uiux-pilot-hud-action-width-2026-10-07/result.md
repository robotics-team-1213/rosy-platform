# Pilot 휴대폰 HUD 행동 폭 — LOCAL

기준 로컬 `main`은 `6c1e9855d`다. 390×844 주행 HUD에서는 「전체 영상」·「화면 채우기」·「도구」가 한 줄, 「조종 종료」만 다음 줄에 남았다. 320×568에서는 상단 HUD의 「도구」와 「조종 종료」가 각각 80px·111.86px였다. 선언된 작은 폭에서 동등 행동이 같은 가용 폭을 쓰라는 `DESIGN.md` 규칙과 맞지 않았다.

휴대폰 티어의 HUD 행동을 두 칸 격자로 바꿨다. 390px은 영상 보기 두 개와 도구·종료 두 개가 각각 한 줄을 채우고, 320px 짧은 화면은 영상 보기를 기존 도구 패널에 유지하면서 도구·종료만 같은 폭으로 나란히 둔다. 조작·권한·비상 정지의 동작은 바꾸지 않았다.

수정 전 렌더 폭 검사: **3 passed, 2 failed**, `known_failures.py` **2 NEW** (`X:/DevTemp/pilot-hud-actions/red.txt`). 수정 후 같은 카메라·조작 배치 다섯 폭 **5 passed**, **0 NEW** (`green.txt`), 비상 카메라·속도/배터리 네 상태·로봇 녹화 시트와 카메라 배치 합계 **17 passed**, **0 NEW** (`states.txt`). 버튼 폭 차이 ≤1px, 44px 이상 표적, 행 정렬, 카메라 표시 면적 >20%, 영상 비겹침을 검사했다. D-153 관련 토큰·팔레트·문법·증거·반응형 계약 **92 passed**, **0 NEW** (`contracts.txt`).

수정 후 원본은 `X:/DevTemp/pilot-hud-actions/green-shots/pilot-drive-current-390x844.png` (SHA256 `b768bb5c1e357068983b528c999659f873895e5e5d18bdf258977d7117714b99`)와 `pilot-drive-current-320x568.png` (SHA256 `eed14d01eb051058eca87373d99dae813683a33782871e4ae024d4bf8840cd58`)이다. 두 화면을 원본 크기로 확인했다.

이는 합성 CORE와 로컬 Chromium의 Pilot G2 **부분 근거**다. 전체 선언 상태·폭, 실제 설치 태블릿·로봇 readback, 운전자 G3가 없으므로 Pilot과 제품 전체는 **HOLD**다.
