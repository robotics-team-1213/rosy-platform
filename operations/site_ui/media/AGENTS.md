# ROSY media

Parent: [site_ui/AGENTS.md](../AGENTS.md). D-789 adds a standalone media service here; it is not installed or served by Fleet.

This wheel owns WebRTC session authorization, viewer demand and media-process supervision. `src/rosy_media/authority.py` validates short media grants and rechecks the originating CORE. `server.py` adapts those decisions to MediaMTX callbacks and viewer requests. `supervisor.py` controls only the two media processes it creates. Camera capture and encoding remain in robot perception.

Harness records: [progress.md](progress.md), append-only [logs.md](logs.md), generated [index.md](index.md). After a change append logs, update progress only for evidence-backed gate changes, and run `python tools/harness/rosy_harness.py generate`.

Do not import Fleet, ROS, device actions or command publishers. Use `core_common` for media signatures. Do not accept CORE long-term credentials, URL tokens, arbitrary upstream URLs or arbitrary process identifiers from HTTP requests. Local MediaMTX management credentials are separate from source/read grants.

Run committed revisions through `tools/remote/remote_pytest.py -- <operations/site_ui/media/test paths>` and compare each returned log with `test/known_failures.py`. Actual H.264/WHIP/WHEP browser tests are in `test/test_webrtc_loopback.py` and require the prepared remote media runtime with `ROSY_RUN_MEDIA_TESTS=1 ROSY_RUN_BROWSER_TESTS=1`. Synthetic loopback does not establish native ARM64, Android, camera or six-robot acceptance.

Deployment remains disabled until the D-789 plan gates are met. Tests of a policy class do not prove that the installed MediaMTX session was terminated. Preserve the distinction in progress and validation records.
