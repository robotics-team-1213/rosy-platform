"""Producer-side repeating research training; never delivers or activates a robot.

learning_cycle.py config.json --out STATE [--once]
Requests: immutable JSON files {dataset: name@sha, purpose: research}.
Review exports are progress evidence, not qualification for segmentation training.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import time

from job_state import Job, JobError, Rejected, sha

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from store import Store, content_sha, parse_dataset_ref  # noqa: E402


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
    if set(config) != expected or not isinstance(config["trainer"], dict):
        raise JobError("cycle needs trainer/recipes/requests_dir/reviews_dir/interval_s/max_attempts")
    if type(config["interval_s"]) is not int or config["interval_s"] < 1:
        raise JobError("positive interval_s required")
    if type(config["max_attempts"]) is not int or config["max_attempts"] < 1:
        raise JobError("positive max_attempts required")
    if not isinstance(config["recipes"], list) or not config["recipes"]:
        raise JobError("nonempty recipes required")
    if len({signature(r) for r in config["recipes"]}) != len(config["recipes"]):
        raise JobError("duplicate recipe")


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
    for name, versions in store.evalsets().items():
        for version in versions:
            path = store.evalset_path(name, version)
            if content_sha(path) != version:
                raise JobError("fixed eval content hash differs")
            evaluation = json.loads((path / "manifest.json").read_text())
            if sessions & {f["session"] for f in evaluation["frames"]}:
                raise JobError("training overlaps a fixed eval session")
    return {"frames": len(frames), "train_sessions": sorted(train), "val_sessions": sorted(val)}


def scan_reviews(config, job):
    root = Path(config["reviews_dir"])
    progress = job.state.setdefault("reviews", {})
    for folder in sorted(root.glob("*")):
        if folder.name.startswith(".") or not folder.is_dir() or not (folder / "COMPLETE").is_file():
            continue
        try:
            row = verified_export(folder)
            progress[str(folder)] = {"status": "verified", **row}
        except (OSError, ValueError, KeyError) as error:
            progress[str(folder)] = {"status": "invalid", "error": str(error)}
    # Persist full per-frame decisions, including pending and excluded, before training.
    job._save()


def run_once(config, out, *, trainer_fn=None):
    validate_config(config)
    out = Path(out).resolve()
    if trainer_fn is None:
        from train_job import run as trainer_fn
    with Job(out, config) as job:
        scan_reviews(config, job)
        cycles = job.state.setdefault("cycles", {})
        requests = job.state.setdefault("requests", {})
        for path in sorted(Path(config["requests_dir"]).glob("*.json")):
            digest = None
            try:
                digest = sha(path)
                prior = requests.get(str(path))
                if prior and prior["sha256"] != digest:
                    raise JobError("processed request changed; use a new request path")
                request = json.loads(path.read_text())
                evidence = validate_request(request, config["trainer"])
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
                key = signature(cfg)
                row = cycles.setdefault(key, {"dataset": request["dataset"], "recipe": recipe,
                                               "attempts": 0, "status": "pending"})
                if row["status"] in ("ready", "rejected", "gave_up"):
                    continue
                if row["attempts"] >= config["max_attempts"]:
                    row.update(status="gave_up", error="interrupted attempt limit reached")
                    job._save()
                    continue
                row.update(status="running", attempts=row["attempts"] + 1)
                job._save()
                try:
                    result = trainer_fn(cfg, out / "jobs" / key)
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
