import hashlib
import json
import math
from types import SimpleNamespace

import pytest
from test_bay_dock import bd
from bay_commission import commission_only


@pytest.mark.parametrize("case", ["dry", "apply", "wrong_bay", "grid", "nominal_disagrees", "stale", "aisle"])
def test_stationary_registration_is_bound_to_independent_site_survey(tmp_path, case):
    ticks, writes = [1000.], []
    state = dict(mode="IDLE", robot_id="rosy_42", map_id="slam", map_grid_id="grid", map_generation=2,
                 pose=dict(x=1., y=0., yaw=0.), pose_frame="map", localization={"state":"LOCALIZED"},
                 navigation="ARRIVED", line_follow={"mode":"OFF"}, velocity={"linear":0., "angular":0.},
                 evidence={key:{"evidence":"fresh"} for key in ("pose","velocity")})
    def get(path):
        if path == "/robot/state":
            return dict(state, map_grid_id="other") if case == "grid" and ticks[0] > 1001 else state
        assert path == "/sensors/dock_observation"
        return dict(source="CAMERA_LINE", ground="NOMINAL", visible=True, evidence="fresh",
                    along_measured=True, lateral_measured=case != "aisle", stamp=1. if case=="stale" else ticks[0],
                    x=-.1, y=0., yaw=math.pi)
    artifact = b"independent stop-face survey test fixture"
    (tmp_path / "survey").write_bytes(artifact)
    record = dict(bay_id="C1" if case=="wrong_bay" else "C2", robot_id="rosy_42", observed_at=1000.,
                  site_map_id="site", site_map_version=5, judged_by="operator", in_bay_line=True,
                  rear_toward_bay=True, cable_absent=True, survey=dict(method="field_measurement", measured_by="operator",
                  stop_face_site=dict(x=.6 if case == "nominal_disagrees" else .9,y=0.,yaw=math.pi),
                  artifact="survey",sha256=hashlib.sha256(artifact).hexdigest()))
    verdict = tmp_path/"verdict.json"
    verdict.write_text(json.dumps(record))
    bind = {"matches":True, "active":{"binding_id":"bind", "approved_by":"operator", "site_map_id":"site",
            "site_map_version":5, "fit":{"yaw":0., "tx":0., "ty":0.}, "robot_id":"rosy_42", "robot_grid_id":"grid"}}
    run = SimpleNamespace(ev=tmp_path,args=SimpleNamespace(dock_id="bay_c2",apply_commission=case!="dry",
                         bay_verdict=verdict),get=get,r=SimpleNamespace(now=lambda:ticks[0],
                         sleep=lambda n:ticks.__setitem__(0,ticks[0]+n),_site=lambda *a,**k:json.dumps(bind),
                         _site_token=lambda:None))
    def post(path, body):
        writes.append(path)
        assert body["map_grid_id"]=="grid" and body["dock"]["x"]==pytest.approx(.9)
        return 200, body["dock"]
    run.post=post
    assert commission_only(run) == int(case not in ("dry","apply"))
    assert writes == (["/docking/commission"] if case == "apply" else [])
