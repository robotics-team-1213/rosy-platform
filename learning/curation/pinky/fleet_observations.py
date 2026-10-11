"""Export retained Fleet observations as an unlabeled, hashed learning source; never trains or dispatches."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "operations/fleet"))
from fleet.server.core_event_store import MAX_EVENT_BYTES, _contains_sensitive_field  # noqa: E402


def export(database, output, *, robot_id=None):
    database, output = Path(database), Path(output)
    if output.resolve().drive.upper() == "F:":
        raise ValueError("recording output belongs on X:, not the source drive")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--robot-id")
    args = parser.parse_args()
    print(json.dumps(export(args.database, args.output, robot_id=args.robot_id)))


if __name__ == "__main__":
    main()
