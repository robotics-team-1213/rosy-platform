"""The device Python runtime id is the sha256 of the whole requirements file (D-189).

A payload release carries that id and a robot refuses one whose id differs from
its image's. Any byte change, a comment included, therefore cuts every flashed
robot off from payload updates until it is re-flashed: e3b0c95e rewrote two
comment paths and 2026.09.30 payloads could not go to robots on 2026.09.27 images.

Change the file only together with a new image, and then update both pins here.
D-373 decision 1 is such a change: it appends the learned-perception block, so
the next image carries IMAGE_RUNTIME_ID, and the lock lists the flashed id as a
compatible predecessor (the file without the block) so payloads built for the
older cards still activate once the bench install or re-flash lands.
"""

import hashlib
from pathlib import Path

import yaml

IMAGE = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "pinky_pro" / "image"
REQUIREMENTS = IMAGE / "device-python-requirements.txt"
#: The runtime flashed images since D-192 carry.
FLASHED_RUNTIME_ID = "a66f224ab570cb08d1c474bdbb1f93899692625cd167a7f6f907fc99690f4176"
#: The runtime the next image carries (D-373 learned-perception block appended).
IMAGE_RUNTIME_ID = "6f3353ea301de18f87843d1f729158fe342ee1b4bbd0365892093f2a23949876"
BEGIN = b"# BEGIN D-373 learned-perception runtime"


def _lock():
    return yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))


def test_requirements_bytes_keep_the_pinned_image_runtime_id():
    assert hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest() == IMAGE_RUNTIME_ID


def test_requirements_without_the_d373_block_are_the_flashed_runtime():
    data = REQUIREMENTS.read_bytes()
    before = data[:data.index(BEGIN)].removesuffix(b"\n")
    assert hashlib.sha256(before).hexdigest() == FLASHED_RUNTIME_ID


def test_lock_pins_the_same_runtime_id():
    assert _lock()["python_runtime"]["requirements_sha256"] == IMAGE_RUNTIME_ID


def test_lock_keeps_the_flashed_runtime_as_the_compatible_predecessor():
    assert _lock()["python_runtime"]["compatible_predecessors"] == [FLASHED_RUNTIME_ID]
