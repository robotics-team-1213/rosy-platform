#!/usr/bin/env python3
"""Read-only D-789 media preflight. A plugin inventory is not field acceptance."""

import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess


PLUGINS = ('webrtcbin', 'x264enc', 'nicesrc', 'rtph264pay', 'appsrc',
           'videoconvert', 'h264parse', 'appsink', 'avdec_h264')


def probe():
    machine = platform.machine()
    core_version = ()
    try:
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        core_version = tuple(Gst.version())
    except (ImportError, ValueError):
        pass
    inspect = shutil.which('gst-inspect-1.0')
    missing, versions = [], {}
    for plugin in PLUGINS:
        try:
            result = subprocess.run([inspect, plugin], capture_output=True, text=True,
                                    timeout=3) if inspect else None
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is None or result.returncode:
            missing.append(plugin)
            continue
        version = next((line.split(None, 1)[1].strip()
                        for line in result.stdout.splitlines()
                        if line.strip().startswith('Version ')), '')
        versions[plugin] = version
    checks = {
        'native_arm64': {'ok': platform.system() == 'Linux' and machine == 'aarch64'},
        'plugins': {'ok': not missing, 'missing': missing, 'versions': versions},
        'gstreamer_series': {'ok': core_version[:2] == (1, 24),
                             'version': '.'.join(map(str, core_version[:3]))},
        'end_to_end': {'ok': False, 'reason': 'not run; WHIP/WHEP render evidence required'},
    }
    return {
        'schema': 'rosy-media-runtime/1',
        'platform': {'system': platform.system(), 'machine': machine},
        'checks': checks,
        'preflight_ready': all(checks[name]['ok'] for name in (
            'native_arm64', 'plugins', 'gstreamer_series')),
        'accepted': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, sort_keys=True))
    return 0 if report['preflight_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
