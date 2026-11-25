"""Publish the independently observed slot of a completed inbound placement."""
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json

from core_common.protocol.port_events import PortEvent, event_id


def placement_events(tasks, snapshot, *, now, task_id=None):
    observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    if observed.timestamp() > now:
        return
    sites = defaultdict(list)
    for site in snapshot["sites"]:
        if site["object_ref_read"]:
            sites[site["object_ref_read"]].append(site)
    history = defaultdict(list)
    for task in tasks:
        if task.get("cell_id") == "cell_ab" and task.get("object_ref") in sites:
            history[task["object_ref"]].append(task)
    for cargo, moves in history.items():
        sightings = sites[cargo]
        if len(sightings) != 1 or sightings[0]["state"] != "OCCUPIED":
            continue
        moves.sort(key=lambda t: t.get("created_at", 0))
        latest = moves[-1]
        receipt = latest.get("receipt") or {}
        if (not latest.get("placement_attempt_id") or not latest.get("intake_occurrence_id")
                or (task_id is not None and latest["task_id"] != task_id)
                or latest.get("status") != "COMPLETED" or not latest.get("completed_at")
                or not latest.get("created_at") or latest["completed_at"] < latest["created_at"]
                or latest["completed_at"] > observed.timestamp()
                or receipt.get("physical_completion") is not True or receipt.get("simulated_success") is not False
                or receipt.get("stage_id") != latest["task_id"] or receipt.get("phase") != "RELEASED"
                or not latest.get("handoff_lease_id") or receipt.get("handoff_lease_id") != latest["handoff_lease_id"]
                or (latest.get("stage_result") or {}).get("task_verified") is not True):
            continue
        # Never attribute a delayed frame to a newer move or resolve overlapping work by creation order.
        if any(t.get("status") not in {"CANCELLED", "ABORTED", "COMPLETED"}
               or t.get("created_at") == latest["created_at"]
               or (t.get("completed_at") or 0) > latest["created_at"] for t in moves[:-1]):
            continue
        key = json.dumps([snapshot["source_id"], snapshot["snapshot_id"], cargo], ensure_ascii=True)
        ref = "site-recognition:" + sha256(key.encode()).hexdigest()
        yield PortEvent(event_id=event_id("cell_ab", ref, "container.stored"), kind="container.stored",
                        observation_ref=ref, object_ref=cargo, slot_ref=sightings[0]["site_ref"],
                        identity="observed", observed_at=observed, intake_occurrence_id=latest["intake_occurrence_id"],
                        placement_attempt_id=latest["placement_attempt_id"])
