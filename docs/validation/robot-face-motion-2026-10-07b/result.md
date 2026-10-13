# D-504 얼굴 애니메이션 두 번째 LOCAL 점검

첫 번째 [확인](../robot-face-motion-2026-10-07/result.md)의 검정·장미색 두 색 GIF는 대각선 눈과 웃는 입의 가장자리가 계단처럼 보였다. 자산 생성기가 3배 해상도에서 그린 뒤 320×240으로 줄이도록 바꾸고, `fun`의 입을 넓혀 `happy`와 구분했다.

- 자동 확인: 여덟 첫 프레임 모두 중간색이 있고, GIF는 각 20프레임·100 ms다. 32×24로 축소한 다섯 운용 표정의 최소 전경 차이는 6.25%다. 여덟 자산 합계 511,159 bytes.
- 시각 확인: `happy`, `fun`, `interest`의 최종 첫 프레임을 320×240에서 열어 가장자리와 실루엣을 대조했다.
- 시험: 얼굴·상황표·문서 배치와 모듈 로그 시험 370 passed, 3 skipped; `known_failures.py` 0 NEW. 원시 기록은 X: `projects/rosy-platform/2026-10-07--203421--face-motion--11cd4d/logs/improved-pytest.txt`다. ADR lint 원시는 같은 `logs/improved-lint.txt`다.
- 범위: 브랜치의 호스트 렌더·코드 근거다. 로봇 LCD의 거리·각도·조도, CPU·RSS, 실제 상태 전이는 장치 적용 뒤 별도 관찰이 필요하다.
