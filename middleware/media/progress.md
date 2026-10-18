---
module: media_edge
logical_modules: []
owner: ROBOT MEDIA
last_verified: {commit: "2190ba6889", date: 2026-10-18}
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py -- middleware/media/test"
    evidence: "Passed at 327f750d8a (with test_module_structure and camera detection suites): camera tap (one request, lores for perception, native 640x480 main only, real mailbox round trip), WHIP worker demand/renewal/backoff, policy, feedback, watermark and WHIP clients."
  LOCAL:
    state: GO
    cmd: "ROSY_TEST_HOSTS=ai@<ai-pc> python tools/remote/remote_pytest.py -- ROSY_RUN_MEDIA_TESTS=1 ROSY_RUN_BROWSER_TESTS=1 test/test_webrtc_loopback.py"
    evidence: "2190ba6889 on the AI PC: MediaPublisher sends H.264 over WHIP to MediaMTX and Chromium renders the capture watermark; rate change reaches the encoder. Synthetic frames, not the Picamera2 tap."
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; the payload now installs rosy-media-edge and rosy-media.service but no signed ARM64 payload was built or its GStreamer closure probed"
  DEVICE:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; no Pinky ran the camera tap, rosy-media.service limits or a real camera stream"
  FIELD:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; six physical robots have not run D-789 acceptance"
adrs: [D-789, D-791]
plans: [docs/plans/2026-10-17-webrtc-camera-migration.md]
---

This optional wheel holds the camera owner's media tap and the robot WHIP worker. It runs only where `/etc/rosy/media/rosy-media.json` exists (rosy-media.service, own cgroup); the camera keeps its perception size and cadence, so media follows the camera rate (8 fps default), below the 15 fps profile.
