from types import SimpleNamespace

from fleet.server.pipeline.bound_home_receipt import bound_ack_allowed, deliver_bound, mirror_bound_clear, record_readiness


def test_only_upgraded_owner_receives_request_and_only_bound_clear_changes_hold():
    arm, incident = "arm_s", "b" * 32
    cells = {arm: "cell_s"}
    root = f"home-recovery:{arm}:{incident}"
    pending = {arm: {"root_task_id": root, "request_id": "r", "incident_id": incident}}
    st = SimpleNamespace(omx_owner_principals={"cell-owner"}, arm_holds={arm: {"held": True, "incident_ids": [incident]}},
                         pending_safe_home_arms=pending,
                         pipeline_homing_sessions={root: {"arm_id": arm, "active_request_id": "r"}})
    user = SimpleNamespace(state=SimpleNamespace(site_principal=SimpleNamespace(principal_id="cell-owner")))
    other = SimpleNamespace(state=SimpleNamespace(site_principal=SimpleNamespace(principal_id="other")))
    ack = {"arm_id": arm, "request_id": "r", "outcome": "completed"}
    report = {"fleet_held": False, "local_held": False, "unsent_outbox": 0, "incident_ids": []}
    body = {"incident_bound_home": True, "incident_bound_home_arms": [arm], "safe_home_acks": [ack], "arm_holds": {arm: report}}
    assert deliver_bound(st, user, {}, cells, pending) == deliver_bound(st, other, body, cells, pending) == {}
    assert deliver_bound(st, user, body, cells, pending) == pending
    record_readiness(st, user, body, cells, 123)
    assert st.bound_home_ready_at == {arm: 123}
    record_readiness(st, user, {}, cells, 124)
    assert not st.bound_home_ready_at
    assert not bound_ack_allowed(st, user, body, cells, ack)
    ack["cleared_incident_id"] = incident
    assert bound_ack_allowed(st, user, body, cells, ack)
    for key, value in (("fleet_held", None), ("local_held", True), ("unsent_outbox", 1), ("incident_ids", ["new"])):
        assert not mirror_bound_clear(st, user, {**body, "arm_holds": {arm: {**report, key: value}}}, cells)
    assert not mirror_bound_clear(st, other, body, cells)
    assert mirror_bound_clear(st, user, body, cells)
    assert not st.arm_holds[arm]["held"] and st.pipeline_homing_sessions[root]["stage"] == "CLEARED"
    assert not mirror_bound_clear(st, user, body, cells)
