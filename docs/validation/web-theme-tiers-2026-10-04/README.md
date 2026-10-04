# 역할 표면 테마×뷰포트 캡처 회차 — 2026-10-04 (D-359 §7.8 첫 실행)

**판정 근거 tier: LOCAL(합성).** 실제 CORE 앱(FastAPI TestClient + Pinky Pro 프로파일 + 개발 인증 오버레이)을
Playwright 경로 차단으로 서빙해 찍은 저장소용 캡처다. 실물 로봇·실물 브라우저 기기·현장 조명 증거가 아니다.
사람 G3 시트도 이 회차에 없다.

## 셀 (18 = 표면 3 × 테마 2 × 뷰포트 3)

- 표면: `/console` `/setup` `/device` (관리자 개발 토큰 — 이 회차의 관심은 테마·뷰포트이지 역할 차이가 아니다)
- 테마: `dark`, `light` — 페이지 스크립트가 돌기 **전에** `localStorage.rosy.theme`을 지정(theme.js)해
  실제 테마 적용 상태를 찍는다. 토글 후유증이 아니다.
- 뷰포트: 1280×800(데스크톱), 390×844, 320×568

파일명: `robot-<surface>-<theme>-<W>x<H>.png`. 전 셀의 캡처 후 `data-theme` 속성이 지정 테마와
일치(`report.json` `rows[].data-theme`)했고 페이지 오류 0, 첫 응답 실패 0이었다.

## 재현

```bash
python tools/capture_surface_round.py --out-dir docs/validation/web-theme-tiers-2026-10-04
```

`tools/web_visible_roles.py`의 부팅·서빙 기계를 그대로 재사용한다.

## D-329 관계

이 회차는 `matrix.json`을 남기지 않는다 — 스키마 v1(`rosy.g2-matrix/1`)의 셀은 표면×상태×뷰포트이고
이 회차의 테마 차원은 파일명과 `report.json`이 소유한다. 테마 차원의 정식 수용은 다음 스키마 개정에서
판단한다.

## 남는 것

- Fleet 콘솔·게임 보드의 같은 격자 캡처(별도 회차 — Fleet 서버 기동이 필요하다).
- 밝은 테마를 운용 권장으로 올리는 판단은 사람 G3 + 현장 조명 관측 뒤다(D-359 Consequences).
