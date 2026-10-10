"""Bind a Fleet incident export to harvested stuck markers by exact stuck_id.

Run: python incident_feedback.py incidents.json stuck_markers.json --out feedback.json
The output is de-identified review evidence for offline analysis, not a pixel label,
model approval, or permission to move a robot. An operator exports incidents from
Fleet; this tool never holds a Fleet token or calls a robot.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CAUSES = {"line_marking", "obstacle", "robot_fault", "localization", "traffic_wait", "unknown"}
SCHEMA = "rosy.recording.incident_feedback/1"


def bind(incidents: dict, markers: dict) -> dict:
    if not isinstance(incidents, dict) or not isinstance(incidents.get("reports"), list):
        raise ValueError("Fleet incidents export requires reports")
    if not isinstance(markers, dict) or markers.get("schema") != "rosy.recording.stuck_markers/1" or not isinstance(markers.get("markers"), list):
        raise ValueError("recording stuck_markers schema differs")
    reports = {}
    for row in incidents["reports"]:
        if not isinstance(row, dict) or row.get("schema") != "rosy.incident.v1" or row.get("classification") != "line_stuck":
            raise ValueError("invalid line-stuck report")
        ids, sid = row.get("robot_ids"), row.get("stuck_id")
        if (not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str)
                or not isinstance(sid, str) or not sid
                or row.get("id") != f"line_stuck:{ids[0]}:{sid}"):
            raise ValueError("incident identity differs")
        if sid in reports:
            raise ValueError("duplicate stuck_id in incident export")
        reports[sid] = row
    matches, missing, seen = [], [], set()
    for marker in markers["markers"]:
        sid = marker.get("stuck_id") if isinstance(marker, dict) else None
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("invalid or duplicate recording stuck_id")
        seen.add(sid)
        row = reports.get(sid)
        if row is None:
            missing.append(sid)
            continue
        evidence = row.get("evidence") or {}
        reviews = row.get("reviews") or []
        if not isinstance(reviews, list):
            raise ValueError("incident reviews must be a list")
        causes = set()
        for review in reviews:
            if (not isinstance(review, dict) or review.get("root_cause") not in CAUSES
                    or not isinstance(review.get("principal_id"), str) or not review["principal_id"]
                    or not isinstance(review.get("at"), str) or not review["at"]):
                raise ValueError("invalid named operator review")
            causes.add(review["root_cause"])
        drafts = {fact.get("value", {}).get("cause_draft") for fact in evidence.get("ai_facts") or []
                  if isinstance(fact, dict) and fact.get("kind") == "incident_context"
                  and (fact.get("evidence") or {}).get("stuck_id") == sid}
        matches.append({"incident_id": row["id"], "stuck_id": sid, "robot_id": row["robot_ids"][0],
                        "core_cause": (evidence.get("core") or {}).get("cause"),
                        "ai_cause_draft": next(iter(drafts)) if len(drafts) == 1 else None,
                        "rosy_cam_linked": evidence.get("rosy_cam") is not None,
                        "front_image_status": (evidence.get("front_image") or {}).get("status"),
                        "review_state": "unreviewed" if not reviews else "review_candidate" if len(causes) == 1 else "disputed",
                        "reviewed_root_cause": next(iter(causes)) if len(causes) == 1 else None,
                        "review_count": len(reviews)})
    return {"schema": SCHEMA, "matches": matches, "missing_incidents": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incidents", type=Path)
    parser.add_argument("markers", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = bind(json.loads(args.incidents.read_text(encoding="utf-8-sig")),
                  json.loads(args.markers.read_text(encoding="utf-8-sig")))
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(result['matches'])} matched, {len(result['missing_incidents'])} missing: {args.out}")


if __name__ == "__main__":
    main()
