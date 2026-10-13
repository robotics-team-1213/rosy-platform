# 게임 보드 정지 요청 G2 폭 확인 — 2026-10-07

[제품 UI/UX 회차](../uiux-surfaces-2026-10-06/README.md)의 `game-board` 부분 근거를 추가한다. 기준 소스는 로컬 `main` `833397522`에서 분기한 `uiux/game-stop-pending-width`이다. 실제 `PreviewServer`와 Chromium에서 정지 `/stop` 응답을 보류한 뒤 시간 초과를 재생했다.

| 상태 | 1280×800 | 390×844 | 320×568 |
|---|---|---|---|
| 요청 보류 | 정지 비활성·「정지 요청 중」 | 같은 상태, 첫 화면 | 같은 상태, 첫 화면 |
| 5초 시간 초과 | 재시도 가능·시간 초과 문구 | 같은 상태, 첫 화면 | 같은 상태, 첫 화면 |

세 폭 모두 문서 가로 넘침 0, 정지 버튼과 상태 문구가 뷰포트 안에 있었다. 전화 두 폭에서는 정지 버튼이 점수 칸과 같은 시작점·너비였다. 320/390px 원본을 눈으로 읽었다. 브라우저 전체 **34 passed**, `known_failures.py` **0 NEW** (`X:/DevTemp/projects/rosy-platform/2026-10-07--game-stop-g2/logs/browser-full.txt`, SHA-256 `3fc508b18941f1ca3cd409091fece091438c94077e6717fb3ef5f6205eb31819`). `main` 병합 뒤 집중 재실행도 **3 passed**, **0 NEW**였다(`logs/post-merge.txt`). 여섯 PNG는 같은 X:의 `evidence/games_board_stop_{pending,timeout}_{1280x800,390x844,320x568}.png`; 재실행 뒤 파일별 해시는 `capture-hashes.txt` (SHA-256 `868ad53839880e311ae8ad3917ab93210306c41ed7be0f6756b4633a2f4b9a89`)에 있다.

이것은 호스트 브라우저와 응답 보류 fixture의 **LOCAL G2 부분 근거**다. 실제 경기·카메라, 로봇의 물리 정지 readback, 남은 선언 상태와 사용자의 G3 독회는 확인하지 않았으므로 `game-board`와 제품 전체는 **HOLD**다.
