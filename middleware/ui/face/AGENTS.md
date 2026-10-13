<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# emotion

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

LCD emotion GIFs (`set_emotion` service) and PWR-003 info-card renderer (`info_screen.py`). Info-screen is ROS-free PIL so tests do not need an LCD.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; python3-pil, interfaces |
| `setup.py` / `setup.cfg` | Package install |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `emotion/` | Python package `emotion` (LCD node, info-screen renderer, hardware LCD helper) + emotion GIFs (see `emotion/AGENTS.md`) |
| `test/` | `test_info_screen.py` + ament linters (see `test/AGENTS.md`) |
| `resource/` | ament marker |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- `info_screen.py` draws 320×240 landscape; LCD code rotates/resizes. Keep that contract.
- CORE publishes `display/info` JSON; this package renders it. Do not put PIL in `core`.

### Testing Requirements

```bash
PYTHONPATH=middleware/ui/face python3 -m pytest middleware/ui/face/test/test_info_screen.py -v
```

### Common Patterns

Share-dir lookup: `get_package_share_directory('emotion')/emotion`.

## Dependencies

### Internal

- `interfaces/Emotion`
- Power manager wake/info hold in `core`

### External

- PIL, rclpy, hardware LCD via `rosy_lcd.py`

<!-- MANUAL: -->

### LCD 표시 역할

- 이름·로그인 코드·현재 정보·감정만 표시하며 운용 입력을 소유하지 않는다. 공용 팔레트 의미와 token parity를 유지한다.
- 320×240 물리 표시, 글자 맞춤과 정보 카드 기하는 매체 계약이다. 웹 버튼/서체 척도를 그대로 강제하지 않으며 실기 LCD 수용을 호스트 그림 시험과 구분한다.
