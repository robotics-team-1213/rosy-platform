"""Export retained Fleet observations as an unlabeled, hashed learning source; never trains or dispatches."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import re
import math
from contextlib import closing

MAX_EVENT_BYTES = 64 * 1024
_SENSITIVE_FIELD = re.compile(
    r"(?:passwo?rd|passwd|psk|passphrase|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|bearer)", re.IGNORECASE)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")


def _in_checkout(path) -> bool:
    """True inside a git working tree: artifacts stay out of source checkouts, on any drive."""
    path = Path(path).resolve()
    return any((p / '.git').exists() for p in (path, *path.parents))


def _contains_sensitive_field(value):
    if isinstance(value, dict):
        return any(_SENSITIVE_FIELD.search(str(key)) or _contains_sensitive_field(child)
                   for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_sensitive_field(child) for child in value)
    return isinstance(value, str) and bool(_PRIVATE_KEY.search(value))


def export(database, output, *, robot_id=None):
    database, output = Path(database), Path(output)
    if _in_checkout(output):
        raise ValueError("recording output belongs outside the source checkout")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")  # One read snapshot, even while Fleet prunes or appends.
        query = "SELECT observation_id, robot_id, received_at, payload_json FROM fleet_observations"
        args = ()
        if robot_id is not None:
            query += " WHERE robot_id=?"
            args = (robot_id,)
        cursor = connection.execute(query + " ORDER BY observation_id", args)
        output.mkdir(parents=True, exist_ok=False)
        digest, count, first, last = hashlib.sha256(), 0, None, None
        with (output / "observations.jsonl").open("xb") as stream:
            for oid, rid, received, payload in cursor:
                body = json.loads(payload)
                if (len(payload.encode("utf-8")) > MAX_EVENT_BYTES or _contains_sensitive_field(body)
                        or body.get("robot_id") != rid or type(body.get("online")) is not bool
                        or json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False) != payload):
                    raise ValueError("observation source failed validation")
                item = dict(observation_id=oid, robot_id=rid, received_at=received, observation=body,
                            sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest())
                encoded = (json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
                stream.write(encoded)
                digest.update(encoded)
                count, first, last = count + 1, oid if first is None else first, oid
            stream.flush()
            os.fsync(stream.fileno())
        manifest = dict(schema="rosy.fleet-observations/1", file="observations.jsonl", rows=count,
                        sha256=digest.hexdigest(), first_cursor=first, last_cursor=last,
                        robot_id=robot_id, verification="retained_observations_only",
                        train_eligible=False, labels=None, action_outcome="not_inferred",
                        clock="fleet_receive_epoch", raw_media="separate_device_recording")
        # Manifest is published last; an interrupted directory is incomplete and never an eligible dataset.
        with (output / "manifest.json").open("xb") as stream:
            stream.write((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        return verify(output)
    finally:
        connection.close()


def verify(output):
    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    if (manifest.get("schema") != "rosy.fleet-observations/1" or manifest.get("file") != "observations.jsonl"
            or manifest.get("train_eligible") is not False or manifest.get("labels") is not None):
        raise ValueError("unlabeled Fleet source manifest is invalid")
    digest, count = hashlib.sha256(), 0
    with (output / "observations.jsonl").open("rb") as stream:
        for line in stream:
            digest.update(line)
            item = json.loads(line)
            payload = json.dumps(item["observation"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if (_contains_sensitive_field(item) or item["sha256"] != hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    or item["robot_id"] != item["observation"]["robot_id"]):
                raise ValueError("observation content or lineage changed")
            count += 1
    if count != manifest["rows"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("Fleet observation export hash or row count changed")
    return manifest


def capture_window(database, *, robot_id, start, end, max_gap_s, max_rows=4096):
    """Validate retained append coverage; command, sensor and model coverage are separate."""
    finite = lambda v: type(v) in (int, float) and math.isfinite(v)
    if (type(robot_id) is not str or not robot_id or not all(map(finite, (start, end, max_gap_s)))
            or start >= end or end - start > 86400 or max_gap_s <= 0
            or type(max_rows) is not int or not 1 <= max_rows <= 4096):
        raise ValueError('window requires a subject, finite ordered <=24h bounds and positive gap')
    result = dict(schema='rosy.fleet-observation-window/1', robot_id=robot_id,
                  start=start, end=end, max_gap_s=max_gap_s, state='HOLD', reasons=[],
                  capture_complete=False, rows=[], verification='retained_capture_only',
                  field_accepted=False, train_eligible=False, labels=None,
                  normal_commands=None, model_calls=None, recurrence=None)

    def hold(reason):
        result['reasons'].append(reason)
        return result

    # Read the live WAL correctly; SQLite immutable=1 would miss uncheckpointed records.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        # A wall clock regression makes epoch-based selection ambiguous, even outside the requested bounds.
        if db.execute('''SELECT 1 FROM (SELECT received_at,
                LAG(received_at) OVER (ORDER BY observation_id) AS previous
                FROM fleet_observations) WHERE received_at < previous LIMIT 1''').fetchone():
            return hold('CLOCK_REGRESSION')
        left = db.execute('SELECT MAX(received_at) FROM fleet_observations WHERE received_at<=?',
                          (start,)).fetchone()[0]
        right = db.execute('SELECT MIN(received_at) FROM fleet_observations WHERE received_at>=?',
                           (end,)).fetchone()[0]
        if left is None or right is None:
            return hold('MISSING_BOUNDARY')
        # Include every row of the boundary captures; never filter the requested robot first.
        bounds = db.execute('''SELECT MIN(observation_id), MAX(observation_id)
                FROM fleet_observations WHERE received_at>=? AND received_at<=?''', (left, right)).fetchone()
        rows = db.execute('''SELECT observation_id,robot_id,received_at,
                CASE WHEN length(CAST(payload_json AS BLOB))<=65536 THEN payload_json ELSE NULL END
                FROM fleet_observations WHERE observation_id BETWEEN ? AND ?
                ORDER BY observation_id LIMIT ?''', (*bounds, max_rows + 1)).fetchall()
    if len(rows) > max_rows:
        return hold('ROW_LIMIT')
    groups, previous, identities, stamp = [], None, [], None
    for oid, rid, received, payload in rows:
        if type(payload) is not str:
            raise ValueError('observation source failed validation')
        try:
            body = json.loads(payload)
            valid = (type(body) is dict and len(payload.encode('utf-8')) <= MAX_EVENT_BYTES
                     and not _contains_sensitive_field(body) and body.get('robot_id') == rid
                     and body.get('received_at') == received and finite(received)
                     and type(body.get('online')) is bool
                     and body.get('clock') == 'fleet_receive_epoch'
                     and body.get('verification') == 'observed_not_labeled'
                     and json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False) == payload)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError('observation source failed validation') from exc
        if not valid:
            raise ValueError('observation source failed validation')
        capture = body.get('capture')
        if capture is None:
            return hold('LEGACY_CAPTURE')
        if (type(capture) is not dict or set(capture) != {'run_id', 'sequence', 'monotonic_at', 'robot_ids'}
                or type(capture['run_id']) is not str or not re.fullmatch('[0-9a-f]{32}', capture['run_id'])
                or type(capture['sequence']) is not int or capture['sequence'] < 1
                or not finite(capture['monotonic_at']) or type(capture['robot_ids']) is not list
                or not 1 <= len(capture['robot_ids']) <= 1024
                or any(type(v) is not str or not v for v in capture['robot_ids'])
                or capture['robot_ids'] != sorted(set(capture['robot_ids']))):
            return hold('INVALID_CAPTURE')
        key = (capture['run_id'], capture['sequence'])
        if previous is not None and key == (previous['run_id'], previous['sequence']):
            if capture != previous or received != stamp:
                return hold('INCONSISTENT_CAPTURE')
        else:
            if previous is not None:
                if sorted(identities) != previous['robot_ids']:
                    return hold('INCOMPLETE_ROSTER')
                if capture['run_id'] != previous['run_id']:
                    return hold('PRODUCER_RESTART')
                if capture['sequence'] != previous['sequence'] + 1:
                    return hold('CAPTURE_GAP')
                delta = capture['monotonic_at'] - previous['monotonic_at']
                if delta <= 0 or delta > max_gap_s or received - stamp > max_gap_s:
                    return hold('CLOCK_OR_CADENCE_GAP')
            if robot_id not in capture['robot_ids']:
                return hold('SUBJECT_ABSENT')
            groups.append(capture)
            previous, identities, stamp = capture, [], received
        identities.append(rid)
        result['rows'].append(dict(observation_id=oid, sha256=hashlib.sha256(payload.encode('utf-8')).hexdigest()))
    if previous is None or sorted(identities) != previous['robot_ids']:
        return hold('INCOMPLETE_ROSTER')
    result.update(state='UNREVIEWED', capture_complete=True, run_id=previous['run_id'],
                  first_sequence=groups[0]['sequence'], last_sequence=previous['sequence'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--robot-id")
    parser.add_argument('--window', action='store_true', help='Validate retained capture coverage only')
    parser.add_argument('--start', type=float)
    parser.add_argument('--end', type=float)
    parser.add_argument('--max-gap-s', type=float)
    args = parser.parse_args()
    if args.window:
        if _in_checkout(args.output):
            raise ValueError('recording output belongs outside the source checkout')
        result = capture_window(args.database, robot_id=args.robot_id, start=args.start,
                                end=args.end, max_gap_s=args.max_gap_s)
        with args.output.open('xb') as stream:
            stream.write((json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
    else:
        if any(v is not None for v in (args.start, args.end, args.max_gap_s)):
            parser.error('window bounds require --window')
        result = export(args.database, args.output, robot_id=args.robot_id)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
