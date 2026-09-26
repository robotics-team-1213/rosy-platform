---
module: web_common
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "web-common + dashboard 75 passed with ROSY_RUN_BROWSER_TESTS=1 (2026-09-26 Windows)"
    cmd: "powershell -NoProfile -Command \"$env:ROSY_RUN_BROWSER_TESTS='1'; python -m pytest src/hmi/web/test src/hmi/dashboard/test -q\""
  LOCAL:
    state: GO
    evidence: "실 CORE /console: visible Playwright desktop 1440px·mobile 390px, rose brand/menu, 0 missing kinds, no horizontal overflow, 0 page errors"
    cmd: "X:\\DevTemp\\rosy-modern-palette\\visible_review.py"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-72, D-194, D-195, D-277, D-285, D-286]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-rosy-modern-brand-palette.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/hmi/web`를 본다.
- 자체 `test/`가 토큰·팔레트·헤드리스·공유 조작 부품을 본다. 브라우저 버튼·글자 크기의 소스는 `components.css`와 `tokens.css`다(D-194). ament_cmake라 colcon test 배선은 없고 CI 4경로·직접 pytest로 실행한다.

## 다음 gate

1. D-277: 브랜드색은 ROSY 워드마크와 현재 역할 메뉴에만 쓰고, 상태·포커스·데이터 색과 분리한다.

## 현재 유효한 금지사항

- Do not copy tokens into consumers; link `/ui/tokens.css` (D-130.3).
