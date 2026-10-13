"""Keep the shared proof bytes equal without joining CORE/Fleet dependencies."""

from pathlib import Path


def test_core_and_fleet_peer_proof_copies_are_equal():
    root = Path(__file__).resolve().parents[2]
    core = root / 'middleware/core/api/core_api_web/api/peer_pairing/peer_crypto.py'
    fleet = root / 'operations/fleet/fleet/server/peer/camera_peer_crypto.py'
    assert core.read_bytes() == fleet.read_bytes(), 'Update both independently shipped proof helpers together'
