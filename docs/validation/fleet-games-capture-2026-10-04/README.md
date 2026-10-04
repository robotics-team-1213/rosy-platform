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

## 독립 화면 재검토 — UX HOLD

2026-10-04 실제 console-1920x1080 PNG는 기본 브라우저 스타일, 큰 아이콘, 접속 인증 필요와 로봇 목록 로딩 상태다. dark 표면·실제 인증·앱 준비가 완료된 정상 UI 증거가 아니다. 도구는 API/console 인증을 fixture로 주입하고 method를 GET으로 바꾸며 CSP를 보존하지 않는다. 페이지 오류 0만으로 인증·스타일·로딩 완료·정지·overflow를 보증할 수 없다. 원본 캡처와 report는 실패 관측으로 보존하며 LOCAL UX/G3·DEVICE 수락은 HOLD다. 정상 역할 로그인·CSP·method/body 유지와 화면 준비·스타일·반응형 상태 검사가 필요하다.
