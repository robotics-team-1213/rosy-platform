import io
import json
import os
from pathlib import Path
import types
import urllib.error

import pytest

from test_omx_bench_record import _setup
import bench_record_handoff as brh
import record_seal


def _make_sealed_collection(home: Path, tmp_path: Path, name: str = "col-ab-01", *, episodes: int = 2, do_not_train: bool = False) -> Path:
    run = tmp_path / f"run-{name}"
    ds = tmp_path / f"ds-{name}"
    (ds / "meta").mkdir(parents=True)
    (ds / "data" / "chunk-000").mkdir(parents=True)
    (ds / "meta" / "info.json").write_text(json.dumps({
        "codebase_version": "v3.0", "robot_type": "bi_omx_follower", "total_episodes": episodes, "fps": 30,
    }), encoding="utf-8")
    (ds / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"PAR1")
    cal = tmp_path / f"{name}-cal.json"
    cal.write_text("{}", encoding="utf-8")
    run.mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"dataset": {"root": str(ds)}, "robot": {"type": "bi_omx_follower"}}), encoding="utf-8")
    (run / "session.json").write_text(json.dumps({
        "safe_end": True, "teleop_only": False, "exit_code": 0, "interrupted": False,
        "source_mode": "leader_native", "config": "config.json", "arm": "arm_ab",
    }), encoding="utf-8")
    cols = home / "rosy-test" / "omx-collections"
    res = record_seal.seal(run, name, cols, rig_revision="bench-v1", calibrations=[cal])
    col_dir = Path(res["collection"])
    if do_not_train:
        (col_dir / "DO_NOT_TRAIN.txt").write_text("halt\n", encoding="utf-8")
    return col_dir


