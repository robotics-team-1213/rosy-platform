"""Tests for the 7-fault D-1088 regression suite (tools/sim/coupled_sim_fault_suite.py)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = str(ROOT / "tools/sim")
if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)

import coupled_sim_controller as csc  # noqa: E402
import coupled_sim_fault_suite as suite  # noqa: E402


def test_run_all_fault_scenarios_covers_all_seven_faults() -> None:
    receipt = suite.run_all_fault_scenarios(site_map_sha256="ab" * 32)
    assert receipt["schema"] == "rosy.sim.fault-suite-receipt.v1"
    assert receipt["all_passed"] is True
    assert receipt["fault_count"] == 7
    fault_ids = [item["fault_id"] for item in receipt["scenarios"]]
    assert set(fault_ids) == set(csc.ALLOWED_FAULTS)
    assert all(item["passed"] is True for item in receipt["scenarios"])


def test_fault_suite_cli_writes_receipt_json(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "fault-suite-receipt.json"
    rc = suite.main(["--site-map-sha256", "cd" * 32, "--out", str(out_path)])
    assert rc == 0
    assert out_path.is_file()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    printed = json.loads(capsys.readouterr().out)
    assert written == printed
    assert written["all_passed"] is True
    assert written["fault_count"] == 7
