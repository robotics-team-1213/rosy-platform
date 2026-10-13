# 배포 CI의 공용 tooltip 수정

- 대상: `shared/web/ui.js`, `components.css`, 실제 Chromium 회귀 시험과 기존 구조 크기 판정.
- 원인: `5da31e05cb89`의 CI에서 설명창이 Fleet 알림함의 정상 클릭을 가로챘다. 실패 후보는 적용하지 않았다.
- 수정: 설명창은 입력을 가로채지 않고 좌표로 hover 영역을 유지한다. 아래 조작에도 설명이 있을 때 기존 설명이 바뀌지 않으며, 클릭·focus·Escape·활성화 후 해제를 유지한다. 동료의 활성화 후 설명 해제 수정도 함께 통합했다.
- 독립 검토: `edd25738b1` 소스 승인. `ui.js` 811줄은 같은 tooltip 책임의 11줄 증가로 한정 수용했다. 기존 800줄 기준·성장 허용치·1000줄 hard tier는 그대로다. 다음 기능 확장 때 actionIcon·tooltip을 설치 자산 경계와 함께 분리한다.
- 정확한 소스의 원격 Chromium·구조 검사: 56 passed, zero NEW. 최신 main 통합 검사: 608 passed / 435 skipped, zero NEW (`d0e988abde2d`). 건너뛴 브라우저 검사는 실제 Chromium 56건의 증거와 구분한다.
- 이 기록은 소스·시험 증거다. 전체 CI·서명·설치·실행 수용은 별도 배포 기록으로 확인한다.