def test_verify_and_push_collection_fail_closed_and_unconfigured(tmp_path):
    fake_home = tmp_path / "home"
    col = _make_sealed_collection(fake_home, tmp_path, "ab-valid")
    ver = brh.verify_sealed_collection(col)
    assert ver["total_episodes"] == 2 and ver["arm_id"] == "arm_ab" and len(ver["manifest_sha256"]) == 64

    unconf = brh.push_collection_to_model(col, {"model_target": ""})
    assert unconf["status"] == "unconfigured" and unconf["ok"] is False

    cmds = []
    fake_run = lambda cmd, **kw: (cmds.append(cmd), types.SimpleNamespace(returncode=0, stdout="", stderr=""))[1]
    pushed = brh.push_collection_to_model(col, {"model_target": "rosy@rosy-omen"}, run=fake_run)
    assert pushed["status"] == "done" and pushed["ok"] is True
    assert pushed["remote_path"] == "~/rosy-test/omx-collections/ab-valid"
    assert cmds[0][:4] == ["ssh", "-o", "BatchMode=yes", "-o"] and "--" in cmds[0]
    assert cmds[1][0] == "scp" and "-r" in cmds[1] and "--" in cmds[1]
    assert "sha256sum" in cmds[0][-1] and "test ! -e" in cmds[2][-1]

    # SSH flag injection, bare "~", public HTTP URLs, and arbitrary hf_repo_id overrides are refused.
    with pytest.raises(ValueError, match="model_target"):
        brh.save_handoff_config(tmp_path, {"model_target": "-oProxyCommand=id@evil"})
    with pytest.raises(ValueError, match="remote_collections_dir"):
        brh.save_handoff_config(tmp_path, {"remote_collections_dir": "~other/cols"})
    with pytest.raises(ValueError, match="https"):
        brh.save_handoff_config(tmp_path, {"intake_url": "http://8.8.8.8:8765/api/learning/canonical/intake"})
    with pytest.raises(ValueError, match="고정"):
        brh.save_handoff_config(tmp_path, {"hf_repo_id": "robotteam/other-repo"})

    # Idempotent ALREADY_MATCHED skips SCP; differing manifest on remote fails closed without overwriting.
    match_cmds = []
    match_run = lambda cmd, **kw: (match_cmds.append(cmd), types.SimpleNamespace(returncode=0, stdout="ALREADY_MATCHED\n", stderr=""))[1]
    already = brh.push_collection_to_model(col, {"model_target": "rosy@rosy-omen"}, run=match_run)
    assert already["status"] == "done" and already.get("already_present") is True and len(match_cmds) == 1

    diff_run = lambda cmd, **kw: types.SimpleNamespace(returncode=2, stdout="", stderr="remote collection exists with different files\n")
    conflict = brh.push_collection_to_model(col, {"model_target": "rosy@rosy-omen"}, run=diff_run)
    assert conflict["status"] == "failed" and conflict["ok"] is False

    # Sealed collection ds_folder ends in '/dataset', so validate_team_hf_upload keeps ds_name & enforces total_episodes >= 1.
    fake_api = types.SimpleNamespace(whoami=lambda: {"name": "op", "orgs": [{"name": "robotteam"}]})
    repo_id, subpath = brh.validate_team_hf_upload(fake_api, col / "dataset", {}, ds_name="ab-valid")
    assert repo_id == "robotteam/rosy-omx-data" and subpath == "ab-valid"
    empty_ep_col = _make_sealed_collection(fake_home, tmp_path, "ab-zero-info", episodes=1)
    (empty_ep_col / "dataset" / "meta" / "info.json").write_text(json.dumps({"total_episodes": 0}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="total_episodes >= 1"):
        brh.validate_team_hf_upload(fake_api, empty_ep_col / "dataset", {}, ds_name="ab-zero-info")

    # Tampered file breaks sha256 verification before any ssh/scp runs.
    (col / "dataset" / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"EVIL")
    with pytest.raises(ValueError, match="SHA-256"):
        brh.verify_sealed_collection(col)

    dnt = _make_sealed_collection(fake_home, tmp_path, "ab-dnt", do_not_train=True)
    with pytest.raises(ValueError, match="DO_NOT_TRAIN"):
        brh.verify_sealed_collection(dnt)


def test_notify_canonical_intake_and_team_hf_policy(tmp_path):
    fake_home = tmp_path / "home"
    col = _make_sealed_collection(fake_home, tmp_path, "ab-intake")
    ver = brh.verify_sealed_collection(col)
    tr = {"remote_path": "~/rosy-test/omx-collections/ab-intake", "verification": ver}

    assert brh.notify_canonical_intake({}, tr)["status"] == "unconfigured"
    assert brh.notify_canonical_intake({"intake_url": "http://127.0.0.1:8765/api/learning/canonical/intake"}, tr)["status"] == "failed"

    tok = tmp_path / "peer.token"
    tok.write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    if os.name == "posix":
        tok.chmod(0o600)

    seen_req = {}
    def fake_urlopen(req, timeout=15):
        seen_req["url"] = req.full_url
        seen_req["auth"] = req.get_header("Authorization")
        seen_req["body"] = json.loads(req.data.decode("utf-8"))
        return io.BytesIO(json.dumps({"ok": True, "job_id": "job-123"}).encode("utf-8"))

    res = brh.notify_canonical_intake(
        {"intake_url": "http://127.0.0.1:8765/api/learning/canonical/intake", "peer_token_file": str(tok)},
        tr, urlopen=fake_urlopen,
    )
    assert res["ok"] is True and seen_req["auth"] == "Bearer 0123456789abcdef0123456789abcdef"
    assert seen_req["body"]["collection"] == "ab-intake" and seen_req["body"]["manifest_sha256"] == ver["manifest_sha256"]


def test_server_on_session_sealed_triggers_honest_auto_handoff_and_persists_config(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    col = _make_sealed_collection(fake_home, tmp_path, "auto-seal-01")

    # Config persistence across fresh Bench reload + HTTP route support.
    cfg_res = bench.pipeline_config({
        "auto_loop": True,
        "model_target": "rosy@rosy-omen",
        "intake_url": "http://127.0.0.1:8765/api/learning/canonical/intake",
        "peer_token_file": str(tmp_path / "tok"),
    })
    assert cfg_res["auto_loop"] is True and cfg_res["model_target"] == "rosy@rosy-omen"

    import bench_record_pipeline as brp
    monkeypatch.setattr(brp, "push_collection_to_model", lambda c, cfg, verified=None: {
        "status": "done", "ok": True, "remote_path": "~/rosy-test/omx-collections/auto-seal-01", "verification": verified,
    })
    monkeypatch.setattr(brp, "notify_canonical_intake", lambda cfg, tr: {
        "status": "done", "ok": True, "response": {"ok": True, "job_id": "intake-job-1"},
    })

    bench.state = {"status": "sealed", "name": "auto-seal-01", "folder": str(tmp_path / "sess")}
    bench._on_session_sealed(tmp_path / "sess")
    import time as _t
    for _ in range(40):
        st = bench.pipeline_status()
        if st["state"] in ("done", "blocked", "failed"):
            break
        _t.sleep(0.05)
    assert st["state"] == "done" and st["loop_count"] == 1
    assert st["stages"]["seal"] == "done" and st["stages"]["transfer"] == "done" and st["stages"]["intake"] == "done"
    assert st["intake_job_id"] == "intake-job-1"
    assert (col / "manifest.json").is_file()


def test_handoff_and_hf_upload_refuse_missing_or_black_top_video(tmp_path, monkeypatch):
    import bench_record_handoff as brh_mod
    import bench_record_preflight as preflight

    fake_home = tmp_path / "home"
    col = _make_sealed_collection(fake_home, tmp_path, "cam-gate-01", episodes=1)
    ds = col / "dataset"

    def _rewrite_manifest_and_info(cams):
        (ds / "meta" / "info.json").write_text(json.dumps({
            "codebase_version": "v3.0", "robot_type": "omx_follower", "total_episodes": 1, "fps": 30,
            "features": {f"observation.images.{c}": {"dtype": "video", "shape": [480, 640, 3]} for c in cams},
        }), encoding="utf-8")
        mf_p = col / "manifest.json"
        mf = json.loads(mf_p.read_text(encoding="utf-8"))
        mf["files"] = {
            p.relative_to(col).as_posix(): brh._sha256_file(p)
            for p in sorted(col.rglob("*")) if p.is_file() and p != mf_p
        }
        mf_p.write_text(json.dumps(mf, indent=2), encoding="utf-8")

    # 1) Missing observation.images.top
    front_mp4 = ds / "videos" / "observation.images.front" / "chunk-000" / "file-000.mp4"
    front_mp4.parent.mkdir(parents=True)
    front_mp4.write_bytes(b"FAKE_MP4")
    _rewrite_manifest_and_info(["front"])
    with pytest.raises(ValueError, match="observation.images.top"):
        brh_mod.verify_sealed_collection(col)

    # 2) Black observation.images.top screen (max_luma=0.0)
    top_mp4 = ds / "videos" / "observation.images.top" / "chunk-000" / "file-000.mp4"
    top_mp4.parent.mkdir(parents=True)
    top_mp4.write_bytes(b"FAKE_BLACK_MP4")
    _rewrite_manifest_and_info(["top", "front"])
    monkeypatch.setattr(preflight, "_probe_video_luma",
                        lambda p: (2278, [0.0, 0.0, 0.0]) if "observation.images.top" in str(p) else (2278, [128.0, 128.0, 128.0]))
    with pytest.raises(ValueError, match="검은 화면"):
        brh_mod.verify_sealed_collection(col)

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    bench.hf_logged_in = lambda: True
    with pytest.raises(ValueError, match="검은 화면"):
        bench.hf_upload_start({"dataset": "cam-gate-01"})

    # 3) Valid non-black top & front passes both verify_sealed_collection and check_dataset_cameras
    monkeypatch.setattr(preflight, "_probe_video_luma",
                        lambda p: (898, [148.2, 148.2, 148.2]) if "observation.images.top" in str(p) else (898, [126.7, 126.7, 127.0]))
    ver = brh_mod.verify_sealed_collection(col)
    assert ver["total_episodes"] == 1
    cam_ok = preflight.check_dataset_cameras(ds)
    assert cam_ok["checked"] is True and cam_ok["cameras"]["observation.images.top"]["max_luma"] == 148.2
