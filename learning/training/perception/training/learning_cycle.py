"""Producer-side repeating research training; never delivers or activates a robot.

learning_cycle.py config.json --out STATE [--once]
Requests: immutable JSON files {dataset: name@sha, purpose: research}.
Review exports are progress evidence, not qualification for segmentation training.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import time

from job_state import Job, JobError, Rejected, sha

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from store import Store, content_sha, parse_dataset_ref  # noqa: E402


def _request_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise JobError('duplicate request key')
        result[key] = value
    return result


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def verified_export(folder):
    """Verify every receiver byte before counting explicit frame decisions."""
    folder = Path(folder)
    raw = (folder / "manifest.json").read_bytes()
    if (folder / "COMPLETE").read_text().strip() != hashlib.sha256(raw).hexdigest():
        raise JobError("review COMPLETE digest differs")
    doc = json.loads(raw)
    if doc.get("schema") != "rosy.object-review-return/1":
        raise JobError("unsupported review receiver schema")
    for item in doc["files"]:
        rel = item["path"]
        p, windows = PurePosixPath(rel), PureWindowsPath(rel)
        if p.is_absolute() or windows.drive or ".." in p.parts or "\\" in rel:
            raise JobError("review file escapes export")
        path = folder / p
        if (not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink()
                or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]):
            raise JobError("review file integrity differs")
    human = folder / "inputs/human.jsonl"
    if sha(human) != doc["human_sha256"]:
        raise JobError("review human provenance differs")
    source = folder / "inputs/source.jsonl"
    if sha(source) != doc["source_sha256"]:
        raise JobError("review source provenance differs")
    originals = {r["index"]: r for r in map(json.loads, source.read_text().splitlines())}
    rows = [json.loads(line) for line in human.read_text().splitlines() if line.strip()]
    if len({r["index"] for r in rows}) != len(rows):
        raise JobError("duplicate human review index")
    for row in rows:
        original = originals[row["index"]]
        if any(row.get(k) != original.get(k) for k in ("image_sha256", "video", "video_frame")):
            raise JobError("review frame identity differs")
        snapshots = list((folder / "inputs/images").glob(f'{row["index"]:06d}.*'))
        if len(snapshots) != 1 or sha(snapshots[0]) != row["image_sha256"]:
            raise JobError("review image provenance differs")
    approved = [r for r in rows if r.get("review_status") == "approved"
                and r.get("complete_frame_review") is True]
    if any(r.get("disposition") == "excluded_by_user" for r in approved):
        raise JobError("excluded frame cannot be approved")
    if len(approved) != doc["exported_frames"]:
        raise JobError("review approved count differs")
    return {"manifest_sha": hashlib.sha256(raw).hexdigest(), "frames": rows,
            "training_dataset_qualified": False}


def validate_config(config):
    expected = {"trainer", "recipes", "requests_dir", "reviews_dir", "interval_s", "max_attempts"}
    if set(config) - {"authority"} != expected or not isinstance(config["trainer"], dict):
        raise JobError("cycle needs trainer/recipes/requests_dir/reviews_dir/interval_s/max_attempts")
    if type(config["interval_s"]) is not int or config["interval_s"] < 1:
        raise JobError("positive interval_s required")
    if type(config["max_attempts"]) is not int or config["max_attempts"] < 1:
        raise JobError("positive max_attempts required")
    if not isinstance(config["recipes"], list) or not config["recipes"]:
        raise JobError("nonempty recipes required")
    if len({signature(r) for r in config["recipes"]}) != len(config["recipes"]):
        raise JobError("duplicate recipe")
    authority = config.get("authority")
    if authority is not None and (not isinstance(authority, dict)
            or set(authority) != {"path", "workspace_id", "max_age_s"}
            or type(authority["max_age_s"]) is not int or not 1 <= authority["max_age_s"] <= 3600):
        raise JobError("authority path/workspace_id/bounded max_age_s required")


def validate_request(request, trainer):
    if set(request) != {"dataset", "purpose"} or request["purpose"] != "research":
        raise JobError("explicit research dataset request required; box export is not a dataset")
    store = Store(trainer["store"])
    dataset = store.dataset_path(*parse_dataset_ref(request["dataset"]))
    if content_sha(dataset) != dataset.name:
        raise JobError("dataset content hash differs")
    doc = json.loads((dataset / "manifest.json").read_text())
    if doc.get("schema") != "rosy.perception.dataset/1" or doc.get("purpose") == "eval":
        raise JobError("training dataset schema/purpose required")
    frames = doc["frames"]
    train = {f["session"] for f in frames if f["split"] == "train"}
    val = {f["session"] for f in frames if f["split"] == "val"}
    if not train or not val or train & val:
        raise JobError("disjoint nonempty train/val sessions required")
    sessions = train | val
    reservations = store.eval_reservations()
    if sessions & reservations.keys():
        raise JobError("training overlaps a reserved eval session")
    groups = {row.get("capture_group") for row in frames if row.get("capture_group")}
    grouped_sessions = {row["session"] for row in frames if row.get("capture_group")}
    sources_for_groups = doc.get("sources", [])
    if isinstance(sources_for_groups, list):
        for row in sources_for_groups:
            if isinstance(row, dict) and row.get("capture_group"):
                groups.add(row["capture_group"])
                grouped_sessions.add(row.get("session"))
    if groups & set(reservations.values()):
        raise JobError("training overlaps a reserved eval capture group")
    if reservations and sessions - grouped_sessions:
        raise JobError("reserved eval capture group cannot be excluded: training source group unknown")
    for name, versions in store.evalsets().items():
        for version in versions:
            path = store.evalset_path(name, version)
            if content_sha(path) != version:
                raise JobError("fixed eval content hash differs")
            evaluation = json.loads((path / "manifest.json").read_text())
            if sessions & {f["session"] for f in evaluation["frames"]}:
                raise JobError("training overlaps a fixed eval session")
    sources = doc.get('sources', [])
    sources = sources if isinstance(sources, list) else [sources]
    indexed = (doc.get('builder') == 'review_dataset.py (D-464)'
               or any(isinstance(row, dict) and row.get('annotation_origin') == 'human_reviewed_pinky_indexed'
                      for row in sources))
    return {"frames": len(frames), "train_sessions": sorted(train), "val_sessions": sorted(val),
            "indexed_review": indexed}


def review_queue(exports):
    """Do not infer revision order from immutable export names or arrival times."""
    frames = {}
    for export in exports:
        for row in export["frames"]:
            identity = {key: row[key] for key in ("video", "video_frame", "image_sha256")}
            frame = frames.setdefault(signature(identity), {"identity": identity,
                                                            "exports": set(), "variants": {}})
            frame["exports"].add(export["manifest_sha"])
            # Index is local to an export, not the original frame identity.
            decision = {key: value for key, value in row.items() if key != "index"}
            frame["variants"][signature(decision)] = decision
    return [{"frame_id": key, "identity": frame["identity"],
             "exports": sorted(frame["exports"]), "variants": len(frame["variants"]),
             "status": "agreed" if len(frame["variants"]) == 1 else "conflict",
             "decision": next(iter(frame["variants"].values()))
                         if len(frame["variants"]) == 1 else None,
             "training_dataset_qualified": False}
            for key, frame in sorted(frames.items())]


def current_authority(config, job):
    """A transport receipt is usable only while its independent fetch remains fresh."""
    from review_authority import advance_revision
    cfg = config["authority"]
    previous = job.state.get("current_authority", {}).get("revision")
    try:
        path = Path(cfg["path"])
        if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
            raise JobError("invalid current authority delivery file")
        delivery = json.loads(path.read_bytes())
        stamp = delivery.get("checked_at_unix")
        if (delivery.get("schema") != "rosy.pinky-review-current-delivery/1"
                or delivery.get("workspace_id") != cfg["workspace_id"]
                or delivery.get("available") is not True
                or type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not -5 <= time.time() - stamp <= cfg["max_age_s"]):
            raise JobError("current authority unavailable, expired or from another workspace")
        current = delivery["authority"]
        revision = advance_revision(current, workspace_id=cfg["workspace_id"], previous=previous)
        job.state["current_authority"] = {"status": "verified", "revision": revision,
                                          "checked_at_unix": stamp}
        return current
    except (OSError, ValueError, KeyError, TypeError) as error:
        job.state["current_authority"] = {"status": "unavailable", "revision": previous,
                                          "error": str(error)}
        return None


def scan_reviews(config, job):
    root = Path(config["reviews_dir"])
    progress = job.state.setdefault("reviews", {})
    current, seen, authority_rows = [], set(), {}
    authority = current_authority(config, job) if config.get("authority") is not None else None
    for folder in sorted(root.glob("*")):
        if folder.name.startswith(".") or not folder.is_dir() or not (folder / "COMPLETE").is_file():
            continue
        try:
            seen.add(str(folder))
            row = verified_export(folder)
            if (folder / "review-contract.json").exists() or (folder / "AUTHORITY_COMPLETE").exists():
                if authority is None:
                    raise JobError("current authority required for v2 review export")
                from review_authority import verify_bundle
                try:
                    verified = verify_bundle(folder, authority,
                                             workspace_id=config["authority"]["workspace_id"])
                except ValueError as error:
                    progress[str(folder)] = {"status": "stale", "error": str(error)}
                    continue
                contract = verified["contract"]
                for decision in contract["authority"]["frames"]:
                    authority_rows[decision["review_uid"]] = dict(
                        decision, training_dataset_qualified=False)
                progress[str(folder)] = {"status": "verified", "contract_sha": verified["contract_sha"],
                                         "workspace_id": authority["workspace_id"],
                                         "generation": authority["generation"],
                                         "training_dataset_qualified": False}
                continue
            progress[str(folder)] = {"status": "verified", **row}
            current.append(row)
        except (OSError, ValueError, KeyError) as error:
            progress[str(folder)] = {"status": "invalid", "error": str(error)}
    for path in progress.keys() - seen:
        progress[path]["status"] = "unavailable"
    job.state["review_queue"] = review_queue(current)
    if authority_rows:
        final_authority = current_authority(config, job)
        if final_authority != authority:
            authority_rows.clear()  # Long verification cannot extend an expired or replaced decision snapshot.
    job.state["authority_queue"] = [authority_rows[key] for key in sorted(authority_rows)]
    # Persist full per-frame decisions, including pending and excluded, before training.
    job._save()


def run_once(config, out, *, trainer_fn=None, review_pipeline=None):
    validate_config(config)
    if review_pipeline is not None:
        from review_pipeline import ReviewPipeline
        if type(review_pipeline) is not ReviewPipeline:
            raise JobError('trusted owner review pipeline required')
        review_pipeline.check_settings()
    out = Path(out).resolve()
    if trainer_fn is None:
        from train_job import run as trainer_fn
    inputs = config if review_pipeline is None else dict(config, owner_review_pipeline=review_pipeline.signature)
    with Job(out, inputs) as job:
        scan_reviews(config, job)
        if review_pipeline is not None:
            review_pipeline.prepare(config, job)
        cycles = job.state.setdefault("cycles", {})
        requests = job.state.setdefault("requests", {})
        for path in sorted(Path(config["requests_dir"]).glob("*.json")):
            digest = None
            try:
                from review_dataset import _stable_bytes
                raw = _stable_bytes(path)
                if len(raw) > 1024 * 1024:
                    raise JobError('research request too large')
                digest = hashlib.sha256(raw).hexdigest()
                prior = requests.get(str(path))
                if prior and prior["sha256"] != digest:
                    raise JobError("processed request changed; use a new request path")
                request = json.loads(raw, object_pairs_hook=_request_pairs)
                evidence = validate_request(request, config["trainer"])
                indexed_context = None
                if evidence['indexed_review']:
                    if review_pipeline is None:
                        raise JobError('indexed request needs owner review pipeline')
                    indexed_context = review_pipeline.for_dataset(config, job, request['dataset'])
                requests[str(path)] = {"sha256": digest, "status": "validated", **evidence}
                job._save()
            except (OSError, ValueError, KeyError) as error:
                if str(path) not in requests:
                    requests[str(path)] = {"sha256": digest}
                requests[str(path)].update(status="blocked", error=str(error))
                job._save()
                continue
            for recipe in config["recipes"]:
                cfg = {**config["trainer"], "dataset": request["dataset"], "training": recipe}
                key = (signature(cfg) if indexed_context is None else
                       review_pipeline.cycle_key(config,job,request['dataset'],recipe))
                row = cycles.setdefault(key, {"dataset": request["dataset"], "recipe": recipe,
                                               "attempts": 0, "status": "pending"})
                if row["status"] in ("ready", "candidate", "rejected", "gave_up"):
                    continue
                if row["attempts"] >= config["max_attempts"]:
                    row.update(status="gave_up", error="interrupted attempt limit reached")
                    job._save()
                    continue
                row.update(status="running", attempts=row["attempts"] + 1)
                row['dataset'] = request['dataset']
                job._save()
                try:
                    if indexed_context is None:
                        result = trainer_fn(cfg, out / "jobs" / key)
                    else:
                        # Byte provenance may advance while logical GT remains
                        # identical. Keep the shared attempt budget but never
                        # reuse a Job directory for different immutable inputs.
                        result = trainer_fn(cfg, out / "jobs" / key / signature(cfg), indexed_review=indexed_context)
                    if recipe.get("recipe") == "drivable_head":
                        if result.get("status") != "candidate":
                            raise JobError("drivable_head must return a candidate, never READY")
                        row.update(status="candidate", result=result)
                    else:
                        if result.get("status") == "candidate":
                            raise JobError("only drivable_head may return a candidate")
                        row.update(status="ready", result=result)
                except Rejected as error:
                    row.update(status="rejected", error=str(error))
                except Exception as error:
                    row.update(status="gave_up" if row["attempts"] >= config["max_attempts"]
                               else "retry", error=f"{type(error).__name__}: {error}")
                job._save()
        return json.loads(job.path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--out", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    while True:
        result = run_once(config, args.out)
        print(json.dumps({"cycles": {k: v["status"] for k, v in result.get("cycles", {}).items()},
                          "requests": result.get("requests", {}),
                          "reviews": {k: v["status"] for k, v in result.get("reviews", {}).items()}}),
              flush=True)
        if args.once:
            return
        time.sleep(config["interval_s"])


if __name__ == "__main__":
    main()
