---
title: A CPU-bound job on asyncio.to_thread starved the ceiling-camera ingest loop and stopped the phone for good
date: 2026-10-01
category: runtime-errors
module: src/site/vision (rosy_vision ingest, map-proposal) and src/site/cam (Rosy Cam close handling)
problem_type: runtime_error
component: service_layer
symptoms:
  - "/api/vision/sources/{id}/frame took 10-15 s while a map-proposal ran"
  - "phone websocket dropped and reconnected (frame_seq reset 13 -> 0), 3 fps fell to 0.5 fps with 116 frames skipped"
  - "Rosy Cam stopped permanently with '앱과 수신기의 버전이 맞지 않아 연결을 멈췄습니다' (close 4400 'no hello')"
  - "map fit falsely rejected (paint match 0.79) on a frame degraded during the stall; a clean frame scored 0.83"
root_cause: concurrency
resolution_type: code_fix
severity: high
framework_version: python 3.12 websockets 14+ (site container)
tags: [asyncio, to-thread, gil, event-loop-starvation, websockets, close-codes, rosy-cam, rosy-vision, map-proposal, d-375, d-341]
---

# A CPU-bound job on asyncio.to_thread starved the ceiling-camera ingest loop and stopped the phone for good

## Problem
Vision serves the phone's frame websocket, the browser's frame reads and the D-375 map-proposal from one asyncio event loop. The map registration (1.2-11 s of Python/OpenCV work) ran through `asyncio.to_thread`. The GIL-holding parts of that work starved the loop, so the live video stalled, and a reconnect's hello timed out. Rosy Cam read the resulting close as a version mismatch and stopped the camera until someone restarted it.

## Symptoms
- Found live on a real Galaxy S21 over pinned `wss` on 2026-10-01. A repro script polled `/frame` while calling `map-proposal` three times. It showed frame reads of 10-15 s, frame numbers restarting (the phone reconnected), 404 "frame unavailable" in between, and `map-proposal` answering in 7-11 s.
- Once, the reconnect's hello wait (`HELLO_TIMEOUT_S = 5.0`) expired while the loop was blocked. Vision closed with 4400 "no hello", and the app treated 4400 as fatal.
- A secondary effect: the phone's adaptive JPEG quality dropped under the stall, so the map fit on that frame fell just under the 0.8 gate.

## What Didn't Work
- `asyncio.to_thread` alone. It keeps the loop free only while the worker thread releases the GIL (NumPy/OpenCV inner calls). The registration's Python loops (candidate search, scoring) hold the GIL long enough to delay every coroutine, including the websocket handshake.
- Treating every 4400 as fatal in the app. A server-side timeout is not an incompatibility.

## Solution
Landed on local main (not yet pushed) as merge commits 60238c0c (Vision) and c2b41ac5 (Rosy Cam) — cite the branches `feat/overhead-map-auto-register` and `feat/overhead-app-site-ca-pin` if those SHAs are rewritten, per D-341 §11:
- Registration runs in one long-lived **spawned worker process** (`src/site/vision/rosy_vision/map_worker.py`: `ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))`). It is single-flight per source, and that one worker is the global CPU limit. The ingest path never waits on it.
- The hello timer counts only time the loop was actually responsive (`_receive_hello` in `ingest.py`). A real timeout closes with **1013** (`protocol.CLOSE_HELLO_TIMEOUT`, "try again later"). 4400 stays only for a genuinely bad hello.
- Rosy Cam retries 1013 and 4503. During the transition it also retries a 4400 whose reason is empty or "no hello" (sent by pre-1013 receivers). Every other 4400 stays fatal. `test/fixtures/protocol/overhead-ingest.v1.json` `close_codes` is the one source both sides test against.
- Regression test: `test_registration_in_flight_does_not_delay_the_ingest_loop` (`src/site/vision/test/test_map_proposal_route.py`) runs a 3 s CPU-bound fake registration and requires a new phone's hello and a frame read to each finish within 0.5 s. It fails when the job runs on a thread.

## Why This Works
A separate process has its own interpreter and GIL, so no amount of Python work in the registrar can delay the ingest loop's coroutines. The retryable close code turns any remaining server-side slowness into a reconnect instead of a permanent stop. The responsive-time hello timer removes the false "no hello" that a blocked loop used to produce.

## Prevention
- In an asyncio server that also carries real-time sockets, never run CPU-heavy Python on `to_thread`. Use a bounded process pool, and add a test that a CPU-bound job in flight does not delay a handshake.
- Server-side waits (busy, timeout) must use a **retryable** close code. Reserve the fatal code for real incompatibility, and pin the table in the shared protocol fixture before either side changes.
- Re-check any "rejected fit" or quality number measured during a connection incident. The input may have been degraded by the incident itself.

## Related Issues
- ADR D-375 (map registration from the lane paint is a proposal), D-341 §11 (close-code table), D-360 (field proposal).
- (auto memory [claude]) The overhead-camera-app memory records the 2026-10-01 live bench (rosy-cam stack, pinned S21) where this was found.
