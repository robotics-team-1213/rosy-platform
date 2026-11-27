"""Observation pack: refusal codes, offline assembly from recorded cases, fetch through a fake cell, bridge tool, CLI."""
from __future__ import annotations

import base64
import copy
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_agent_bridge as br  # noqa: E402
import rosy_cli as cli  # noqa: E402
import rosy_observe as obs  # noqa: E402
import rosy_observe_refusals as ref  # noqa: E402

CASES = ROOT / "test" / "fixtures" / "llm_loop"


def case(name: str) -> dict[str, Any]:
    return json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))


def pack_of(name: str, **patch: Any) -> dict[str, Any]:
    raw = copy.deepcopy(case(name)["raw"])
    raw.update(patch)
    return obs.assemble(raw)


@pytest.mark.parametrize("why, code, sugg, nums", [
    ("neighbour clearance: 14.0 / 6.0 mm free beside it", "NEIGHBOUR_CLEARANCE", ["push", "ask_human"], {"free_mm": [14.0, 6.0], "min_free_mm": 6.0}),
    ("neighbour clearance on either closing axis", "NEIGHBOUR_CLEARANCE", ["push", "ask_human"], {}),
    ("edge of view: a side is past the camera's view, 5.0 / 40.0 mm free beside it", "EDGE_OF_VIEW", ["ask_human"], {"free_mm": [5.0, 40.0], "min_free_mm": 5.0}),
    ("no catalogue match", "NO_CATALOGUE_MATCH", ["push", "ask_human"], {}),
    ("tangled blob", "TANGLED_BLOB", ["push", "ask_human"], {}),
    ("wanted object container-2, got container-3", "WRONG_OBJECT", ["ask_human"], {"wanted": ["container-2"], "got": "container-3"}),
    ("tier mismatch: layers_below=1 on base site temp_plate_a plans at plate height; use source temp_plate_a-l1", "TIER_MISMATCH",
     ["retier(temp_plate_a-l1)"], {"layers_below": 1, "site": "temp_plate_a", "use": "temp_plate_a-l1"}),
    ("light top: mean 0.0 < 15.0: the room lights are off or the lens is covered - a person turns them on", "LIGHT_TOP", [], {"mean": 0.0, "min": 15.0}),
    ("held: top camera moved since map reference", "CAMERA_MOVED", [], {}),
    ("stopped: no usable object (neighbour clearance)", "NO_OBJECT", ["ask_human"], {}),
    ("ik_unreachable: pick (0.3,0.1,-0.05)", "UNREACHABLE", ["ask_human"], {}),
    ("something the cell never said before", "UNCLASSIFIED", ["ask_human"], {}),
])
def test_refusal_sentences_map_to_one_code(why, code, sugg, nums):
    out = ref.classify(why)
    assert (out["code"], out["suggestions"], out["numbers"]) == (code, sugg, nums)


def test_plate_b_is_untrusted_so_the_planned_workbench_is_ask_human_only():
    pack = pack_of("plate_b_workbench")
    planned = next(c for c in pack["candidates"] if c["status"] == "planned")
    assert planned["untrusted"] and planned["suggestions"] == ["ask_human"]
    assert all(c["suggestions"] == ["ask_human"] for c in pack["candidates"])


def test_belt_edge_box_and_temp_plate_gaps_carry_code_numbers_and_suggestions():
    edge = pack_of("belt_edge_box")["candidates"]
    assert [(c["code"], c["suggestions"], c["centre_mm"]) for c in edge] == [("NO_CATALOGUE_MATCH", ["push", "ask_human"], [191, 180])]
    gaps = [c for c in pack_of("temp_plate_gaps_b")["candidates"] if c["code"] == "NEIGHBOUR_CLEARANCE"]
    assert gaps and all(c["numbers"]["min_free_mm"] < 10 for c in gaps) and all("pick" not in c["suggestions"] for c in gaps)


def test_planned_belt_box_is_a_pick_with_the_cells_numbers_and_ids_are_stable():
    pack = pack_of("belt_middle_box")
    c = pack["candidates"][0]
    assert (c["id"], c["matched_id"], c["suggestions"], c["place_mm"]) == ("c1", "container-2", ["pick"], [153.0, -128.0])
    assert pack["observation_id"] == pack_of("belt_middle_box")["observation_id"]
    assert pack["observation_id"] != pack_of("belt_edge_box")["observation_id"]
    assert pack["readiness"]["ok"] and pack["readiness"]["peer"]["arm"] == "arm_a"


def test_tier_hint_run_becomes_a_retier_candidate():
    c = pack_of("tier_hint_base_site")["candidates"]
    assert [x["suggestions"] for x in c] == [["retier(temp_plate_a-l1)"]]


@pytest.mark.parametrize("name, reason", [("dark_top_frame", "DARK_FRAME:arm_s_top:0.0"), ("camera_moved", "CAMERA_MOVED")])
def test_dark_or_moved_camera_is_observable_false_with_nothing_else(name, reason):
    pack = pack_of(name)
    assert set(pack) == {"schema", "arm", "observable", "reason", "observed_at", "observation_id"}
    assert pack["observable"] is False and pack["reason"] == reason


def test_stale_and_missing_frames_refuse():
    raw = copy.deepcopy(case("belt_middle_box")["raw"])
    raw["frames"]["top"]["source_stamp"] -= 5
    assert obs.assemble(raw)["reason"].startswith("STALE_FRAME:top:")
    raw = copy.deepcopy(case("belt_middle_box")["raw"])
    raw["frames"]["side"] = {"ok": False, "error": "502", "fetched_at": raw["fetched_at"]}
    assert obs.assemble(raw)["reason"] == "CAMERA_MISSING:side"


