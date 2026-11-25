from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from cell_recovery_placement_journal import PlacementJournal


def test_claim_survives_restart_and_blocks_new_incident_until_verified(tmp_path):
    first = PlacementJournal(tmp_path, "arm_s")
    assert not first.pending()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: first.begin("usb-one", "board"), range(4)))
    assert claims.count(True) == 1
    second = PlacementJournal(tmp_path, "arm_s")
    assert second.pending()
    assert not second.begin("usb-two", "floor")
    assert not second.verified("usb-one", "floor")
    assert not second.verified("usb-two", "board")
    assert PlacementJournal(tmp_path, "arm_b").begin("usb-other", "floor")
    assert second.verified("usb-one", "board")
    assert first.confirmed("usb-one")
    assert not first.confirmed("usb-two")
    assert not first.pending()
    assert not first.begin("usb-one", "floor")
    assert first.begin("usb-two", "floor")
