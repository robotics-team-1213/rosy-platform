"""rosy CLI: free-position pick and push payloads, and a console that cannot print UTF-8."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_cli as cli  # noqa: E402
import rosy_agent_bridge as br  # noqa: E402

SHA = "ab" * 32


class Bridge:
    def __init__(self, res=None):
        self.calls, self.res = [], res or {"ok": True, "data": {"task": {"task_id": "t", "status": "PROPOSED"}}}

    def call_tool(self, name, args=None):
        self.calls.append((name, args))
        return self.res


def _args(argv):
    return cli.build_parser().parse_args(argv)


FREE_ARGV = ["pick", "--free-anchor", "belt", "--at-px", "320,240", "--dst", "yard:r1-s1-t1", "--frame-seq", "41", "--frame-sha256", SHA]


def test_pick_free_anchor_builds_one_typed_motion_and_no_metres():
    bridge = Bridge()
    res = cli.cmd_pick(bridge, _args([*FREE_ARGV, "--object", "box", "--dry-run"]))
    assert res["ok"] and res["tool"] == "fleet_dispatch_cell_task" and bridge.calls == []
    assert res["payload"] == {"cell_id": "cell_ab", "motion": {
        "kind": "free_pick", "anchor_site": "belt", "at_px": [320, 240], "dst_site": "yard:r1-s1-t1",
        "frame_seq": 41, "frame_sha256": SHA, "object": "box"}}
    assert br._validate_args(br.TOOL_MAP["fleet_dispatch_cell_task"], res["payload"]) is None


def test_pick_free_anchor_sends_the_dispatch_tool_and_propose_flag_keeps_the_propose_tool():
    bridge = Bridge()
    cli.cmd_pick(bridge, _args(FREE_ARGV))
    cli.cmd_pick(bridge, _args([*FREE_ARGV, "--propose"]))
    assert [c[0] for c in bridge.calls] == ["fleet_dispatch_cell_task", "fleet_propose_cell_task"]
    assert all(c[1]["motion"]["kind"] == "free_pick" and "src_site" not in c[1] for c in bridge.calls)


@pytest.mark.parametrize("extra", [["--at-px", "320"], ["--at-px", "a,b"], ["--src", "belt"], ["--preset", "x"], ["--tiers", "1,2"]])
def test_pick_free_anchor_refuses_bad_or_mixed_arguments(extra):
    argv = [a for a in FREE_ARGV]
    for i in range(0, len(extra), 2):
        key = extra[i]
        if key in argv:
            argv[argv.index(key) + 1] = extra[i + 1]
        else:
            argv += extra[i:i + 2]
    bridge = Bridge()
    res = cli.cmd_pick(bridge, _args(argv))
    assert res["error_code"] == "INVALID_ARGS" and bridge.calls == []


@pytest.mark.parametrize("drop", ["--dst", "--frame-seq", "--frame-sha256"])
def test_pick_free_anchor_needs_the_frame_and_the_destination(drop):
    argv = list(FREE_ARGV)
    i = argv.index(drop)
    del argv[i:i + 2]
    res = cli.cmd_pick(Bridge(), _args(argv))
    assert res["error_code"] == "INVALID_ARGS"


PUSH_ARGV = ["push", "--site", "belt", "--px", "300,200", "--dir", "1,0", "--mm", "10", "--frame-seq", "41", "--frame-sha256", SHA]


def test_push_is_always_the_propose_tool_and_needs_approval():
    bridge = Bridge()
    res = cli.cmd_push(bridge, _args([*PUSH_ARGV, "--arm", "arm_a"]))
    (name, payload), = bridge.calls
    assert name == "fleet_propose_cell_task" and res["needs_approval"] is True
    assert payload == {"cell_id": "cell_ab", "arm_id": "arm_a", "motion": {
        "kind": "push", "site": "belt", "px": [300, 200], "dir": [1.0, 0.0], "mm": 10.0, "frame_seq": 41, "frame_sha256": SHA}}
    assert br._validate_args(br.TOOL_MAP["fleet_propose_cell_task"], payload) is None


def test_push_dry_run_sends_nothing_and_a_failed_call_is_not_marked_approved():
    bridge = Bridge()
    assert cli.cmd_push(bridge, _args([*PUSH_ARGV, "--dry-run"]))["dry_run"] is True and bridge.calls == []
    bad = cli.cmd_push(Bridge({"ok": False, "status": 422}), _args(PUSH_ARGV))
    assert bad["ok"] is False and "needs_approval" not in bad
    assert cli.cmd_push(Bridge(), _args([a for a in PUSH_ARGV if a != "--frame-sha256" and a != SHA]))["error_code"] == "INVALID_ARGS"


def test_the_motion_property_is_in_both_cell_task_tools():
    for name in ("fleet_propose_cell_task", "fleet_dispatch_cell_task"):
        assert br.TOOL_MAP[name]["inputSchema"]["properties"]["motion"]["type"] == "object"


def test_main_prints_utf8_on_a_cp1252_console(monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", errors="strict"))
    monkeypatch.setattr(cli, "cmd_schema", lambda args: ({"label": "한글 야드"}, 0))
    assert cli.main(["schema"]) == 0
    sys.stdout.flush()
    assert json.loads(raw.getvalue().decode("utf-8")) == {"label": "한글 야드"}
