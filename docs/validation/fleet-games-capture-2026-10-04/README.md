# Fleet 콘솔·게임 보드 캡처 회차 — 2026-10-04 (D-359 §7.8 역할 표면의 나머지)

**판정 근거 tier: LOCAL(합성).** Fleet은 실제 앱(FastAPI TestClient + 가짜 로봇 2대)을,
게임은 실제 preview 서버(`PreviewServer`, D-101 `--preview`)를 띄워 찍었다.
실물 관제 PC·LAN·현장 조명 증거가 아니다. 사람 G3 시트도 이 회차에 없다.

## 셀 (6 = console 3 + games 3)

| 파일 | 표면 | 뷰포트 |
|---|---|---|
| `console-1920x1080.png` | Fleet 관제 콘솔 | 관제 PC |
| `console-390x844.png` | 위와 같음 | 전화 |
| `console-320x568.png` | 위와 같음 | 작은 전화(D-359 §7.8 선언) |
| `games-1280x800.png` | 경기 보드 | 노트북(경기 운영자) |
| `games-390x844.png` | 위와 같음 | 전화 |
| `games-320x568.png` | 위와 같음 | 작은 전화 |

Fleet은 dark 고정(`themes: [dark]`, surfaces.yaml)이라 테마 차원이 없다.
게임 보드는 자체 pitch 팔레트(`:root`)를 유지한다(D-153 크래프트 계획 P3 게이트).
전 셀 페이지 오류 0(`report.json`).

## 재현

```bash
python tools/capture_console_games_round.py \
    --out-dir docs/validation/fleet-games-capture-2026-10-04
```

## 남는 것

- 게임 보드·로봇 정지 readback 2대와 카메라(DEVICE 회차).
- Fleet 관제자 관점의 사람 G3 8항 시트.
