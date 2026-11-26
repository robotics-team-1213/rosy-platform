"""Request the existing Fleet recovery tool for a commissioned arm's current USB hold."""
import hashlib
import json
import re
from urllib.request import Request

from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
from cell_bound_home_placement import bound_request_due


def request_current_homes(base, token, context, open_url, arms, holds, pending):
    roots = {}
    for arm in arms:
        hold = holds.get(arm) or {}
        ids = hold.get("incident_ids")
        if (arm not in pending and hold.get("fleet_held") is True and hold.get("fleet_reason") == HOME_RECOVERY_REASON
                and type(hold.get("unsent_outbox")) is int and hold["unsent_outbox"] == 0
                and isinstance(ids, list) and len(ids) == 1 and isinstance(ids[0], str)
                and re.fullmatch(r"[0-9a-f]{32}", ids[0]) and bound_request_due(arm, ids[0])):
            roots[f"home-recovery:{arm}:{ids[0]}"] = arm
    if not roots:
        return
    url = base + "/api/fleet/pipeline/recovery-tools"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with open_url(Request(url, headers=headers), context=context, timeout=6) as stream:
        failures = json.load(stream)["active_failures"]
    for item in failures:
        root = item.get("root_task_id")
        arm = roots.get(root)
        if (not arm or item.get("arm_id") != arm or item.get("trigger_code") != "HOME_RECOVERY_REQUIRED"
                or item.get("homing_strategies", {}).get("auto_fold", {}).get("allowed") is not True):
            continue
        digest = item["context_sha256"]
        key = hashlib.sha256(f"{root}/{digest}".encode()).hexdigest()
        payload = {"tool_name": "safe_fold_home", "arguments": {"arm_id": arm, "strategy": "auto_fold"},
                   "root_task_id": root, "expected_context_sha256": digest, "request_id": f"usb-home-{key}",
                   "caller_kind": "system", "rationale": "Guarded return for the current USB home recovery record"}
        with open_url(Request(url + "/invoke", data=json.dumps(payload).encode(), headers=headers),
                      context=context, timeout=6) as stream:
            json.load(stream)
