<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-21 | Updated: 2026-09-22 -->

# signal

## Purpose

Traffic-signal controller contract (ROSY-SIGNAL-001, Draft) and ESP32 reference
firmware. 접점 스위치로 켜지는 저가 LED 신호등을 관제(Fleet 콘솔)가 제어하게 하는
site 장비. The controller's first duty is not control — it is **visible
untrustworthiness**: on boot, supervisor silence, or reboot, every lamp shows
FLASH RED until a fresh authenticated command arrives. Site 장비라 ROS import 가
없고, Fleet 서버와는 LAN 위 HTTP 계약으로만 만난다(D-59: 디바이스는 계약 버스만).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | ROSY-SIGNAL-001: `/status`·`/command` 스키마, 인증, 페일세이프, 전기/규정 규칙 |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `firmware/` | ESP32 Arduino sketch (see `firmware/AGENTS.md`) |
| `observer/` | 호스트 관측 서비스 — 카메라로 램프 상태를 실측하는 **읽기 전용** 컴포넌트 (명령 경로 없음, see `observer/README.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Rules in order: (1) boot into fail-safe flash, (2) supervisor silence (> `HEARTBEAT_TIMEOUT_MS`) → fail-safe flash, (3) never red+green, (4) commands require the `X-Rosy-Token` and a fresh `seq`, (5) serve `/status` with required fields.
- 신호등은 표시 장치지 안전 인터록이 아니다. 로봇 CORE 가 신호등을 제어하거나 신호등 보고를 안전 근거로 삼는 설계는 만들지 않는다.
- 여러 신호기 사이의 순서는 Fleet 이 정한다(D-12) — 장치 안 `cycle` 은 시연·벤치용 반복 패턴이다.
- Wi-Fi credentials and the command token must not appear in sources; `test/test_signal_contract.py` fails the build if they do.
- Fleet G-S3 클라이언트·엔드포인트·UI는 `src/site/fleet`에 있다. 장치 계약을 바꿀 때는 Fleet 파서와 `test/test_signal_contract.py`를 함께 검증한다.

### Testing Requirements

```bash
python3 -m pytest test/test_signal_contract.py -q
```

Host pytest (Windows OK) — README↔펌웨어 대조는 소스 스캔이다. 벤치(G-S1)와
펌웨어 빌드(ARTIFACT)는 하드웨어에서 수동이다.

### Common Patterns

Contract in README; implementation in `firmware/rosy_signal/rosy_signal.ino`; client in `src/site/fleet/fleet/server/signals.py` (G-S3).

## Dependencies

### Internal

- Design: `docs/plans/2026-09-21-traffic-light-controller-research.md`
- Precedent: `firmware/dock/README.md` (ROSY-DOCK-001), `docs/plans/2026-09-14-site-middleware-role-fabric-design.md` (D-59)

### External

- ESP32 Arduino core (WiFi, WebServer, Preferences/NVS), ArduinoJson 6.x

<!-- MANUAL: -->
