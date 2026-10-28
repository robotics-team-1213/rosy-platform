"""The watchdog can terminate only its own media child processes."""

import importlib
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def test_missing_authority_health_stops_only_owned_media_processes():
    assert (ROOT / 'src/rosy_media/supervisor.py').is_file(), 'D-789 independent media supervisor missing'
    module = importlib.import_module('rosy_media.supervisor')
    healthy = [True]
    command = [sys.executable, '-c', 'import time;time.sleep(30)']
    unrelated = subprocess.Popen(command)
    supervisor = module.MediaSupervisor([command, command], health_check=lambda: healthy[0])
    try:
        supervisor.start(now=100)
        assert supervisor.tick(now=100)
        children = list(supervisor.children)
        healthy[0] = False
        assert supervisor.tick(now=102)
        assert supervisor.tick(now=103) is False
        assert all(child.poll() is not None for child in children)
        assert unrelated.poll() is None
    finally:
        supervisor.stop()
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_authority_child_exit_stops_backend_immediately():
    assert (ROOT / 'src/rosy_media/supervisor.py').is_file(), 'D-789 independent media supervisor missing'
    module = importlib.import_module('rosy_media.supervisor')
    command = [sys.executable, '-c', 'import time;time.sleep(30)']
    supervisor = module.MediaSupervisor([command, command], health_check=lambda: True)
    try:
        supervisor.start(now=100)
        supervisor.children[0].terminate()
        supervisor.children[0].wait(timeout=3)
        assert supervisor.tick(now=100.1) is False
        assert all(child.poll() is not None for child in supervisor.children)
    finally:
        supervisor.stop()


def test_supervisor_uses_actual_tick_timestamp_not_successful_http_response_time():
    assert (ROOT / 'src/rosy_media/supervisor.py').is_file()
    module = importlib.import_module('rosy_media.supervisor')
    command = [sys.executable, '-c', 'import time;time.sleep(30)']
    heartbeat = [100.0]
    supervisor = module.MediaSupervisor([command, command], health_check=lambda: heartbeat[0])
    try:
        supervisor.start(now=100)
        assert supervisor.tick(now=100)
        heartbeat[0] = 102.0
        assert supervisor.tick(now=102)
        assert supervisor.tick(now=104)
        assert supervisor.tick(now=105) is False
    finally:
        supervisor.stop()
