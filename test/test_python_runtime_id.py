"""The device Python runtime id is the sha256 of the whole requirements file (D-189).

A payload release carries that id and a robot refuses one whose id differs from
its image's. Any byte change, a comment included, therefore cuts every flashed
robot off from payload updates until it is re-flashed: e3b0c95e rewrote two
comment paths and 2026.09.30 payloads could not go to robots on 2026.09.27 images.

Change the file only together with a new image, and then update both pins here.
"""

import hashlib
from pathlib import Path

import yaml

IMAGE = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "pinky_pro" / "image"
REQUIREMENTS = IMAGE / "device-python-requirements.txt"
#: The runtime flashed images since D-192 carry.
FLASHED_RUNTIME_ID = "a66f224ab570cb08d1c474bdbb1f93899692625cd167a7f6f907fc99690f4176"  # sha256


def test_requirements_bytes_keep_the_flashed_runtime_id():
    assert hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest() == FLASHED_RUNTIME_ID


def test_lock_pins_the_same_runtime_id():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    assert lock["python_runtime"]["requirements_sha256"] == FLASHED_RUNTIME_ID
