"""D-789 optional media artifacts and executable runtime preflight."""

import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'deploy/robot/pinky_pro/image/probe-media-runtime.py'
LOCK = ROOT / 'deploy/site/media-sources.lock.json'


def test_media_runtime_preflight_exists():
    assert PROBE.is_file(), 'D-789 needs an executable native media preflight'


def test_media_runtime_preflight_reports_missing_tools_without_claiming_acceptance(tmp_path):
    assert PROBE.is_file(), 'D-789 needs an executable native media preflight'
    out = tmp_path / 'report.json'
    result = subprocess.run(
        [sys.executable, str(PROBE), '--output', str(out)],
        env={'PATH': str(tmp_path)}, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 1
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['accepted'] is False
    assert report['schema'] == 'rosy-media-runtime/1'
    assert report['checks']['plugins']['ok'] is False
    assert set(report['checks']['plugins']['missing']) >= {'webrtcbin', 'x264enc', 'nicesrc'}
    assert report['checks']['native_arm64']['ok'] in (True, False)
    assert 'native_arm64' in report['checks']
    assert report['checks']['end_to_end']['ok'] is False
    assert 'not run' in report['checks']['end_to_end']['reason']


def test_media_runtime_preflight_reports_actual_host(tmp_path):
    assert PROBE.is_file(), 'D-789 needs an executable native media preflight'
    out = tmp_path / 'host.json'
    result = subprocess.run([sys.executable, str(PROBE), '--output', str(out)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode in (0, 1)
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['platform']['machine']
    assert report['accepted'] is False  # preflight alone is never end-to-end evidence
    print(json.dumps(report, sort_keys=True))


def test_media_artifact_is_locked_and_carries_provenance():
    assert LOCK.is_file(), 'D-789 needs verified media binary provenance'
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    media = lock['mediamtx']
    assert media['version'].startswith('v')
    assert len(media['sha256']) == 64
    assert set(media['sha256']) <= set('0123456789abcdef')
    assert media['url'].startswith('https://github.com/bluenviron/mediamtx/releases/download/')
    assert 'linux_arm64' in media['url']
    assert media['license'] == 'MIT'
    assert lock['gstreamer']['required_series'] == '1.24'
    assert lock['acceptance']['native_arm64'] == 'unverified'
    assert lock['acceptance']['end_to_end'] == 'unverified'


def test_media_site_config_refuses_anonymous_publish_and_read():
    config = ROOT / 'deploy/site/mediamtx.yaml'
    assert config.is_file(), 'D-789 needs isolated media server configuration'
    media = yaml.safe_load(config.read_text(encoding='utf-8'))
    assert media['authMethod'] == 'http'
    assert media['authHTTPAddress'].startswith('http://127.0.0.1:')
    assert media['authHTTPExclude'] == []
    assert media['apiAddress'].startswith('127.0.0.1:')
    assert media['webrtcAddress'].startswith('127.0.0.1:')
    assert media['rtsp'] is False
    assert media['rtmp'] is False
    assert media['hls'] is False
    assert media['srt'] is False
    assert media['pathDefaults']['record'] is False
    assert media['pathDefaults']['overridePublisher'] is False


SITE = ROOT / 'deploy/site'
NATIVE = ROOT / 'deploy/robot/pinky_pro/native'


def test_site_media_image_downloads_exactly_the_locked_mediamtx():
    lock = json.loads(LOCK.read_text(encoding='utf-8'))['mediamtx']
    dockerfile = (SITE / 'Dockerfile.media').read_text(encoding='utf-8')
    assert f"ARG MEDIAMTX_VERSION={lock['version']}" in dockerfile
    assert f"ARG MEDIAMTX_SHA256={lock['amd64']['sha256']}" in dockerfile
    assert 'sha256sum -c -' in dockerfile
    # An unverifiable digest is a recorded shortcut, never silently a floating tag.
    assert 'FROM ubuntu:24.04' in dockerfile and 'shortcut:' in dockerfile
    fleet = set((SITE / 'requirements-fleet.txt').read_text(encoding='utf-8').split())
    media = (SITE / 'requirements-media.txt').read_text(encoding='utf-8').split()
    assert media and all('==' in line and line in fleet for line in media)


def test_site_media_is_its_own_compose_project_without_fleet():
    compose = yaml.safe_load((SITE / 'compose.media.yaml').read_text(encoding='utf-8'))
    assert set(compose['services']) == {'media', 'media-gateway'}
    media, gateway = compose['services']['media'], compose['services']['media-gateway']
    assert media['build']['dockerfile'] == 'deploy/site/Dockerfile.media'
    assert gateway['network_mode'] == 'service:media'
    for service in (media, gateway):
        assert service['read_only'] is True and service['cap_drop'] == ['ALL']
        assert service['user'] == '10001:10001'
    assert all('fleet' not in str(value) for value in media.values())
    assert './Caddyfile.media:/etc/caddy/Caddyfile:ro' in gateway['volumes']


def test_site_media_gateway_never_exposes_callbacks_or_management():
    caddy = '\n'.join(line for line in (SITE / 'Caddyfile.media').read_text(encoding='utf-8').splitlines()
                     if not line.lstrip().startswith('#'))
    proxied = [line.split()[-1] for line in caddy.splitlines() if line.strip().startswith('reverse_proxy')]
    assert proxied == ['127.0.0.1:9121', '127.0.0.1:8889']
    assert '@authority path /v1/*' in caddy
    assert '9997' not in caddy and '/auth' not in caddy and '/health' not in caddy
    assert 'respond 404' in caddy


def _unit(path):
    directives = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            directives.setdefault(key, []).append(value)
    return directives


def test_robot_media_unit_is_a_bounded_separate_cgroup_without_devices():
    unit = _unit(NATIVE / 'rosy-media.service')
    assert unit['MemoryMax'] == ['256M'] and unit['CPUQuota'] == ['100%']
    assert unit['Restart'] == ['always'] and unit['RestartSec'] == ['2']
    assert unit['RestartMaxDelaySec'] == ['30'] and unit['StartLimitIntervalSec'] == ['0']
    assert unit['ConditionPathExists'] == ['/etc/rosy/media/rosy-media.json']
    assert unit['PrivateDevices'] == ['true'] and unit['DevicePolicy'] == ['closed']
    assert 'DeviceAllow' not in unit and 'PartOf' not in unit and 'SupplementaryGroups' not in unit
    assert 'rosy_media_edge.worker' in unit['ExecStart'][0]
    camera = _unit(NATIVE / 'rosy-camera.service')
    assert 'rosy-media.service' in camera['Wants'] and '/run/rosy-media' in camera['ReadWritePaths']
    build = (ROOT / 'deploy/robot/pinky_pro/image/build-native-payload.sh').read_text(encoding='utf-8')
    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-media.service" "$OVERLAY/etc/systemd/system/"' in build
    assert '"rosy-media.service"' in (NATIVE / 'sync-image-layer.py').read_text(encoding='utf-8')
    wheels = (ROOT / 'deploy/robot/pinky_pro/image/install-motion-contracts.sh').read_text(encoding='utf-8')
    assert 'rosy-media-edge==0.1.0' in wheels and 'middleware/media/src' in wheels
    rules = (NATIVE / 'tmpfiles-rosy-state.conf').read_text(encoding='utf-8')
    assert 'd /run/rosy-media 0750 rosy-camera rosy-camera -' in rules
