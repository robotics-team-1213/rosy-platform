"""SIM robots publish battery/voltage like the Pinky battery node, so Fleet's trip start sees fresh evidence."""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
for holder in ("contracts/foundation", "middleware/core/services"):  # this file also runs alone
    if str(REPO / holder) not in sys.path:
        sys.path.insert(0, str(REPO / holder))


def _sim_battery():
    spec = importlib.util.spec_from_file_location("sim_battery", ROOT / "scripts" / "sim_battery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_sim_pack_voltage_reads_as_a_healthy_non_charging_battery():
    from core_features.power.battery import BatteryConfig, BatteryMonitor
    mod = _sim_battery()
    clock = [100.0]
    monitor = BatteryMonitor(BatteryConfig(), clock=lambda: clock[0])
    for _ in range(4):
        monitor.on_voltage(mod.SIM_PACK_V)
        clock[0] += 1.0
    health = monitor.health()
    assert health["evidence"] == "fresh" and health["level"] == "ok" and health["percent"] < 100.0
    assert mod.SIM_PACK_V < 8.40      # a charger clamps at 100 %: the sim pack is not on a charger
    assert health["charging_state"] == "unconfirmed"


def test_every_launch_that_starts_a_sim_core_starts_the_battery_node_and_cmake_installs_it():
    assert "scripts/sim_battery.py" in (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    for name in ("gz_multi.launch.py", "map_v2_fleet_lane.launch.py", "map_v2_fleet_real.launch.py"):
        text = (ROOT / "launch" / name).read_text(encoding="utf-8")
        assert text.count('executable="core"') == 1, name
        assert re.search(r'executable=.sim_battery\.py.', text), name
