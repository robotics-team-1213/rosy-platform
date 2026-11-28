
# rosy_vision

**Parent context:** `../AGENTS.md`

## Purpose

Python package for Rosy Vision: receive-only `rosy-overhead/1` WebSocket ingest of Rosy Cam frames, CPU ArUco detection, projection to the site map, and publication of derived sightings to Fleet (D-257, D-261). ROS-free; no `cmd_vel`. Fleet receives sighting JSON only, never JPEG.

## For AI Agents

### Working In This Directory

- `protocol.py` must match the Kotlin app (`operations/site_ui/cam`) byte for byte; the shared vector file `test/fixtures/protocol/overhead-ingest.v1.json` decides, not a local edit.
- Keep OpenCV out of `protocol.py`, `ingest.py`, `publish.py`; it belongs in `detect.py` and the proposal modules.
- Latest-only everywhere (`ingest.py`, `worker.py`): no frame queues. Never trust the phone clock; use the receiver's time minus `age_ms`.
- Proposals (`field_detect.py` D-360, `map_register.py` D-375) and rectification (`rectify.py`, D-318) are display-only; they never alter the raw frame used for sightings or become policy evidence. `stack_tiers.py` and `correspondence.py` (D-1007, review-only) are not wired to Fleet.
- Every Fleet POST goes through `PostGuard.post` (`post_guard.py`: stale payloads over 0.8 s are dropped and counted, never queued); httpx clients keep `keepalive_expiry` at 30 s, below Fleet's 75 s and Caddy's idle pool.
- A Pinky pose without its own marker in the frame is a home guess: never a sighting, never in the anchors POST.
- `track/` is display-only (D-457 blob tracking, anchor head tracker at most 1 Hz, D-587 marker sightings); `led_identity.py` (D-472) is a pure blink detector and sends Fleet numbers only.
- Never log or forward tokens; publish with a source token only. `pairing_sync.py` syncs token hashes only (D-341).

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/vision" -- operations/overhead/test -q
```

D-584: remote only. Needs `websockets>=14`. Fake frames: `test/map_paint_frames.py`. Deps: `core_common.homography`, `core_common.protocol.sightings`, Fleet sighting API.
