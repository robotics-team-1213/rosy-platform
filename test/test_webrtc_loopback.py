"""D-789 real GStreamer -> WHIP -> MediaMTX -> Chromium WHEP test.

Opt in on a prepared test PC with ROSY_RUN_MEDIA_TESTS=1. This is synthetic
SOURCE integration; native ARM64, real cameras, Android and FIELD stay separate.
"""

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('ROSY_RUN_MEDIA_TESTS') != '1',
                    reason='requires isolated media runtime on remote test PC')
def test_real_whip_whep_browser_receives_capture_watermark(tmp_path):
    sender = ROOT / 'middleware/media/src/rosy_media_edge/pipeline.py'
    assert sender.is_file(), 'D-789 real H.264 WHIP sender is missing'
    helper = ROOT / 'test/webrtc_loopback_harness.py'
    assert helper.is_file(), 'D-789 needs actual browser render evidence'
    import runpy
    runpy.run_path(str(helper))['run_loopback'](ROOT, tmp_path)


@pytest.mark.skipif(os.environ.get('ROSY_RUN_MEDIA_TESTS') != '1',
                    reason='requires isolated media runtime on remote test PC')
def test_core_revocation_terminates_actual_mediamtx_and_browser_video(tmp_path):
    import runpy
    module = runpy.run_path(str(ROOT / 'test/webrtc_loopback_harness.py'))
    assert 'run_secure_loopback' in module, 'D-789 needs real session termination evidence'
    module['run_secure_loopback'](ROOT, tmp_path)


@pytest.mark.skipif(os.environ.get('ROSY_RUN_MEDIA_TESTS') != '1',
                    reason='requires isolated media runtime on remote test PC')
def test_shared_client_starts_hidden_video_and_releases_real_session(tmp_path):
    import runpy
    module = runpy.run_path(str(ROOT / 'test/webrtc_loopback_harness.py'))
    module['run_loopback'](ROOT, tmp_path, shared_client=True)
