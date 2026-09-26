---
module: dashboard
logical_modules: []
owner: 화면
last_verified: { commit: "uncommitted", date: 2026-09-25 }
gates:
  SOURCE:
    state: GO
    evidence: "운용 화면 정적 파일이 API 패키지에서 이 폴더로 옮겨졌고, 파일 존재·인라인 스크립트 없음 시험이 통과 (2026-09-25)"
    cmd: "python -m pytest src/hmi/dashboard/test src/runtime/gateway/test/test_dashboard_no_bundler.py -q"
  LOCAL:
    state: GO
    evidence: "대시보드 계약 시험이 이 폴더를 읽고 통과 (2026-09-25 Windows)"
    cmd: "python -m pytest src/hmi/dashboard/test src/runtime/gateway/test/test_dashboard.py src/runtime/gateway/test/test_console_layout.py -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "share/dashboard 설치를 이미지에서 본 기록이 없다"
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-23, D-77, D-243]
plans: []
---

## 지금 상태

- 운용 콘솔의 HTML·JS·CSS는 여기 있다. FastAPI는 `src/runtime/api_web`이 같은 프로세스에서 이 파일을 읽는다.
- 공용 토큰은 `src/hmi/web`이다. 얼굴 LCD는 `src/hmi/face`다.

## 다음 gate

1. ARTIFACT: 이미지에 `dashboard` 패키지가 설치된다.

## 현재 유효한 금지사항

- 이 폴더에 빌드 단계나 인라인 스크립트를 넣지 않는다.
- Fleet·게임 화면을 여기로 가져오지 않는다.
