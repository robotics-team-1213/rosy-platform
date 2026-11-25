import datetime as dt
import json
from types import SimpleNamespace

import pytest

from test_pinky_loc_pipeline import plp


def test_surveyed_holdout_uses_fresh_stationary_core(tmp_path):
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    state = {"robot_id": "rosy_42", "online": True, "map_grid_id": "grid",
             "pose": {"x": 0.3, "y": 0.4}, "velocity": {"linear": 0, "angular": 0},
             "localization": {"state": "LOCALIZED", "pose_frame": "map"},
             "evidence": {"pose": {"evidence": "fresh", "received_at": stamp},
                          "velocity": {"evidence": "fresh", "sampled_at": stamp}}}
    endpoints = {"/api/fleet/site-map/active": {"map": {"map_id": "floor"}, "version": 1},
                 "/api/fleet/state": {"robots": [state]}}
    client = SimpleNamespace(request_json=lambda method, path: endpoints[path])
    path = tmp_path / "samples.json"
    args = dict(robot_id="rosy_42", out_path=path, pair_spec=None, grid_id_override=None,
                site_map_id_override=None, holdout=True, max_track_age_s=1, surveyed_site=(0.8, 0.9))
    assert plp.run_sample(client, **args) == 0
    saved = path.read_bytes()
    row = json.loads(saved)["samples"][0]
    assert (row["robot"], row["site"], row["source"]) == ([0.3, 0.4], [0.8, 0.9], "manual")
    assert row["holdout"] and row["robot_pose_received_at"] == stamp
    state["velocity"]["linear"] = 0.1
    with pytest.raises(plp.PipelineError, match="stand still"):
        plp.run_sample(client, **args)
    del state["velocity"]["linear"]
    with pytest.raises(plp.PipelineError, match="fresh measured"):
        plp.run_sample(client, **args)
    state["velocity"]["linear"] = 0
    state["evidence"]["pose"]["evidence"] = "stale"
    with pytest.raises(plp.PipelineError, match="fresh measured"):
        plp.run_sample(client, **args)
    assert path.read_bytes() == saved
