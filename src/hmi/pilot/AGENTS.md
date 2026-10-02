<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-29 | Updated: 2026-09-29 -->

# pilot

## Purpose

Rosy Pilot 원격 조종 표면(D-323). 정적 파일이며 `core_api_web`이 `/pilot` 으로 서빙한다 — dashboard와 같은 D-23 임베디드 패턴. v1 조종 대상은 Pinky 주행 1대, OMX는 `drivers/registry` 확정점만 선행한다(D-296). 앱은 `/api/v1`·`/ws/*` same-origin 만 말하고 ROS를 모른다(CORE SRS §1.3).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` / `CMakeLists.txt` | ament_cmake; installs to `share/pilot` |
| `index.html` | web_common `template.html` 기반 `ui-shell`(grammar `spatial`) |
| `styles.css` | 표면 규칙만 — 색·타이포는 `tokens.css`(D-130.3) |
| `stick.js` | 입력 → `{linear, angular}` 순수 매핑(데드존·감도 곡선·프리셋·반전) |
| `recording.js` | D-411 로봇 녹화 순수 표시 판정(경과·크기 서식, 토글, 거부 코드, "녹화본" 시트 행·차단 사유) |
| `screens/robot-recording.js` | D-411 로봇 녹화 HUD 토글·"녹화본" 시트 DOM(폴링, 시작/정지, 받기 — 정지 중에만, 짧은 본문은 실패) |
| `progress.md` | Current gate snapshot (SOURCE→FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Node 서브프로세스 순수 시험(`test_stick.py`)과 브라우저 시험(예정) |

## For AI Agents

### Working In This Directory

- Harness (D-61): 변경 뒤 `logs.md` 추가, gate 가 움직이면 `progress.md` 갱신, 루트에서 `python tools/harness/rosy_harness.py generate`.
- CSP 인라인 스크립트·스타일 금지. 같은 출처의 `/api/v1`·`/ws/*` 만 호출한다.
- 새 JS 모듈은 `api/app.py`의 `pilot_assets` 와 `CMakeLists.txt` 에 함께 등록한다(빠뜨리면 404).
- **hold-to-drive**: 손을 떼면·탭이 화면을 벗어나면·게임패드가 끊기면 즉시 0 을 발행한다.
- 토큰은 D-193 저장 규칙(sessionStorage 기본). URL·쿠키·콘솔에 두지 않는다. 실기 주소·계정은 `private/`(D-226).
- 1차 기기는 현장 태블릿(Lenovo 1200×2000, 가로 기준).

### Testing Requirements

```bash
python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py -q
```

### Common Patterns

import 방향은 단방향: web_common(ui) ← client/link/stick ← screens ← app. `stick.js` 는 DOM·네트워크·시계를 모르는 순수 함수만 둔다.

## Dependencies

### Internal

- `api/app.py` FileResponse + MIME allowlist

### External

없음 (브라우저 API 만)

<!-- MANUAL: -->
