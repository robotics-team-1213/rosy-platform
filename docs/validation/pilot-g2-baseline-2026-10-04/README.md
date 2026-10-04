# Rosy Pilot G2 기준선 셀 — 2026-10-04

**판정 근거 tier: LOCAL(합성).** `test/dev_server.py` 가짜 CORE(토큰 `devtoken`)가 서빙한 `/pilot`를
headless Chromium으로 돌린 저장소용 합성 캡처이다. 실물 로봇·실물 태블릿·현장 조명 증거가 아니다
(D-91, D-153.3). 사람 G3 시트도 이 회차에 없다.

## 셀 (9)

| 파일 | 화면 | 뷰포트 |
|---|---|---|
| `gate-{tablet-land,tablet-port,phone}.png` | 접속(토큰 게이트) | 2000×1200, 1200×2000, 390×844 |
| `lobby-{tablet-land,tablet-port,phone}.png` | 로그인 뒤 진입 대기 | 위와 같음 |
| `drive-{tablet-land,tablet-port,phone}.png` | 주행(카메라+스틱+페달) | 위와 같음 |

1차 기기는 현장 태블릿(Lenovo 1200×2000 가로 기준, D-323). 전화 390×844는 WEB-001 인접 확인용.

## 기계 계측 (같은 회차, 수정 후)

정의: 정지 버튼=`[data-estop]` 가시 박스. 조작부=보이는 `button`/`ui-button`/스틱 최소 변.
대비=본문 텍스트 계산색 대 유효 바탕(WCAG 비). 텍스트 바닥=12px(DESIGN.md Micro).
조작 면적 바닥=44px(DESIGN.md, 모든 티어).

| 셀 | e-stop | 44px 미만 조작부 | 4.5:1 미만 텍스트 | 가로 넘침 |
|---|---|---|---|---|
| gate 3종 | 111×58 보임 | 0 | 0 | 0px |
| drive 3종(태블릿) | 111×58 보임 | 0 | 0 | 0px |
| drive 390×844 | 111×58 보임 | 0 | 0 | 0px |
| drive 320×568(계측만) | 111×58 보임 | 0 | 0 | 0px |

12px 텍스트(단위·각주류)는 승인된 Micro 단계(DESIGN.md "12px가 바닥")라 위반이 아니다.

## 이번 회차의 수정

- `styles.css` — 좁은 티어(`width < 30rem`)에서 속도 프리셋(저속/보통/빠름)과 정밀 토글이
  레이아웃 규칙(`data-drive-layout="side|below"`의 `min-width: 0`) 때문에 내용 폭으로 줄어
  44px 바닥을 뚫었다(390px에서 36px, 320px에서 42px). 파일 끝에 같은 특이도의 되돌림
  (min-width 2.75rem + flex 0 1 auto)을 두어 바닥을 회복했다. 넓은 화면의 flex 채움은 불변.

## 재현

```bash
python -X utf8 <이 폴더의 캡처 스크립트 초안은 X:\DevTemp\opencode\pilot-craft\capture.py —
worktree 경로를 담은 스크래치 원본. 절차: dev_server 기동 → /pilot → devtoken → 진입 →
set_viewport_size 3종 → screenshot>
```

측정 스크립트(대비·면적)는 같은 폴더의 `measure` 초안을 따랐다(계산 로직은 README 표의 정의와 동일).

## 다음 회차에 남는 것

- 사람 G3 8항 시트(운전자 1인 이상) — 이 캡처는 사람 판정이 아니다.
- 실물 태블릿·현장 조도에서의 관측(DEVICE 회차, 사다리 P2와 묶음).
- 밝은 테마는 pilot이 어둡게 고정(theme_reason)이라 범위 밖.
