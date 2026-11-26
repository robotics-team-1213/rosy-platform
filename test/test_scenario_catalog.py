"""scenario_catalog contract: the catalog matches the canonical id list and the real tool surfaces."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "sim"))
import scenario_catalog  # noqa: E402

EXPECTED_IDS = {"AT-01", "AT-02", "AT-03", "AT-04", "AT-05", "AT-06", "AT-07",
                "X-SLOT", "X-3TIER", "X-FALLBACK", "X-PINKY"}


def test_check_passes():
    assert scenario_catalog.check() == []


def test_id_set_is_exactly_the_canonical_list():
    assert {s["id"] for s in scenario_catalog.SCENARIOS} == EXPECTED_IDS


def test_teacher_tasks_are_in_argparse_choices():
    # 텍스트로 읽는다(MuJoCo import 금지); 파싱이 빈 집합이면 시험 자체가 실패해야 한다.
    tasks = scenario_catalog.teacher_tasks()
    assert tasks, "omx_two_arm_teacher.py argparse choices 파싱 실패"
    for s in scenario_catalog.SCENARIOS:
        if s["sim"] and s["sim"][0] == scenario_catalog.TEACHER:
            assert s["sim"][2] in tasks


def test_dry_run_tools_are_in_bridge_tool_specs():
    tools = scenario_catalog.bridge_tools()
    assert tools, "rosy_agent_bridge.py TOOL_SPECS 파싱 실패"
    for s in scenario_catalog.SCENARIOS:
        assert set(s["dry_run"]) <= tools


def test_mujoco_rows_name_the_cell_snapshot():
    for s in scenario_catalog.SCENARIOS:
        if s["sim_host"] == "ai":
            assert "cell_snapshot=deploy/robot/omx/sim/cell_snapshots/20261110-1231.json" in s["sim"], s["id"]
