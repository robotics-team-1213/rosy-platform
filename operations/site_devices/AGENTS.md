<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-10-03 -->

# site_devices

## Purpose

사이트 장치(D-429 §2): 펌웨어와 장치 계약. Colcon 밖이며 로봇 이미지에 넣지 않는다. `firmware/` 하위 폴더는 D-430 §1 안전 층(2층)이라 바꾸는 커밋에 `Safety-Review:` trailer가 필요하다. D-427 wave 3b에서 저장소 최상위 `firmware/`에서 옮겼다.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dock/` | ROSY-DOCK-001 충전 도크 (see `dock/AGENTS.md`) |
| `signal/` | ROSY-SIGNAL-001 신호 제어 (see `signal/AGENTS.md`). 관측기는 `../vision/signal_observer` |

<!-- MANUAL: -->
