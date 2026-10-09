<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# rosy_vision

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Python package for Rosy Vision: receive-only `rosy-overhead/1` WebSocket ingest of Rosy Cam frames, CPU ArUco detection, projection to the site map, and publication of derived sightings to Fleet (D-257, D-261). ROS-free; no `cmd_vel`. Fleet receives sighting JSON only, never JPEG.

## Key Files

| File | Description |
|------|-------------|
| `protocol.py` | Wire protocol: 20-byte frame header, `hello`/`config` JSON, `rosyov://` URI. Pure stdlib |
| `ingest.py` | `IngestServer`: one connection per source, latest-frame-only |
| `detect.py` | CPU ArUco detector; OpenCV isolated here |
| `project.py` | Marker observations to site map (uses the `games` homography) |
| `publish.py` | Source-token-only Fleet sighting client |
| `worker.py` | Latest-frame camera-to-Fleet pipeline, no queues |
| `track/` | D-457 markerless blob tracking (`background_blob.py`, `worker.py`, `fleet_client.py`) and D-472 `led_identity.py` (pure on/off/on LED blink detector; the worker sends Fleet a numbers-only verdict per identity challenge) |
| `vision_config.py` | Validated camera/map config; secrets resolved by env name |
| `pairing_sync.py` | Paired camera credentials synced from Fleet (token hashes only, D-341) |
| `rectify.py` | Display-only lens/plane rectification for preview (D-318) |
| `field_detect.py` | Field boundary proposal for operator review (D-360) |
| `map_register.py`, `map_worker.py` | D-375 lane-paint map registration proposal, run in a separate low-priority process |
| `cli.py` | `rosy-vision` entry point (`receive` etc.) |

## For AI Agents

### Working In This Directory

- `protocol.py` must match the Kotlin app (`operations/ui/cam`) byte for byte; the shared vector file `test/fixtures/protocol/overhead-ingest.v1.json` decides, not a local edit.
- Keep OpenCV out of `protocol.py`, `ingest.py`, `publish.py`; it belongs in `detect.py` and the proposal modules.
- Latest-only everywhere: do not add frame queues. Never trust the phone clock; use the receiver's own time minus `age_ms`.
- Proposals (field, map fit) and rectification are display-only; they never alter the raw frame used for sightings or become policy evidence.
- Never log or forward tokens; the worker publishes with a source token only.

### Testing Requirements

```bash
python -m pytest operations/vision/test -q
```

Key tests: `test_protocol.py`, `test_ingest.py`, `test_vision_detect.py`, `test_vision_project.py`, `test_vision_worker.py`, `test_vision_publish.py`, `test_vision_config.py`, `test_pairing_sync.py`, `test_pairing_e2e.py`, `test_preview_rectification.py`, `test_field_detect.py`, `test_map_register.py`, `test_vision_cli.py`, `test_led_identity.py`. Needs `websockets>=14`.

### Common Patterns

Small single-purpose modules; config validated up front; fake frames in `test/map_paint_frames.py`.

## Dependencies

### Internal

- `games.field.homography` (via `project.py`), `core_common.protocol.sightings` payload, Fleet sighting API

### External

- websockets>=14, opencv-contrib-python-headless, numpy, httpx
