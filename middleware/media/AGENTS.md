# Robot media publisher

Parent: [middleware/AGENTS.md](../AGENTS.md). D-789/D-791 define this optional native media process. The `rosy-media-edge` wheel owns H.264, WHIP and capture identity transport; it never opens a second camera or imports CORE/ROS command code. The existing perception camera remains the sole capture owner.

Read [progress.md](progress.md), append to [logs.md](logs.md), and regenerate [index.md](index.md) through `python tools/harness/rosy_harness.py generate`. Keep native GStreamer imports lazy; ordinary CORE/perception startup must work without the optional media stack.

Run committed `middleware/media/test` through `tools/remote/remote_pytest.py`, compare each log with `test/known_failures.py`, and run `test/test_webrtc_loopback.py` only on the prepared remote media host with `ROSY_RUN_MEDIA_TESTS=1 ROSY_RUN_BROWSER_TESTS=1`. Synthetic x86_64 WebRTC does not prove native ARM64, a camera, Android, or six-robot field acceptance.
