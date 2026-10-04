from test_cell_job_api import _setup, _post, _candidate
from pathlib import Path

import pytest
import yaml

from fleet.server.cell_compiler import PalletizingCellJobCompiler


def test_fleet_without_cell_does_not_import_optional_goal_resolver(monkeypatch):
    import sys
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole

    monkeypatch.setitem(sys.modules, "fleet.server.cell_goal_evidence", None)
    app = create_app(FleetConsole([], []))
    assert app.state.cell_job_store is None


def _save(client, kind, identifier, document, token="operator-secret", expected=None):
    return _post(client, f"/api/fleet/cell-app/documents/{kind}/{identifier}", token,
                 {"document": document, "expected_digest": expected})


def _refs(client):
    recipe = _save(client, "recipe", "demo", _candidate()["recipe"]).json()
    cell = _save(client, "cell", "demo", _candidate()["cell"]).json()
    return {"recipe_id": "demo", "recipe_digest": recipe["digest"],
            "cell_id": "demo", "cell_digest": cell["digest"]}


def test_named_operator_document_revision_and_preview_have_no_mission_effect(tmp_path):
    client, tasks, compiler = _setup(tmp_path)
    assert _save(client, "recipe", "demo", {}, token="viewer-secret").status_code == 403
    assert _save(client, "recipe", "demo", {}, token="cell-secret").status_code == 403
    refs = _refs(client)
    preview = _post(client, "/api/fleet/cell-app/compile", "operator-secret", refs)
    assert preview.status_code == 200
    assert preview.json()["candidate"]["job"]["steps"] == ["transfer-0", "transfer-1"]
    assert client.app.state.cell_job_store is not None
    assert _save(client, "recipe", "demo", {}).status_code == 409
    changed = {**refs, "recipe_digest": "0" * 64}
    assert _post(client, "/api/fleet/cell-app/compile", "operator-secret", changed).status_code == 409
    assert compiler.calls == 1


def test_app_proposal_uses_configured_service_and_never_admits(tmp_path):
    client, tasks, compiler = _setup(tmp_path, cell_app_service_id="cell-service")
    refs = _refs(client)
    body = {**refs, "request_key": "app-request-1", "workcell_id": "omx_01", "instance_id": "omx_01_control"}
    result = _post(client, "/api/fleet/cell-app/proposals", "operator-secret", body)
    assert result.status_code == 200, result.text
    proposal_id = result.json()["proposal"]["proposal_id"]
    assert result.json()["mission"]["status"] == "PROPOSED"
    assert client.app.state.proposal_store.get(proposal_id)["principal_id"] == "cell-service"
    repeated = _post(client, "/api/fleet/cell-app/proposals", "operator-secret", body)
    assert repeated.status_code == 200 and repeated.json()["proposal"]["proposal_id"] == proposal_id
    assert repeated.json()["mission"]["status"] == "PROPOSED"
    assert _post(client, f"/api/fleet/missions/{proposal_id}/admit", "cell-secret",
                 {"expected_generation": 0}).status_code == 403


def test_proposal_requires_explicit_service_configuration(tmp_path):
    client, tasks, compiler = _setup(tmp_path)
    body = {**_refs(client), "request_key": "one", "workcell_id": "omx_01", "instance_id": "omx_01_control"}
    assert _post(client, "/api/fleet/cell-app/proposals", "operator-secret", body).status_code == 503


def test_real_compiler_round_trip_and_separate_admission(tmp_path):
    examples = Path(__file__).resolve().parents[3] / "operations/processes/cell/examples/omx_sim"
    compiler = PalletizingCellJobCompiler(tol_m=0.001)
    client, tasks, _ = _setup(tmp_path, compiler=compiler, cell_app_service_id="cell-service")
    refs = {}
    for kind in ("recipe", "cell"):
        document = yaml.safe_load((examples / f"{kind}.yaml").read_text(encoding="utf-8"))
        result = _save(client, kind, "demo", document)
        assert result.status_code == 200, result.text
        refs[f"{kind}_id"] = "demo"
        refs[f"{kind}_digest"] = result.json()["digest"]
    preview = _post(client, "/api/fleet/cell-app/compile", "operator-secret", refs)
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["transfer_count"] == 18
    assert preview.json()["candidate"]["job"]["recipe_hash"] == preview.json()["candidate"]["recipe_sha256"]
    proposal = _post(client, "/api/fleet/cell-app/proposals", "operator-secret", {
        **refs, "request_key": "canonical-1", "workcell_id": "omx_sim", "instance_id": "omx_sim_01"})
    assert proposal.status_code == 200, proposal.text
    mission = proposal.json()["mission"]
    assert mission["status"] == "PROPOSED"
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    admitted = _post(client, f"/api/fleet/missions/{mission['mission_id']}/admit", "operator-secret",
                     {"expected_generation": generation})
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["mission"]["status"] == "READY"


@pytest.mark.parametrize("service", ["missing", "operator-1", "viewer-1"])
def test_service_composition_refuses_missing_or_wrong_role(tmp_path, service):
    with pytest.raises(ValueError, match="configured service principal"):
        _setup(tmp_path, cell_app_service_id=service)
