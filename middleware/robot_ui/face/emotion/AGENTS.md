
# emotion (Python package)

**Parent context:** `../AGENTS.md`

## Purpose

LCD node, GIF playback, ROS-free info-card drawing, and the GIF assets themselves.
Installed to `share/emotion/emotion`; runtime lookup is
`get_package_share_directory('emotion')/emotion`.

## Key Files

| File | Description |
|------|-------------|
| `rosy_lcd.py` | Hardware LCD helper (SPI, RPi.GPIO — device only) |

## For AI Agents

### Working In This Directory

- Known emotions: `character.NAMES` (= `core_common.face_screen.FACES`). Unknown
  names should fail closed. Filenames are the `set_emotion` names — renaming a
  GIF without updating the service contract breaks the LCD.
- Info-screen cards are drawn in PIL (`info_screen.py`), not as GIFs here.
- 2026-09-21 (D-153 회차1 F-01 수정): 재편(9b77daa)이 선언만 `emotion.*`로
  바꾸고 파일을 `rosy_emotion/`에 두던 불일치를 닫았다 — 파이썐 파일은 이
  디렉터리에 평평하게 두고 `rosy_emotion.py`는 `emotion.py`로 환원했다.

### Testing Requirements

```bash
PYTHONPATH=middleware/robot_ui/face python3 -m pytest middleware/robot_ui/face/test -v
```

### Common Patterns

GIF play on a thread so the service callback does not block forever.

## Dependencies

### Internal

- `interfaces/Emotion`
- CORE publishes `display/info` JSON; this package renders it

### External

- PIL (renderer), rclpy (node only), hardware LCD via `rosy_lcd.py`