def test_live_verbs_follow_the_probe_not_the_code():
    raw = copy.deepcopy(case("belt_middle_box")["raw"])
    assert obs.assemble(raw)["live_verbs"] == {"pick": True, "free_pick": True, "push": True, "idle": True, "ask_human": True}
    raw["probe"]["at_px"] = {"status": 400, "text": "\"unknown params ['at_px']\""}
    raw["probe"]["push"] = {"status": 404, "text": "null"}
    v = obs.assemble(raw)["live_verbs"]
    assert (v["free_pick"], v["push"]) == (False, False)
    raw = copy.deepcopy(case("belt_middle_box")["raw"])
    raw["readiness"] = {"error": "down"}
    assert obs.assemble(raw)["readiness"]["ok"] is False


def test_repeat_runs_that_disagree_are_unstable_and_ask_human_only():
    raw = copy.deepcopy(case("temp_plate_gaps_b")["raw"])
    run = raw["dry_runs"][0]["results"][0]
    other = copy.deepcopy(run)
    for r in other["structured_result"]["attempts"][0]["refused"]:
        r["centre_mm"][0] += 20  # the blob is not where the first run saw it
    run_two = {"site": "temp_plate_b", "results": [run, other]}
    raw["dry_runs"] = [run_two]
    unstable = [c for c in obs.assemble(raw)["candidates"] if c.get("unstable")]
    assert unstable and all(c["suggestions"] == ["ask_human"] for c in unstable)


def _jpeg(level: int) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (level, level, level)).save(buf, "JPEG")
    return buf.getvalue()


class FakeCell:
    """Answers the bridge's cell tools from a recorded case; counts calls so no moving job can sneak in."""

    def __init__(self, name: str, level: int = 120, stamp: float | None = None) -> None:
        self.raw, self.level, self.stamp, self.calls = case(name)["raw"], level, stamp, []

    def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(tool)
        if tool == "cell_frame":
            jpeg = _jpeg(self.level)
            return {"ok": True, "status": 200, "image_b64": base64.b64encode(jpeg).decode(), "sha256": "x",
                    "frame_headers": {"X-Frame-Seq": "7", "X-Source-Stamp": str(self.stamp or time.time())}}
        if tool == "cell_dry_run" and args["source"] != "probe":
            sr = next((e["results"][0]["structured_result"] for e in self.raw["dry_runs"] if e["site"] == args["source"]), None)
            return {"ok": True, "status": 200, "data": {"id": "j", "running": False, "structured_result": sr}} if sr else {"ok": False, "status": 400, "detail": {"error": "x"}}
        if tool == "cell_readiness":
            return {"ok": True, "status": 200, "data": self.raw["readiness"]}
        return {"ok": False, "status": 400, "detail": {"error": "config: no such file in the workdir"}}


def test_observe_through_a_fake_cell_is_read_only_and_annotates():
    cell = FakeCell("belt_middle_box", stamp=1000.0)
    pack, jpeg = obs.observe(cell, "arm_b", now=lambda: 1000.4)
    assert pack["observable"] and pack["candidates"][0]["suggestions"] == ["pick"] and pack["frames"]["top"]["age_s"] == 0.4
    assert set(cell.calls) <= {"cell_frame", "cell_dry_run", "cell_readiness", "cell_push_dry_run"}
    Image = pytest.importorskip("PIL.Image")
    assert Image.open(io.BytesIO(jpeg)).size == (640, 480)


def test_observe_dark_top_returns_only_the_reason():
    pack, jpeg = obs.observe(FakeCell("belt_middle_box", level=2, stamp=1000.0), "arm_b", now=lambda: 1000.4)
    assert pack["observable"] is False and pack["reason"].startswith("DARK_FRAME:top") and jpeg is None and "candidates" not in pack


def test_bridge_tool_cell_observe_validates_args_and_returns_image(monkeypatch):
    cell = FakeCell("belt_middle_box")
    bridge = br.RosyAgentBridge(br.BridgeConfig(cell_token="t", timeout_s=1.0))
    assert bridge.call_tool("cell_observe", {"arm": "arm_z"})["error_code"] == "INVALID_ARGS"
    assert bridge.call_tool("cell_observe", {"arm": "arm_b", "extra": 1})["error_code"] == "INVALID_ARGS"
    monkeypatch.setattr(bridge, "call_tool", lambda name, a=None, _orig=bridge.call_tool: cell(name, a or {}) if name != "cell_observe" else _orig(name, a))
    res = bridge.call_tool("cell_observe", {"arm": "arm_b"})
    assert res["ok"] and res["data"]["observable"] and res["mime_type"] == "image/jpeg" and base64.b64decode(res["image_b64"])[:2] == b"\xff\xd8"


class _StubBridge:
    def __init__(self, res: dict[str, Any]) -> None:
        self.res = res

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        assert name == "cell_observe"
        return dict(self.res)


def test_cli_observe_writes_pack_and_picture(tmp_path):
    pack = pack_of("belt_middle_box")
    ns = type("A", (), {"arm": "arm_b", "repeat": 1, "layers_below": None, "out_dir": str(tmp_path)})()
    out = cli.cmd_observe(_StubBridge({"ok": True, "data": pack, "image_b64": base64.b64encode(b"\xff\xd8jpg").decode()}), ns)
    assert out["observable"] and json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))["observation_id"] == pack["observation_id"]
    assert (tmp_path / "annotated_top.jpg").read_bytes() == b"\xff\xd8jpg"
