#!/usr/bin/env python3
"""Arm incidents a person cleared with a cause, as label rows learning scores against (model PC, D-516).

Each row keeps three answers apart and never merges them: the person's cause with its basis, the measured reading the cell
made at the stop (`facts.stop_reading`, cell_why), and the AI PC's explanation. Only a cause known by a repeat or a
measurement counts as truth (`truth`); a cause seen in pictures measures how often people misread (2026-11-07: people,
models and frame strips all misread contact). The label block has the shape of the learning media labels
(rosy.contracts.learning.media: origin, status, author, reviewer, evidence), unreviewed until a second person approves.

  arm_incident_labels.py pull --url https://<fleet> --token-env ROSY_AI_OBSERVER_TOKEN [--ca ca.pem] --out labels.jsonl
  arm_incident_labels.py score --out labels.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

SCHEMA = "rosy.omx-arm-incident-label.v1"
TRUTH = ("repeat", "measured")
LABELLED = "/api/fleet/workcell-observations/arm-incidents/labelled"


def row(incident: dict) -> dict:
    cleared, facts = incident["cleared"], incident.get("facts") or {}
    reading = facts.get("stop_reading") or {}
    return {"schema": SCHEMA, "incident_id": incident["incident_id"], "source_id": incident["source_id"],
            "reported_at": incident["reported_at"], "cleared_at": cleared["at"],
            "person": {"cause": cleared["cause"], "basis": cleared["basis"], "note": cleared["note"], "by": cleared["by"]},
            "rule": {"hypothesis": reading.get("hypothesis") or reading.get("verdict"), "reading": reading,
                     "decision": (incident.get("decision") or {}).get("reason")},
            "model": incident.get("explanation"), "stops": facts.get("stops", []),
            "evidence": [{k: e[k] for k in ("camera", "t_rel_s", "kind", "sha256")} for e in incident.get("evidence", [])],
            "truth": cleared["basis"] in TRUTH,
            "labels": {"ontology_revision": None, "semantic_ids": [f"arm_stop_cause:{cleared['cause']}"], "origin": "human",
                       "status": "unreviewed", "author": cleared["by"], "reviewer": None, "evidence": []}}


def pull(url: str, token: str, out: Path, context=None) -> int:
    """Append the labelled incidents not yet in `out`; returns how many were new."""
    request = urllib.request.Request(url.rstrip("/") + LABELLED, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=20, context=context) as reply:
        incidents = json.loads(reply.read())["incidents"]
    return keep(incidents, out)


def keep(incidents: list, out: Path) -> int:
    have = {json.loads(line)["incident_id"] for line in out.read_text().splitlines()} if out.exists() else set()
    new = [row(i) for i in incidents if i["incident_id"] not in have and (i.get("cleared") or {}).get("cause")]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for r in sorted(new, key=lambda r: r["cleared_at"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


def score(rows: list) -> dict:
    """The rule's reading against the person's cause where the person's cause is truth; and how many rows of each basis."""
    truth = [r for r in rows if r["truth"]]
    read = [r for r in truth if r["rule"]["hypothesis"] not in (None, "undetermined", "unknown")]
    return {"rows": len(rows), "by_basis": {b: sum(r["person"]["basis"] == b for r in rows) for b in (*TRUTH, "seen", "unknown")},
            "truth": len(truth), "rule_read": len(read), "rule_agreed": sum(r["rule"]["hypothesis"] == r["person"]["cause"] for r in read)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--url", required=True)
    p.add_argument("--token-env", required=True)
    p.add_argument("--ca")
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        context = ssl.create_default_context(cafile=args.ca) if args.ca else None
        print(json.dumps({"new": pull(args.url, os.environ[args.token_env], args.out, context)}))
    else:
        print(json.dumps(score([json.loads(line) for line in args.out.read_text().splitlines()])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
