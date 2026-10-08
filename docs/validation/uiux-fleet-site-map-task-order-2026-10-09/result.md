# Fleet 현장 지도 작업 순서 · 2026-10-09

- 기준: `uiux/site-map-task-order`, 분기 당시 로컬 `main` `eabbb013274904634586bf84eeb95dc5dfda2dd6`.
- 발견: 320×568 현장 지도에서 지도 다음에 표시 전용 평면 영상 도구와 지도 초안 편집이 이어져, 경로 미리보기와 운행 조작이 긴 화면 아래로 밀렸다. 변경 전 실제 Fleet FastAPI·합성 응답의 전체 페이지를 캡처했다.
- 변경: 문서 읽기·키보드 순서를 지도 → 경로 미리보기 → 운행 → 초안 편집 → 지도 가르치기로 정리했다. 데스크톱에서는 경로·운행을 왼쪽, 초안 편집을 오른쪽에 둔다. 평면 영상 좌표 도구는 지도 바로 아래의 키보드 접근 가능한 접힌 항목으로 둔다. 펼쳐도 영상 좌표는 표시 전용이며 운행 목적지로 전달하지 않는다.
- LOCAL 화면: 1440×1000, 390×844, 320×568에서 지도와 경로 작업의 순서, 모바일 가로 넘침 없음, 비상 정지 접근을 캡처로 확인했다. 320px 변경 후에는 경로 미리보기 다음에 운행이 나오고 초안 편집은 그 아래에 있다.
- 검증: 실제 Fleet FastAPI 정적 자산·합성 로봇/지도 응답의 Chromium 검사 7 passed(경로 계획/초안 활성화 3폭, 영상 좌표 표시 전용과 키보드 펼침, 3폭 레이아웃). `known_failures.py` 0 NEW, `git diff --check` 통과. Impeccable detector `[]`; 서버 절대경로 CSS를 로컬 파일로 해석하지 못해 색상 토큰 판정은 제한된다.
- 임시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-09--site-map-task-order/`의 `before/`, `after/`, `before-run.txt`, `after-run.txt`.
  - 변경 전 `before/site-map-fresh-320x568.png` SHA-256 `68c174eff9eedcc8a03c9107122e82cf03ecdba37a481936cf990f18c8dedcd5`
  - 변경 후 `after/site-map-fresh-320x568.png` SHA-256 `8a3283d02151f39d8fed02e7a175f2735b803056155746211e2c7aedb243903b`
  - 변경 후 `after/site-map-fresh-390x844.png` SHA-256 `0c8cce2dfc6a8d707563ea5f50c3a3284564cfe9a3e535c79b5850ab9c6e6db7`
  - 변경 후 `after/site-map-fresh-1440x1000.png` SHA-256 `82715f1d55f4ed5170d9d99566a3e809095af44d61121a4376e0d1c48e6ea102`
- 판정: SOURCE/LOCAL 작업 순서와 반응형 표현 근거를 보강했다. 실사이트 설치본, 실제 로봇의 지도 위치·경로 추종·SLAM, DEVICE/FIELD, 운영 G3 및 전체 D-153 G2는 HOLD.
