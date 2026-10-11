"""Bind a Fleet incident export to harvested stuck markers by exact stuck_id.

Run: python incident_feedback.py incidents.json stuck_markers.json --out feedback.json
The output is de-identified review evidence for offline analysis, not a pixel label,
model approval, or permission to move a robot. An operator exports incidents from
Fleet; this tool never holds a Fleet token or calls a robot.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.incident_handoff import validate_handoff
from rosy.contracts.learning.incident_profiles import validate_primary_roles

CAUSES = {"line_marking", "obstacle", "robot_fault", "localization", "traffic_wait", "unknown"}
SCHEMA = "rosy.recording.incident_feedback/1"
FAILURE_OWNERS = dict(judgment='Decision', observation='Perception', map='SiteMap',
                      field_connection='Fleet', device='CORE/device', unknown='unassigned')


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


def attach_model_feedback(recording_feedback: dict, exported: dict) -> dict:
    """Attach bound, unreviewed model evidence; a content hash is not a truth label."""
    if (type(recording_feedback) is not dict or recording_feedback.get('schema') != SCHEMA
            or type(recording_feedback.get('matches')) is not list
            or type(exported) is not dict or set(exported) != {'schema', 'case', 'digest', 'label_state', 'field_accepted'}
            or exported['schema'] not in {'rosy.incident.model_feedback/1', 'rosy.incident.model_feedback/2', 'rosy.incident.model_feedback/3'}
            or exported['label_state'] != 'UNREVIEWED' or exported['field_accepted'] is not False
            or type(exported['case']) is not dict):
        raise ValueError('invalid unreviewed model feedback')
    case = exported['case']
    single = exported['schema'].endswith('/3')
    if single: validate_primary_roles(case)
    if single or 'profiles' in case:
        profiles = case.get('profiles')
        expected = ['primary'] if single else ['primary', 'reviewer']
        if (type(case.get('scope')) is not dict or type(profiles) is not list or len(profiles) != len(expected)
                or any(type(p) is not dict for p in profiles) or [p.get('role') for p in profiles] != expected
                or hashlib.sha256(json.dumps(profiles, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                    != (case.get('scope') or {}).get('profile_sha256')):
            raise ValueError('model feedback manifest or strategy differs')
    if exported['schema'].endswith('/2') or single and 'handoff' in case:
        if type(case.get('budget')) is not dict or 'handoff' not in case:
            raise ValueError('missing handoff evidence')
        validate_handoff(case['handoff'], case.get('scope'), case['budget'].get('started_at'))
    elif 'handoff' in case:
        raise ValueError('versioned handoff evidence required')
    encoded = json.dumps(case, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    if len(encoded) > 1024 * 1024 or hashlib.sha256(encoded).hexdigest() != exported['digest']:
        raise ValueError('model feedback content hash differs')
    scope = case.get('scope')
    if (type(scope) is not dict or set(scope) != {'subject_id', 'case_id', 'owner_id', 'profile_sha256', 'policy_revision'}
            or any(type(scope[k]) is not str or not scope[k] for k in scope)
            or re.fullmatch('[0-9a-f]{64}', scope['profile_sha256']) is None
            or type(case.get('reason')) is not str or re.fullmatch('[A-Z0-9_]{1,64}', case['reason']) is None
            or case.get('state') not in {'ACTIVE', 'HOLD', 'NOT_NEEDED'}
            or case.get('outcome') not in {'IN_PROGRESS', 'UNRESOLVED', 'RESOLVED_OBSERVED', 'DO_NOT_INTERVENE'}):
        raise ValueError('invalid bound model feedback')
    for key in ('calls', 'observations', 'spent_micros', 'reserved_micros'):
        if type(case.get(key)) is not int or not 0 <= case[key] <= (8 if key in {'calls', 'observations'} else 1_000_000_000_000):
            raise ValueError('invalid model feedback counter')
    matches = [row for row in recording_feedback['matches']
               if (row.get('robot_id'), row.get('stuck_id')) == (scope['subject_id'], scope['case_id'])]
    if len(matches) != 1:
        raise ValueError('model feedback does not match exactly one recording incident')
    result = json.loads(json.dumps(recording_feedback, allow_nan=False))
    for row in result['matches']:
        if (row['robot_id'], row['stuck_id']) == (scope['subject_id'], scope['case_id']):
            row['model_feedback'] = {key: case[key] for key in ('state', 'outcome', 'reason', 'calls',
                                     'observations', 'spent_micros', 'reserved_micros')}
            row['model_feedback'].update(profile_sha256=scope['profile_sha256'], digest=exported['digest'],
                                         label_state='UNREVIEWED')
            if 'handoff' in case: row['model_feedback']['handoff'] = json.loads(json.dumps(case['handoff']))
    result['schema'] = 'rosy.recording.incident_feedback/2'
    return result


def attach_failure_analysis(recording_feedback, exported, analysis):
    result = attach_model_feedback(recording_feedback, exported)
    scope = exported['case']['scope']
    fields = {'schema', 'subject_id', 'case_id', 'model_feedback_digest', 'reviews'}
    if (type(analysis) is not dict or set(analysis) != fields
            or analysis['schema'] != 'rosy.incident.failure_analysis/1'
            or analysis['subject_id'] != scope['subject_id'] or analysis['case_id'] != scope['case_id']
            or analysis['model_feedback_digest'] != exported['digest']
            or type(analysis['reviews']) is not list or not 1 <= len(analysis['reviews']) <= 8
            or len(json.dumps(analysis, allow_nan=False).encode()) > 65536):
        raise ValueError('invalid bound failure analysis')
    candidates, seen, human = [], set(), set()
    for review in analysis['reviews']:
        if (type(review) is not dict or set(review) != {'category', 'source', 'author_id', 'at'}
                or type(review['category']) is not str or review['category'] not in FAILURE_OWNERS
                or type(review['source']) is not str or review['source'] not in {'model', 'human'}
                or type(review['author_id']) is not str or not 1 <= len(review['author_id']) <= 128
                or review['author_id'] != review['author_id'].strip() or type(review['at']) is not str
                or len(review['at']) > 64 or datetime.fromisoformat(review['at']).tzinfo is None):
            raise ValueError('invalid named failure proposal or review')
        encoded = json.dumps(review, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        if digest in seen: raise ValueError('duplicate failure review')
        seen.add(digest)
        if review['source'] == 'human': human.add(review['category'])
        candidates.append(dict(category=review['category'], owner=FAILURE_OWNERS[review['category']],
                               source=review['source'], review_digest=digest))
    for row in result['matches']:
        if (row['robot_id'], row['stuck_id']) == (scope['subject_id'], scope['case_id']):
            row['failure_analysis'] = dict(candidates=candidates, label_state='UNREVIEWED',
                review_state='unreviewed' if not human else 'review_candidate' if len(human) == 1 else 'disputed',
                reviewed_category=next(iter(human)) if len(human) == 1 else None)
    result['schema'] = 'rosy.recording.incident_feedback/3'
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incidents", type=Path)
    parser.add_argument("markers", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-feedback", type=Path, help="unreviewed fixed Fleet model feedback export")
    parser.add_argument("--failure-analysis", type=Path, help="bound failure proposals and final review candidates")
    args = parser.parse_args()
    if args.failure_analysis is not None and args.model_feedback is None:
        raise ValueError('failure analysis requires model feedback')
    result = bind(json.loads(args.incidents.read_text(encoding="utf-8-sig")),
                  json.loads(args.markers.read_text(encoding="utf-8-sig")))
    if args.model_feedback is not None:
        with args.model_feedback.open('rb') as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('model feedback file limit exceeded')
        exported = json.loads(raw)
        if args.failure_analysis is None:
            result = attach_model_feedback(result, exported)
        else:
            with args.failure_analysis.open('rb') as source:
                raw = source.read(65537)
            if len(raw) > 65536: raise ValueError('failure analysis file limit exceeded')
            result = attach_failure_analysis(result, exported, json.loads(raw))
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(result['matches'])} matched, {len(result['missing_incidents'])} missing: {args.out}")


if __name__ == "__main__":
    main()
