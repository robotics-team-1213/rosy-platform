---
module: media_edge
logical_modules: []
owner: ROBOT MEDIA
last_verified: {commit: "93d04a2b2e", date: 2026-10-29}
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py -- middleware/media/test"
    evidence: "93d04a2b2e: official remote media/shared WHEP/native probe contracts 83 passed. Negotiation primer, startup timeout, binding teardown, downshift-before-primer, continuous idle NIC sampling and playback cleanup regressions covered. 1c8923b441 affected selection: 4311 passed, 156 skipped; source/device limits in docs/validation/robot-local-video-recovery-2026-10-29/result.md."
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
    blocker: "Native ARM64 preflight and diagnostic 640x480 watermark rendering observed; final continuous-sampling patch deployment and production automatic playback remain unverified after device connectivity loss. See docs/validation/robot-local-video-recovery-2026-10-29/result.md."
  FIELD:
    state: HOLD
    blocker: "measurement skipped by user decision 2026-10-18; six physical robots have not run D-789 acceptance"
adrs: [D-789, D-791]
plans: [docs/plans/2026-10-17-webrtc-camera-migration.md]
---

This optional wheel holds the camera owner's media tap and the robot WHIP worker. It runs only where `/etc/rosy/media/rosy-media.json` exists (rosy-media.service, own cgroup); the camera keeps its perception size and cadence, so media follows the camera rate (8 fps default), below the 15 fps profile.
