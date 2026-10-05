"""Harvest (optional) -> provenance catalog -> autolabel -> build -> train job.

recording_job.py config.json --out <job-dir> [--prepare-only]
Uses completed MCAP sessions or bag_to_video MP4+sidecar, never prediction masks.
No assume-idle, raw deletion, watcher invocation, or actuator command.
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from job_state import Job, JobError, receipt, sha

HERE = Path(__file__).resolve().parent
PERCEPTION = HERE.parent
for path in (PERCEPTION, PERCEPTION / "dataset"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def validate_config(cfg):
    from store import safe_name
    if set(cfg) != {"store", "name", "recordings", "harvest", "label", "trainer"}:
        raise JobError("recording config needs store/name/recordings/harvest/label/trainer")
    if not safe_name(cfg["name"]) or not isinstance(cfg["recordings"], list) or not cfg["recordings"]:
        raise JobError("safe dataset name and nonempty recordings required")
    if not isinstance(cfg["harvest"], list):
        raise JobError("harvest must be a list")
    sessions = []
    for row in cfg["recordings"]:
        if not isinstance(row, dict) or not {"session"} <= row.keys():
            raise JobError("recording session required")
        source_keys = set(row) & {"video", "raw", "harvest"}
        if not safe_name(row["session"]) or len(source_keys) != 1:
            raise JobError("safe session and exactly one video/raw/harvest source required")
        if set(row) - {"session", "video", "raw", "harvest", "pitch_deg"}:
            raise JobError("unknown recording option")
        if "harvest" in row:
            index = row["harvest"]
            if type(index) is not int or not 0 <= index < len(cfg["harvest"]):
                raise JobError("recording harvest index must reference a configured harvest entry")
        if "pitch_deg" in row and (type(row["pitch_deg"]) not in (int, float)
                                   or not math.isfinite(row["pitch_deg"])):
            raise JobError("finite camera pitch required")
        sessions.append(row["session"])
    if len(set(sessions)) != len(sessions):
        raise JobError("duplicate recording session")
    label = cfg["label"]
    if set(label) != {"min_interval", "max_frames", "lidar_yaw_deg"}:
        raise JobError("explicit label min_interval/max_frames/lidar_yaw_deg required")
    if type(label["max_frames"]) is not int or label["max_frames"] < 1:
        raise JobError("positive max_frames required")
    for key in ("min_interval", "lidar_yaw_deg"):
        if type(label[key]) not in (int, float) or not math.isfinite(label[key]):
            raise JobError(f"finite label {key} required")
    if label["min_interval"] <= 0:
        raise JobError("positive frame interval required")
    if set(cfg["trainer"]) != {"gate", "replay_root", "intake_out", "camera_profile", "training"}:
        raise JobError("trainer gate/replay_root/intake_out/camera_profile/training required")
    required = {"host", "core_token_file", "identity", "known_hosts", "dest", "host_key_alias"}
    optional = {"user", "remote_root", "core_url", "timeout", "status_timeout"}
    for h in cfg["harvest"]:
        if not isinstance(h, dict) or not required <= h.keys() or set(h) - required - optional:
            raise JobError("harvest requires pinned SSH, token file and destination; unknown options refused")
        if any(not isinstance(h[k], str) or not h[k] for k in required):
            raise JobError("nonempty harvest paths and identity required")


def files_under(folder):
    return sorted(p for p in Path(folder).rglob("*") if p.is_file())


def execute(argv, log):
    with Path(log).open("w", encoding="utf-8") as stream:
        result = subprocess.run([sys.executable, *map(str, argv)], stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise JobError(f"stage exited {result.returncode}; see {log}")
    return 0


def inputs(cfg):
    scripts = [HERE / "recording_job.py", HERE / "job_state.py"]
    scripts += [PERCEPTION / "dataset" / name for name in
                ("harvest.py", "catalog.py", "autolabel.py", "build.py", "labels.py", "geometry.py")]
    scripts += [PERCEPTION / "store.py", PERCEPTION / "operator_ssh.py"]
    # Child trainer independently hashes its own source and deployment gate.
    return {"config": cfg, "source_files": {p.relative_to(PERCEPTION).as_posix(): sha(p) for p in scripts}}


def evaluation(cfg):
    import yaml
    from store import content_sha
    gate = Path(cfg["trainer"]["gate"])
    doc = yaml.safe_load(gate.read_text(encoding="utf-8"))
    if doc.get("require_eval") is not True or not isinstance(doc.get("eval_set"), str):
        raise JobError("require_eval gate with fixed eval_set required")
    path = (Path(cfg["trainer"]["replay_root"]) / doc["eval_set"]).resolve()
    if content_sha(path) != path.name:
        raise JobError("fixed evaluation hash differs")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("purpose") != "eval" or not manifest.get("frames"):
        raise JobError("nonempty fixed evaluation purpose required")
    heldout = {r["session"] for r in manifest["frames"]}
    overlap = heldout & {r["session"] for r in cfg["recordings"]}
    if overlap:
        raise JobError(f"heldout recording cannot be labelled for training: {sorted(overlap)}")
    return path, gate


def catalog_source(row, out, store):
    import catalog
    if "raw" in row:
        raw = Path(row["raw"]).resolve()
        meta = json.loads((raw / "session.json").read_text(encoding="utf-8"))
        if raw.name != row["session"] or not meta.get("ended_at") or not list((raw / "bag").glob("*.mcap")):
            raise JobError("raw identity, completed session and MCAP required")
        result = catalog.session_row(raw, out, store=Path(store))
        return result, files_under(raw)
    video = Path(row["video"]).resolve()
    sidecar, metadata = video.with_suffix(".jsonl"), video.with_suffix(".json")
    doc = json.loads(metadata.read_text(encoding="utf-8"))
    if doc.get("schema") != "rosy.teleop.video/1" or (doc.get("source") or {}).get("session") != row["session"]:
        raise JobError("video metadata recording identity differs")
    source_files = [video, sidecar, metadata]
    scan = video.with_suffix(".scan.npz")
    if scan.exists():
        source_files.append(scan)
    if doc.get("scan") and not scan.is_file():
        raise JobError("video metadata declares missing LiDAR scan sidecar")
    meta = doc.get("session") or {}
    result = {"schema": catalog.SCHEMA, "session": row["session"], "device": meta.get("device"),
              "reason": meta.get("reason"), "started_at": meta.get("started_at"),
              "ended_at": meta.get("ended_at"), "duration_s": (doc.get("video") or {}).get("duration_s"),
              "topics": (doc.get("source") or {}).get("topics", {}), "raw": None,
              "files": [{"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)} for p in source_files],
              "derived": {"video": [{"video": str(video), "sidecar": str(sidecar), "meta": str(metadata)}],
                          "frames": [], "labels": [], "datasets": []},
              "driver": catalog.infer_driver(meta["reason"]) if meta.get("reason") else None,
              "driver_inferred": bool(meta.get("reason")), "scene_tags": [], "errors": [], "notes": "",
              "has_scan": scan.is_file(), "camera_profile_revision": meta.get("camera_profile_revision")}
    return result, source_files


def resolve_recordings(cfg):
    """Resolve explicit harvest references to one verified local session folder."""
    resolved = []
    for row in cfg["recordings"]:
        if "harvest" not in row:
            resolved.append(row)
            continue
        dest = Path(cfg["harvest"][row["harvest"]]["dest"]).resolve()
        matches = []
        if dest.is_dir():
            for candidate in dest.glob(f"*/{row['session']}"):
                path = candidate.resolve()
                if path.name == row["session"] and path.parent.parent == dest:
                    matches.append(path)
        if len(matches) != 1:
            raise JobError(
                f"harvested session {row['session']!r} resolved to {len(matches)} folders; expected one")
        resolved.append({**row, "raw": str(matches[0])})
        resolved[-1].pop("harvest")
    return resolved


def prepare(cfg, out, *, runner=execute, builder=None):
    import catalog
    from build import build_auto_dataset
    validate_config(cfg)
    evalset, gate = evaluation(cfg)
    out = Path(out).resolve()
    signature = inputs(cfg)
    signature.update(gate_sha=sha(gate), eval_sha=evalset.name)
    builder = builder or build_auto_dataset
    with Job(out, signature) as job:
        for index, h in enumerate(cfg["harvest"]):
            def harvest_stage(attempt, h=h, index=index):
                log = out / f"harvest-{index}-{attempt}.log"
                argv = [PERCEPTION / "dataset/harvest.py", h["host"]]
                for key, value in h.items():
                    if key == "host":
                        continue
                    argv += ["--" + key.replace("_", "-"), str(value)]
                runner(argv, log)
                raw_files = files_under(h["dest"])
                if not raw_files:
                    raise JobError("harvest yielded no verified local source files")
                return receipt({"destination": h["dest"]}, raw_files)
            job.step(f"harvest-{index}", harvest_stage)

        recordings = resolve_recordings(cfg)

        def catalog_stage(attempt):
            rows, raw_files = [], []
            for row in recordings:
                item, paths = catalog_source(row, out, cfg["store"])
                rows.append(item)
                raw_files += paths
            target = out / "catalog-source.jsonl"
            catalog.save(target, rows)
            return receipt({"catalog": str(target)}, [target, *raw_files])
        original = job.step("catalog", catalog_stage)
        labelled = []
        for index, row in enumerate(recordings):
            def label_stage(attempt, row=row, index=index):
                target = out / f"labels-{index}-{attempt}" / row["session"]
                argv = [PERCEPTION / "dataset/autolabel.py"]
                argv += ([Path(row["raw"])] if "raw" in row else ["--video", Path(row["video"])])
                argv += ["--out", target]
                for key, value in cfg["label"].items():
                    argv += ["--" + key.replace("_", "-"), str(value)]
                if "pitch_deg" in row:
                    argv += ["--pitch-deg", str(row["pitch_deg"])]
                runner(argv, out / f"label-{index}-{attempt}.log")
                if not (target / "meta.json").is_file() or not (target / "labels.jsonl").is_file():
                    raise JobError("labeller did not complete metadata and labels")
                return receipt({"folder": str(target)}, files_under(target))
            labelled.append(job.step(f"label-{index}", label_stage)["folder"])
            # Detect a source changed by another process during the label invocation.
            job.step("catalog", catalog_stage)

        def build_stage(attempt):
            doc, folder = builder(list(map(Path, labelled)), cfg["store"], cfg["name"],
                                  exclude_eval=[evalset])
            from store import content_sha
            if content_sha(folder) != folder.name:
                raise JobError("built dataset hash differs")
            rows = catalog.load(Path(original["catalog"]))
            for row, label in zip(rows, labelled):
                row["derived"]["labels"] = [{"path": label, "labels_sha256": sha(Path(label) / "labels.jsonl")}]
                splits = sorted({f["split"] for f in doc["frames"] if f["session"] == row["session"]})
                row["derived"]["datasets"] = [{"name": cfg["name"], "version": folder.name, "split": splits}]
            target = out / "catalog-curated.jsonl"
            catalog.save(target, rows)
            trainer = {**cfg["trainer"], "store": cfg["store"], "dataset": cfg["name"] + "@" + folder.name}
            training_config = out / "training-config.json"
            training_config.write_text(json.dumps(trainer, indent=2), encoding="utf-8")
            return receipt({"dataset": trainer["dataset"], "catalog": str(target),
                            "training_config": str(training_config)},
                           [target, training_config, *files_under(folder)])
        return job.step("build", build_stage)


def run(cfg, out):
    import train_job
    prepared = prepare(cfg, out)
    trainer = json.loads(Path(prepared["training_config"]).read_text(encoding="utf-8"))
    evalset, gate = evaluation(cfg)
    signature = inputs(cfg)
    signature.update(gate_sha=sha(gate), eval_sha=evalset.name)
    with Job(out, signature) as job:
        called = False

        def model_stage(attempt):
            nonlocal called
            called = True
            result = train_job.run(trainer, Path(out) / "model-job")
            return receipt(result, [prepared["training_config"]])

        result = job.step("model", model_stage)
        if not called:
            # Child checks its own source, output hashes and watcher moves on every resume.
            current = train_job.run(trainer, Path(out) / "model-job")
            if current["revision"] != result["revision"]:
                raise JobError("child model revision changed")
            result.update(current)
        job.finish()
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        result = prepare(cfg, args.out) if args.prepare_only else run(cfg, args.out)
        print(json.dumps(result))
        return 0
    except (JobError, OSError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
