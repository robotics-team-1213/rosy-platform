# D-654 ROSY 브랜드 소스 검증

`c4f94646bd`의 접속·개발 모드·지도·교통·계정·헤더 Chromium 회귀 81개가 통과했고 NEW 0이다. 앞선 `15b3f4dd22` CI 실패를 반영해 D-658의 항상 접힌 접속 상세를 시험에서 명시적으로 열고, 개발 배지의 두 줄 상태 그룹과 고정 높이를 검증한다. 로그인 준비를 기다리는 흐름과 로그인 유지·새 탭·로그아웃도 확인했다. 로그: `X:/DevTemp/projects/rosy-platform/2026-10-11--192437--rosy-brand--d27650/logs/header-access-complete/run-1.txt`.

D-658 헤더 영역 변경의 `326e0582b7` 원격 회귀 15개가 통과했고 NEW 0이다. 네 문서의 동일 헤더, 접근성 그룹, 320–1920px 여섯 폭, 접속 거부·자동 펼침, 알림과 안전 그룹 소속, 상태 배지의 동일 박스 계산을 확인했다. 실패했던 320px 헤더 높이는 상태 배지의 기존 토큰 크기와 border-box를 공용 규칙에 적용해 해결했다. 테스트 기준이나 실패 목록을 완화하지 않았다. 로그: `X:/DevTemp/projects/rosy-platform/2026-10-11--192437--rosy-brand--d27650/logs/header-regions-qualified/run-1.txt`.

`f62299e82b`의 원격 검사 78개가 통과했고 `known_failures.py`는 NEW 0이다. 작은 심볼 16/24/48px, 파생 타일의 정본 기하·토큰 일치, allowlist·설치 목록, 두 테마의 실제 공용 브랜드, 네 Fleet 문서와 여섯 폭, Cell의 320px 비상 정지 접근을 포함한다. 데스크톱과 모바일 스크린샷을 직접 확인했다. 로그: `X:/DevTemp/projects/rosy-platform/2026-10-11--192437--rosy-brand--d27650/logs/browser/run-1.txt`.

브랜드 심볼은 기존 `ui-brand`를 통해 Fleet·Robot·Pilot 웹 표면과 공용 template에 연결된다. 역할별 앱 favicon·런처와 이름은 유지한다. 생성 견본의 가상 화면과 역할 색 점은 실제 표시나 상태 계약으로 사용하지 않는다.

앞선 아이콘 밀도 변경의 `bec3528c5` CI에서는 로봇 상세가 갱신되는 순간 분리된 옛 버튼을 측정하는 경합이 확인됐다. 같은 48px 이상 높이·14px 글자·12px 여백 기준을 유지하고 Playwright의 live locator 단언으로 재확인하도록 수정했다. 실패 목록에 추가하지 않았다.

공식 착지·정확한 출시 SHA CI·서명 설치·설치본 화면은 별도 증거다. 설치 증거는 `artifacts/receipts/rosy-brand-2026-10-11/<source-sha>/receipt.json`에 보존한다. native Android 설치·실물 주행·외부 Tailscale 기기 접속 수용을 소스 검증으로 주장하지 않는다.
