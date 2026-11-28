"""PR D tests: live Cell PC catalog-only object metadata publisher and post-pick CellStateGen bump."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_camera_telemetry_sync as ccts  # noqa: E402
from cell_job_readiness import CellStateGen  # noqa: E402
import cell_object_view as cov  # noqa: E402
import cell_objects_sync as cos  # noqa: E402


class _FakeResp(io.BytesIO):
    def __init__(self, body: bytes = b'{"ok":true}', headers: dict[str, str] | None = None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_sync_cell_objects_strips_unmatched_and_media_and_pushes_extra_targets(tmp_path: Path, monkeypatch):
    prep = tmp_path / "prep"
    CellStateGen(prep / "cell-job-api" / "cell-state-gen.json").bump()
    extra_tok = tmp_path / "arm-cell.token"
    extra_tok.write_text("arm-cell-tok\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_CELL_OBJECTS_TARGETS", f"http://arm-cell.local:8443|{extra_tok}")

    def fake_detect(_prep, arm, **_kw):
        if arm == "arm_a":
            return {"status": "config_unavailable", "objects": []}
        return {
            "schema": cov.SCHEMA, "cell_id": "cell_s" if arm == "arm_s" else "cell_ab", "arm_id": arm,
            "camera_role": "arm_s_top" if arm == "arm_s" else "top", "frame_wh": [640, 480],
            "source_seq": 77, "observed_at": 1700000100.5, "ttl_s": 15.0, "status": "ok",
            "objects": [
                {"catalog_id": "unmatched", "object_ref": "det:77:0", "site": "pinky", "centre_mm": [1.0, 2.0], "pickable": True},
                {"catalog_id": "container-1", "object_ref": "det:77:1", "site": "pinky", "centre_mm": [10.0, 20.0],
                 "centre_px": [300.0, 220.0], "corners_px": [[270, 190], [330, 190], [330, 250], [270, 250]],
                 "pickable": True, "bind_tol_mm": 13.5, "image_b64": "data:image/jpeg;base64,/9j/4AAQ"},
            ],
        }

    posted: list[tuple[str, str, dict]] = []

    def fake_urlopen(req, **_kw):
        posted.append((req.full_url, req.headers.get("Authorization", ""), json.loads(req.data.decode("utf-8"))))
        return _FakeResp()

    with patch.object(cov, "detect_objects", side_effect=fake_detect):
        out = cos.sync_cell_objects("http://fleet-r:8443", "fleet-tok", None, fake_urlopen, prep_dir=prep)

    assert out["cell_state_gen"] == 1
    assert out["arms"]["arm_a"]["status"] == "config_unavailable"
    assert out["posted"] == 4  # (arm_s, arm_b) x (fleet-r, arm-cell)
    assert out["errors"] == {}
    urls = {u for u, _, _ in posted}
    assert urls == {"http://fleet-r:8443/api/fleet/pipeline/cell-objects", "http://arm-cell.local:8443/api/fleet/pipeline/cell-objects"}
    for _, auth, payload in posted:
        assert auth in ("Bearer fleet-tok", "Bearer arm-cell-tok")
        assert payload["cell_state_gen"] == 1
        assert [o["catalog_id"] for o in payload["objects"]] == ["container-1"]
        assert "image_b64" not in payload["objects"][0]


def test_sync_cell_objects_isolates_viewer_and_post_errors(tmp_path: Path):
    prep = tmp_path / "prep"

    def flaky_detect(_prep, arm, **_kw):
        if arm == "arm_s":
            raise TimeoutError("viewer down")
        return {
            "schema": cov.SCHEMA, "cell_id": "cell_ab", "arm_id": arm, "camera_role": "top",
            "observed_at": 1700000200.0, "status": "ok",
            "objects": [{"catalog_id": "box-2", "object_ref": "det:8:0", "site": "yard", "centre_mm": [5.0, -3.0], "pickable": False}],
        }

    calls: list[str] = []

    def flaky_urlopen(req, **_kw):
        calls.append(req.full_url)
        if "broken.local" in req.full_url:
            raise OSError("connection refused")
        return _FakeResp()

    with patch.object(cov, "detect_objects", side_effect=flaky_detect):
        out = cos.sync_cell_objects(
            "http://fleet-r:8443", "tok", None, flaky_urlopen,
            prep_dir=prep, extra_targets=[("http://broken.local:8443", "t2", None)],
        )

    assert "arm_s" in out["errors"] and out["arms"]["arm_a"]["objects"] == 1 and out["posted"] == 2
    assert any("broken.local" in k for k in out["errors"])


def test_bump_state_gen_after_pick_and_telemetry_hook(tmp_path: Path):
    prep = tmp_path / "prep"
    gen = CellStateGen(prep / "cell-job-api" / "cell-state-gen.json")
    assert gen.current() == 0
    assert cos.bump_state_gen_after_pick(prep, arm_id="arm_s", placed=False) is None
    assert gen.current() == 0
    assert cos.bump_state_gen_after_pick(prep, arm_id="arm_s", placed=True, task_id="t-1") == 1
    assert gen.current() == 1

    seen_urls: list[str] = []

    def mock_urlopen(req, **_kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        seen_urls.append(url)
        if url.endswith("/state.json"):
            return _FakeResp(b"{}")
        return _FakeResp(b'{"ok":true}')

    with patch.object(cov, "detect_objects", return_value={"status": "config_unavailable", "objects": []}):
        qout = ccts.sync_cell_telemetry("http://127.0.0.1:8443", "tok", prep_dir=prep, urlopen_fn=mock_urlopen)
    assert "cell_objects_sync" in qout and qout["cell_objects_sync"]["cell_state_gen"] == 1
    assert any(u.endswith("/api/fleet/pipeline/cell-quality") for u in seen_urls)


def test_make_ca_urlopen_preserves_extra_target_ssl_context_and_isolates_malformed_det(tmp_path: Path, monkeypatch):
    import cell_task_exec as cte

    primary_ca = tmp_path / "primary-ca.pem"
    extra_ca = tmp_path / "extra-ca.pem"
    primary_ca.write_text("PRIMARY", encoding="utf-8")
    extra_ca.write_text("EXTRA", encoding="utf-8")
    tok_file = tmp_path / "tok"
    tok_file.write_text("t-extra\n", encoding="utf-8")

    sentinel_primary = object()
    sentinel_extra = object()
    seen: list[tuple[str, object]] = []

    def fake_default_ctx(*, cafile=None):
        return sentinel_primary if cafile == str(primary_ca) else (sentinel_extra if cafile == str(extra_ca) else object())

    def fake_raw_urlopen(req, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        seen.append((url, kwargs.get("context")))
        return _FakeResp()

    monkeypatch.setattr("cell_task_exec.ssl.create_default_context", fake_default_ctx)
    monkeypatch.setattr("cell_objects_sync.ssl.create_default_context", fake_default_ctx)
    monkeypatch.setattr("cell_task_exec.urlopen", fake_raw_urlopen)
    opener = cte.make_ca_urlopen(primary_ca)

    with patch.object(cov, "detect_objects", side_effect=[
        None,  # malformed non-dict return must isolate without breaking telemetry
        {"schema": cov.SCHEMA, "cell_id": "cell_ab", "arm_id": "arm_a", "camera_role": "top",
         "observed_at": 1700000300.0, "status": "ok",
         "objects": [{"catalog_id": "box-1", "object_ref": "det:1:0", "site": "yard", "centre_mm": [1.0, 2.0], "pickable": True}]},
        {"status": "config_unavailable", "objects": []},
    ]):
        out = cos.sync_cell_objects(
            "https://fleet-r:8443", "tok-main", sentinel_primary, opener,
            prep_dir=tmp_path, extra_targets=[("https://arm-cell:8443", "tok-extra", str(extra_ca))],
        )

    assert out["errors"]["arm_s"] == "TypeError" and out["posted"] == 2
    by_url = dict(seen)
    assert by_url["https://fleet-r:8443/api/fleet/pipeline/cell-objects"] is sentinel_primary
    assert by_url["https://arm-cell:8443/api/fleet/pipeline/cell-objects"] is sentinel_extra
    opener("https://example.invalid/ping", context=sentinel_extra)
    assert seen[-1][1] is sentinel_primary  # primary opener still overrides untrusted context

    monkeypatch.setattr("cell_objects_sync.sync_cell_objects", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    qout = ccts.sync_cell_telemetry("http://127.0.0.1:8443", "tok", prep_dir=tmp_path, urlopen_fn=lambda _r, **_k: _FakeResp(b"{}"))
    assert qout.get("cell_objects_sync_error") == "RuntimeError" and "safe_home_blocked_reason" in qout
