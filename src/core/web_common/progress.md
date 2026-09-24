---
module: web_common
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-24 }
gates:
  SOURCE:
    state: GO
    evidence: "공유 조작 부품 포함 web_common·표면 계약 — 120 passed (2026-09-24 Windows)"
    cmd: "python -m pytest src/core/web_common/test -q"
  LOCAL:
    state: GO
    evidence: "120 passed, 공유 부품 경로 포함 (2026-09-24 Windows)"
    cmd: "python -m pytest src/core/web_common/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-72, D-187, D-188]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/core/web_common`를 본다.
- 자체 `test/`가 토큰·팔레트·헤드리스·공유 조작 부품을 본다. 브라우저 버튼·글자 크기의 소스는 `components.css`와 `tokens.css`다(D-187). ament_cmake라 colcon test 배선은 없고 CI 4경로·직접 pytest로 실행한다.

## 다음 gate

1. 시험 범위를 공개면(팔레트·토큰) 계약으로 넓힌다.

## 현재 유효한 금지사항

- Do not copy tokens into consumers; link `/ui/tokens.css` (D-130.3).
