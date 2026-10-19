---
module: media
logical_modules: []
owner: SITE MEDIA
last_verified: {commit: "2190ba6889", date: 2026-10-18}
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py -- operations/site_ui/media/test"
    evidence: "25 passed at c94df2d713 (AI PC). rosy_media.main composes MediaAuthority with a fixed-origin HTTPS CORE validator and MediaMTXClient.kick; revocation, CORE loss and refused kicks reach the MediaMTX kick API (test_media_main)."
  LOCAL:
    state: GO
    cmd: "ROSY_TEST_HOSTS=ai@<ai-pc> python tools/remote/remote_pytest.py -- ROSY_RUN_MEDIA_TESTS=1 ROSY_RUN_BROWSER_TESTS=1 test/test_webrtc_loopback.py"
    evidence: "2190ba6889 on the AI PC: real GStreamer WHIP -> MediaMTX v1.21.2 -> Chromium WHEP render with watermark, and CORE revocation removed the actual MediaMTX sessions and stopped browser video. Synthetic x86_64 input; the composed authority's kick was exercised against a fake MediaMTX API, the policy class against real MediaMTX."
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; compose.media.yaml/Dockerfile.media exist but no site media image was built, digest-pinned or read back"
  DEVICE:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; no robot, Android device or production site installation"
  FIELD:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; six physical robots never ran the 30-minute bandwidth/latency/control scenario"
adrs: [D-789, D-801]
plans: [docs/plans/2026-10-17-webrtc-camera-migration.md]
---

The service is the default video path wherever a robot's CORE has `vision.media.site_url` (D-789 addendum 2026-10-18). Its authority is limited to media sessions; CORE retains command authority and Fleet does not relay video. Default-on is a user decision, not acceptance: no D-789 performance number has been measured.
