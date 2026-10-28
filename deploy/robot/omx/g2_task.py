"""G2 composition of the existing topic client and existing role-bound Fleet transport."""
import json
from pathlib import Path

SIM_TOPIC = "SIM box-only16: execute the caller-selected registered OMX recipe and cell"


class RoleApi:
    def __init__(self, client, role):
        if role not in {"proposer", "approver"}:
            raise ValueError("G2 task requests require an existing named operator role")
        self.client, self.role = client, role

    def request(self, method, path, body=None):
        return self.client.request(method, path, body, role=self.role)


def submit_topic_task(run, client, binding):
    # G2 imports its source closure in preflight; do not load Fleet at SDK probe import time.
    from fleet.server.cell_task_client import admit_task, prepare_task
    output = Path(run) / "topic-task"
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    prepared = output / "prepare"
    proposal = prepare_task(RoleApi(client, "proposer"), SIM_TOPIC, binding, prepared)
    plan = json.loads((prepared / "plan.json").read_text(encoding="utf-8"))
    count = plan.get("summary", {}).get("transfer_count")
    if type(count) is not int or count != 16:
        raise RuntimeError("Cell app saved plan differs from the reviewed box-only16 scenario")
    control = client.request("GET", "/api/fleet/dispatch-control", role="approver")
    admitted = admit_task(RoleApi(client, "approver"), prepared, control["generation"], output / "admission")
    mission_id = admitted["mission"]["mission_id"]
    if mission_id != proposal["mission"]["mission_id"]:
        raise RuntimeError("admitted mission differs from the saved topic task; reconcile only")
    return mission_id
