# Native media verification

Run committed media tests through the remote runner. The real codec tests require a prepared Ubuntu 24.04 test PC; ordinary Python tests do not install or load GStreamer.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_RUN_MEDIA_TESTS=1 ROSY_RUN_BROWSER_TESTS=1 test/test_webrtc_loopback.py
python test/known_failures.py <external-log-dir>/run-1.txt
```

Select the prepared host through the existing `ROSY_TEST_HOSTS` configuration. A missing runtime is a setup failure, not a skipped or passed codec test.

## Prepared host

The harness reads `~/rosy-test/media-runtime-d789/`:

- `amd64/mediamtx`: the executable amd64 archive member, verified against `deploy/site/media-sources.lock.json`.
- `environment.json`: string environment values for the native sender. Include `PYTHONPATH`, even if empty. An isolated package extraction also needs `LD_LIBRARY_PATH`, `GI_TYPELIB_PATH`, `GST_PLUGIN_PATH`, and a runtime-owned `GST_REGISTRY`.
- A preparation receipt should retain the archive and extracted Debian package SHA-256 values. Use authenticated distro package downloads; leave the host's global packages and services unchanged when preparing an isolated runtime.

The system Python must load GI, Gst 1.24 and GstWebRTC. `webrtcbin` registration alone is insufficient: DTLS/SRTP factories must also load. The required inventory is in the media source lock and native `probe-media-runtime.py`. An isolated Ubuntu dependency extraction used the following packages in the verified run:

```text
gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-nice
libgstreamer-plugins-bad1.0-0 libnice10 libx264-164 gir1.2-gst-plugins-bad-1.0
libgupnp-igd-1.6-0 libgupnp-1.6-0 libgssdp-1.6-0 libsrtp2-1
```

This list supplements an existing Gst 1.24/GI host; it is not an ARM64 image dependency lock. After changing extracted dependencies, use a fresh runtime-owned GStreamer registry so a previously blacklisted plugin is inspected again.

## What the tests prove

The three real codec cases verify H.264 → WHIP → MediaMTX → Chromium watermark rendering, actual authority revocation, and hidden-video playback through production `shared/web/webrtc.js`. The shared-client case also verifies native session removal, peer closure, stream detachment and the revocation callback.

The shared-client case routes HTTPS signaling and intent/renew responses inside Playwright. It does not prove a real TLS gateway or live CORE grant flow. The separate revocation case uses the actual test authority. All three use synthetic frames on x86_64; native ARM64, the real camera, control traffic under load, Android and field acceptance remain separate gates.
