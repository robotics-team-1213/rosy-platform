"""release_timing links the release chain from existing records and fails --assert-complete on broken links."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_timing", ROOT / "tools/release_timing.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

A, B = "a" * 40, "b" * 40
T0 = 1_000_000.0


def iso(s):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(T0 + s, timezone.utc).isoformat().replace("+00:00", "Z")


def jl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def fixture(tmp, **over):
    pr = [{"pr": 1, "head_sha": "1" * 40, "queue_sha": A, "main_sha": A, "head_at": iso(0), "queue_at": iso(600), "main_at": iso(1200)}]
    art = [{"source_commit": A, "manifest_sha256": "d1", "created_at": iso(1500)}]
    sign = [{"decision": "signed", "source_commit": A, "manifest_sha256": "d1", "time": iso(2100)}, {"decision": "refused", "tag": "x"}]
    rstate = {"installed": {"commit": A, "time": iso(3000)}, "failed": {}}
    cell = {"history": [{"release": A[:12], "result": "active", "at": T0 + 3300}]}
    rcd = [{"at": iso(2200), "result": "building", "sha": A, "release_id": "2026.11.20-001"}]
    rollout = tmp / "ev" / "2026-11-20"
    rollout.mkdir(parents=True)
    jl(rollout / "rollout.jsonl", [{"at": iso(4000), "event": "canary-ok", "release_id": "2026.11.20-001"}])
    acc = [{"target": "R", "sha": A, "at": iso(3600)}, {"target": "pinky", "sha": A, "at": iso(4300)},
           {"target": "cell:A", "sha": A, "at": iso(3900)}]
    data = {"pr": pr, "art": art, "sign": sign, "acc": acc, "rcd": rcd}
    data.update(over)
    (tmp / "r.json").write_text(json.dumps(over.get("rstate", rstate)))
    (tmp / "c.json").write_text(json.dumps(cell))
    return ["--pr-events", jl(tmp / "pr", data["pr"]), "--artifacts", jl(tmp / "art", data["art"]),
            "--sign-audit", jl(tmp / "sign", data["sign"]), "--r-state", str(tmp / "r.json"),
            "--cell-state", f"A={tmp / 'c.json'}", "--robot-cd-audit", jl(tmp / "rcd", data["rcd"]),
            "--rollout-evidence", str(tmp / "ev"), "--acceptance", jl(tmp / "acc", data["acc"]), "--json"]


def run(args, capsys):
    code = rt.main(args)
    return code, json.loads(capsys.readouterr().out)


def test_complete_chain_has_stage_latencies(tmp_path, capsys):
    code, out = run(fixture(tmp_path) + ["--assert-complete"], capsys)
    assert code == 0 and out["problems"] == []
    assert out["releases"][0]["targets"] == {"R": "accepted", "cell:A": "accepted", "pinky": "accepted"}
    assert out["stages"]["head->queue"]["p50"] == 600
    assert out["stages"]["queue->main"]["p90"] == 600
    assert out["stages"]["artifact->signed"]["p50"] == 600
    assert out["stages"]["signed->install"]["n"] == 3


def test_unconfirmed_acceptance_is_distinct_and_not_a_failure(tmp_path, capsys):
    code, out = run(fixture(tmp_path, acc=[]) + ["--assert-complete"], capsys)
    assert code == 0
    assert set(out["releases"][0]["targets"].values()) == {"unconfirmed-acceptance"}


def test_missing_install_record_fails(tmp_path, capsys):
    code, out = run(fixture(tmp_path, rstate={"failed": {}}) + ["--assert-complete"], capsys)
    assert code == 1 and any("R: no install" in m for m in out["missing"])


def test_missing_signing_and_unlinked_artifact(tmp_path, capsys):
    code, out = run(fixture(tmp_path, sign=[], art=[{"source_commit": B, "manifest_sha256": "x", "created_at": iso(1)}])
                    + ["--assert-complete"], capsys)
    assert code == 1
    assert any("no signing audit" in m for m in out["missing"]) and any("without a PR" in m for m in out["missing"])


def test_duplicate_and_sha_mismatch_fail(tmp_path, capsys):
    pr = [{"pr": 1, "queue_sha": B, "main_sha": A, "head_at": iso(0), "queue_at": iso(1), "main_at": iso(2)}] * 2
    sign = [{"decision": "signed", "source_commit": A, "manifest_sha256": "other", "time": iso(2100)}] * 2
    code, out = run(fixture(tmp_path, pr=pr, sign=sign) + ["--assert-complete"], capsys)
    assert code == 1
    assert out["duplicate"] and any("queue sha" in m for m in out["mismatch"])
    assert any("digest differs" in m for m in out["mismatch"])


def test_held_busy_and_rollback_are_told_apart(tmp_path, capsys):
    (tmp_path / "x").mkdir()
    args = fixture(tmp_path, rstate={"failed": {"site-" + A[:12]: {"time": iso(3000), "reason": "health"}}})
    cj = jl(tmp_path / "cj", [{"step": "deferred", "release": A[:12], "reason": "session_running", "t": T0 + 3000}])
    (tmp_path / "c.json").write_text(json.dumps({"history": []}))
    args[args.index("--rollout-evidence")] = "--cell-journal"
    args[args.index("--cell-journal") + 1] = f"A={cj}"
    args += ["--rollout-evidence", str(tmp_path / "none")]
    rcd = jl(tmp_path / "rcd", [{"at": iso(2200), "result": "delivery_held", "sha": A, "release_id": "r"}])
    args[args.index("--robot-cd-audit") + 1] = rcd
    code, out = run(args, capsys)
    assert code == 0
    assert out["releases"][0]["targets"] == {"R": "rollback", "cell:A": "busy", "pinky": "held"}


def test_window_filters_by_main_time(tmp_path, capsys):
    _, out = run(fixture(tmp_path) + ["--since", iso(5000)], capsys)
    assert out["releases"] == []
