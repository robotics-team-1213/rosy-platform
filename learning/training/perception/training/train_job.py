"""Stored dataset -> GPU train -> ONNX -> strict intake -> canonical READY.

The drivable_head recipe (owner-injected IndexedReview, or a D-554 lane-derived dataset
whose hashes are re-verified at every boundary) exports a candidate only; it never
calls intake, READY publication, or device delivery.

Usage: train_job.py config.json --out <new-or-resumable-job-dir>
Config: store, dataset ('name@sha'), gate, replay_root, intake_out, camera_profile (provenance JSON),
training {seed, epochs, lr, batch_size, base, recipe: baseline|enhanced}, or
drivable_head with parent_model, parent_torchscript and ignore_top.
No device command or watcher invocation. Upstream harvest/curation remains separate.
"""
import argparse
from contextlib import contextmanager, ExitStack
import json
import hashlib
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

from job_state import Job, JobError, Rejected, receipt, sha

HERE = Path(__file__).resolve().parent
PERCEPTION = HERE.parent
ROOT = HERE.parents[3]
for path in (PERCEPTION, PERCEPTION / "model", PERCEPTION / "dataset", ROOT / "middleware/perception",
             ROOT / "contracts/foundation"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def check_coverage(classes, train_counts, val_counts):
    if not len(classes) == len(train_counts) == len(val_counts):
        raise JobError("class/pixel count lengths differ")
    missing = [c["name"] for c, t, v in zip(classes, train_counts, val_counts) if v > 0 and t == 0]
    if missing:
        raise JobError(f"validation classes missing in training: {missing}")
    return [c["name"] for c, t, v in zip(classes, train_counts, val_counts) if t == v == 0]


def validate_drivable_parent(folder, torchscript, dataset_classes):
    """Bind real parent bytes and output order before a drivable candidate can train."""
    from control.sensing.perception.learned.manifest import ManifestError, load_manifest
    from review_provenance import _stable_bytes

    folder, torchscript = Path(folder).absolute(), Path(torchscript).absolute()
    try:
        manifest_path = folder / "model_manifest.json"
        manifest_raw = _stable_bytes(manifest_path)
        model = load_manifest(manifest_path)
        if (model.task != "lane_seg" or model.backend != "onnx"
                or not model.model_revision.startswith("lane-seg-")
                or model.input.shape != (1, 3, 240, 320)):
            raise JobError("parent must be a fixed-size lane-seg ONNX model")
        onnx = model.onnx_file("fp32")
        files = [manifest_path, *(folder / item.name for item in model.files), torchscript]
        contents = {path: _stable_bytes(path) for path in files}
        for item in model.files:
            if hashlib.sha256(contents[folder / item.name]).hexdigest() != item.sha256:
                raise JobError(f"parent {item.name} sha256 differs from manifest")
        if contents[manifest_path] != manifest_path.read_bytes():
            raise JobError("parent manifest changed during validation")
    except (ManifestError, OSError, ValueError) as exc:
        raise JobError(f"drivable parent invalid: {exc}") from exc
    expected = [(c.index, c.name, c.role) for c in model.classes]
    actual = [(c["index"], c["name"], c["role"]) for c in dataset_classes]
    if (not expected or expected[0][2] != "background"
            or any(role == "drivable" for _, _, role in expected)
            or len(actual) != len(expected) + 1
            or actual[:-1] != expected
            or actual[-1][0] != len(expected) or actual[-1][2] != "drivable"):
        raise JobError("drivable dataset class order must match parent plus one final drivable class")
    return {"lineage": {"model_revision": model.model_revision,
                        "onnx_sha256": hashlib.sha256(contents[onnx]).hexdigest(),
                        "torchscript_sha256": hashlib.sha256(contents[torchscript]).hexdigest()},
            "onnx": onnx, "torchscript": torchscript,
            "files": files, "hashes": {path: hashlib.sha256(raw).hexdigest()
                                       for path, raw in contents.items()},
            "input": {"color": model.input.color, "scale": model.input.scale,
                      "mean": model.input.mean, "std": model.input.std}}


def snapshot_intake(artifact, report):
    """Freeze this job's own proof; the shared champion folder is allowed to change."""
    artifact = Path(artifact)
    proof = artifact / "intake_report.json"
    proof.write_text(json.dumps(report, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt({"artifact": str(artifact)}, [proof])


def publish_ready(folder, store_root, job_name, *, before_ready=None):
    """Recover our partial copy or a watcher move; never overwrite different content."""
    import handover
    from store import (Store, content_sha, safe_name, publication_group,
                       publication_directory, shared_publication_permissions, refuse_publication_links)
    from control.sensing.perception.learned.manifest import load_manifest, verify_files
    folder = Path(folder)
    manifest = load_manifest(folder)
    verify_files(manifest)
    report = json.loads((folder / "intake_report.json").read_text())
    if report.get("verdict") != "pass" or report.get("model_revision") != manifest.model_revision:
        raise Rejected("passing intake report required before READY")
    if report.get("files") != [{"name": f.name, "sha256": f.sha256} for f in manifest.files]:
        raise JobError("intake files differ from manifest")
    if not safe_name(job_name):
        raise JobError("job directory basename must be a safe store name")
    store = Store(store_root)
    group = publication_group(store.root)
    if group is not None:
        refuse_publication_links(folder)
    store.ensure_layout()
    revision, names = handover._files(folder)
    target = store.inbox / f"{revision}__{job_name}"
    if (store.rejected / target.name).exists():
        raise Rejected("watcher rejected this candidate; use a new job")
    for location in (store.accepted / revision,):
        if location.is_dir():
            if all((location / name).is_file() and sha(location / name) == sha(folder / name)
                   for name in names):
                if before_ready is not None:
                    before_ready()
                return location
            raise JobError("existing store revision has different content")
    publication_directory(target)
    refuse_publication_links(target)
    allowed = {*names, *(name + ".part" for name in names), "READY"}
    if any(p.name not in allowed or not p.is_file() for p in target.iterdir()):
        raise JobError("existing inbox has unexpected content")
    for name in names:
        dest = target / name
        if dest.exists():
            if sha(dest) != sha(folder / name):
                raise JobError("existing inbox file differs; use a new job")
            continue
        part = target / (name + ".part")
        if part.exists():
            part.unlink()  # recover only a checked regular partial file
        with (folder / name).open('rb') as source, part.open('xb') as destination:
            shutil.copyfileobj(source, destination)
        if sha(part) != sha(folder / name):
            raise JobError("copy hash differs")
        os.replace(part, dest)
    ready = target / "READY"
    digest = content_sha(target)
    if ready.exists():
        if ready.read_text().strip() != digest:
            raise JobError("existing READY digest differs")
        if before_ready is not None:
            before_ready()
    else:
        shared_publication_permissions(target, group)
        if before_ready is not None:
            before_ready()
        ready.write_text(digest, encoding="utf-8")  # always last
    if group is not None:
        ready.chmod(0o640)  # recover interruption after READY write, before chmod
    return target


@contextmanager
def gpu_lease():
    """Serialize cooperative trainers and refuse existing GPU users, including Isaac."""
    if os.name == "nt":
        raise JobError("GPU job runs on the Linux model PC")
    import fcntl
    path = Path.home() / ".cache/rosy-learning/gpu.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobError("another learning GPU job is running") from exc
        output = subprocess.run(["nvidia-smi", "--query-compute-apps=pid",
                                 "--format=csv,noheader,nounits"], check=True,
                                capture_output=True, text=True).stdout
        if any(line.strip() != str(os.getpid()) for line in output.splitlines() if line.strip()):
            raise JobError("GPU already has another process; do not overlap training and Isaac")
        yield


def run(config, out, *, indexed_review=None):
    """Only a trusted owner-injected verifier can admit indexed content."""
    with ExitStack() as stack:
        return _run(config, out, indexed_review, stack)


def _run(config, out, indexed_review, admission_stack):
    import yaml
    from store import Store, content_sha, parse_dataset_ref
    from intake import run as intake_run
    from intake_eval_gate import _eval_gate_error
    required = {"store", "dataset", "gate", "replay_root", "intake_out", "camera_profile", "training"}
    if set(config) != required:
        raise JobError(f"config must contain exactly {sorted(required)}")
    training = config["training"]
    drivable_head = training.get("recipe") == "drivable_head"
    keys = ({"seed", "epochs", "lr", "batch_size", "recipe", "parent_model",
             "parent_torchscript", "ignore_top"} if drivable_head else
            {"seed", "epochs", "lr", "batch_size", "base", "recipe"})
    if set(training) != keys:
        raise JobError(f"training needs exactly {sorted(keys)}")
    for name in (("seed", "epochs", "batch_size") if drivable_head else
                 ("seed", "epochs", "batch_size", "base")):
        if type(training[name]) is not int or training[name] < (0 if name == "seed" else 1):
            raise JobError(f"invalid training {name}")
    if drivable_head:
        if (type(training["ignore_top"]) is not int or not 0 <= training["ignore_top"] < 240
                or any(not isinstance(training[name], str) or not training[name].strip()
                       for name in ("parent_model", "parent_torchscript"))):
            raise JobError("drivable_head needs parent paths and ignore_top in [0,239]")
    elif training["recipe"] not in ("baseline", "enhanced") or training["base"] not in (8, 16):
        raise JobError("recipe baseline/enhanced, base 8/16 required")
    if type(training["lr"]) not in (int, float) or not 0 < training["lr"] < 1:
        raise JobError("learning rate must be finite in (0,1)")
    store = Store(config["store"])
    dataset = store.dataset_path(*parse_dataset_ref(config["dataset"]))
    if content_sha(dataset) != dataset.name:
        raise JobError("dataset content hash differs from version")
    gate_path = Path(config["gate"]).resolve()
    gate_raw = gate_path.read_bytes()
    gate = yaml.safe_load(gate_raw)
    if gate.get("require_eval") is not True or _eval_gate_error(gate):
        raise JobError("valid require_eval deployment gate required")
    evalset = (Path(config["replay_root"]) / gate["eval_set"]).resolve()
    if content_sha(evalset) != evalset.name:
        raise JobError("evaluation content hash differs from version")
    dataset_doc = json.loads((dataset / "manifest.json").read_text())
    sources = dataset_doc.get("sources", [])
    sources = sources if isinstance(sources, list) else [sources]
    indexed = (dataset_doc.get("builder") == "review_dataset.py (D-464)"
               or any(isinstance(source, dict)
                      and source.get("annotation_origin") == "human_reviewed_pinky_indexed" for source in sources))
    # D-554: labels derived from reviewed lane masks admit only a drivable_head candidate.
    derived = dataset_doc.get("schema") == "rosy.lane-derived-drivable/1"
    if derived and not drivable_head:
        raise JobError("D-554 lane-derived datasets train only the drivable_head recipe")
    if drivable_head and not (indexed or derived):
        raise JobError("drivable_head requires an indexed dataset or a D-554 lane-derived dataset")
    if derived:
        from lane_derived_drivable import verify_dataset
        try:
            derived_doc = verify_dataset(dataset, finalized=True)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise JobError(f"D-554 lane-derived admission denied: {exc}") from exc
    if indexed:
        from review_admission import IndexedReview
        if type(indexed_review) is not IndexedReview:
            raise JobError("independent indexed review training admission required")
    eval_doc = json.loads((evalset / "manifest.json").read_text())
    if eval_doc.get("purpose") != "eval":
        raise JobError("fixed evaluation dataset purpose required")
    shared = {f["session"] for f in dataset_doc["frames"]} & {f["session"] for f in eval_doc["frames"]}
    if shared:
        raise JobError(f"training/evaluation sessions overlap: {sorted(shared)}")
    profile = Path(config["camera_profile"]).resolve()
    camera_raw = profile.read_bytes()
    camera = json.loads(camera_raw)
    if not isinstance(camera.get("accepted"), bool):
        raise JobError("camera provenance must state accepted boolean explicitly")
    if drivable_head and camera["accepted"] is not True and not derived:
        raise JobError("drivable_head requires accepted camera provenance")
    # D-554 item 7: only the derived shadow-only candidate may train on provisional camera provenance.
    camera_provenance = "accepted" if camera["accepted"] is True else "provisional"
    parent = (validate_drivable_parent(training["parent_model"], training["parent_torchscript"],
                                      dataset_doc["classes"]) if drivable_head else None)
    source_files = [HERE / name for name in
                    ("train_job.py", "job_state.py", "rosy_lane_model.py", "recipes.py", "export_cell.py")]
    source_files += [PERCEPTION / "model" / name for name in ("intake.py", "intake_eval_gate.py")]
    source_files += [PERCEPTION / "store.py"]
    if indexed:
        source_files += [HERE / name for name in ("review_admission.py", "review_dataset.py",
                                                  "review_provenance.py", "review_authority.py",
                                                  "review_eval_companion.py")]
        source_files += [PERCEPTION / "dataset" / "build.py"]
    if drivable_head:
        source_files += [HERE / "drivable_head.py"]
    if derived:
        source_files += [PERCEPTION / "dataset" / "lane_derived_drivable.py"]
    inputs = {"config": config, "dataset_sha": dataset.name, "eval_sha": evalset.name,
              "gate_sha": hashlib.sha256(gate_raw).hexdigest(), "camera_sha": hashlib.sha256(camera_raw).hexdigest(),
              "source_files": {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files}}
    if parent is not None:
        inputs["parent_lane_model"] = parent["lineage"]
        inputs["parent_files"] = {str(path): digest for path, digest in parent["hashes"].items()}
    if drivable_head:
        inputs["camera_provenance"] = camera_provenance
    if derived:
        inputs["lane_derived"] = {"annotation_origin": derived_doc["annotation_origin"],
                                  "adr": derived_doc["adr"], "source": derived_doc["source"],
                                  "tool": derived_doc["tool"], "params": derived_doc["params"],
                                  "judge": {k: v for k, v in derived_doc["judge"].items() if k != "dropped"}}
    admitted = None
    if indexed:
        expected_files = {gate_path: inputs["gate_sha"], profile: inputs["camera_sha"],
                          **{ROOT / relative: digest for relative, digest in inputs["source_files"].items()},
                          **({} if parent is None else parent["hashes"])}
        admitted = admission_stack.enter_context(indexed_review.open(
            config, dataset, evalset, source_files + ([] if parent is None else parent["files"]),
            expected_file_hashes=expected_files))
        inputs["indexed_review"] = admitted.evidence
        dataset, gate_path = admitted.dataset, admitted.gate_path
    bound = ({ROOT / relative: digest for relative, digest in inputs["source_files"].items()}
             | parent["hashes"]) if derived else {}
    def check_indexed():
        if admitted is not None:
            admitted.check()
        if derived:  # D-554 re-check at every boundary, as IndexedReview does
            try:
                verify_dataset(dataset, finalized=True)
                changed = [str(path) for path, digest in bound.items() if sha(path) != digest]
            except (ValueError, OSError, KeyError, TypeError) as exc:
                raise JobError(f"D-554 lane-derived dataset changed after admission: {exc}") from exc
            if changed:
                raise JobError(f"D-554 parent/trainer source changed after admission: {changed}")
    out = Path(out).resolve()
    check_indexed()
    if drivable_head:
        return _run_drivable_candidate(config, out, dataset, profile, training, parent,
                                       inputs, check_indexed)
    with Job(out, inputs) as job:
        def train_stage(attempt):
            check_indexed()
            import numpy as np
            import torch
            from rosy_lane_model import LaneUNet, RosyLaneDataset, train
            from recipes import LightingDataset, adamw, make_loss, pixel_counts
            from run_log import RunLog
            seed = training["seed"]
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            torch.set_num_threads(4)
            train_ds, val_ds = RosyLaneDataset(dataset, "train"), RosyLaneDataset(dataset, "val")
            if not len(train_ds) or not len(val_ds):
                raise JobError("both session-level train and val splits required")
            if train_ds.classes[0]["role"] != "background":
                raise JobError("recipe requires background index 0")
            counts, val_counts = pixel_counts(train_ds), pixel_counts(val_ds)
            unobserved = check_coverage(train_ds.classes, counts, val_counts)
            check_indexed()
            attempt_dir = out / f"train-{attempt}"
            attempt_dir.mkdir(exist_ok=False)
            with gpu_lease():
                check_indexed()
                if not torch.cuda.is_available():
                    raise JobError("CUDA required")
                torch.cuda.manual_seed_all(seed)
                tracker = RunLog(attempt_dir, tensorboard=False)
                tracker.write_config({**inputs, **training, "device": "cuda:0",
                                      "gpu": torch.cuda.get_device_name(0), "torch": str(torch.__version__),
                                      "cuda": torch.version.cuda, "train_pixels": counts,
                                      "val_pixels": val_counts, "unobserved_classes": unobserved})
                try:
                    model = LaneUNet(n_classes=len(train_ds.classes), base=training["base"])
                    extra = {}
                    if training["recipe"] == "enhanced":
                        extra = {"loss_fn": make_loss(counts, device="cuda:0"), "optimizer_factory": adamw}
                        train_ds = LightingDataset(train_ds)
                    result = train(model, train_ds, val_ds, epochs=training["epochs"], lr=training["lr"],
                                   batch_size=training["batch_size"], device="cuda:0", **extra,
                                   on_epoch=tracker.on_epoch, log=lambda text: print(text, flush=True))
                    checkpoint = attempt_dir / "best.pt"
                    torch.save(model.cpu().state_dict(), checkpoint)
                    metrics = attempt_dir / "metrics.json"
                    metrics.write_text(json.dumps({**result, "classes": val_ds.classes}))
                    tracker.finish({"status": "trained", "best_epoch": result["best_epoch"]})
                    return receipt({"checkpoint": str(checkpoint), "metrics": str(metrics)},
                                   [checkpoint, metrics, attempt_dir / "config.json"])
                finally:
                    tracker.close()
        trained = job.step("train", train_stage)

        def export_stage(attempt):
            check_indexed()
            import torch
            from rosy_lane_model import LaneUNet, Preprocess
            from export_cell import export
            metrics = json.loads(Path(trained["metrics"]).read_text())
            model = LaneUNet(n_classes=len(metrics["classes"]), base=training["base"])
            model.load_state_dict(torch.load(trained["checkpoint"], map_location="cpu", weights_only=True))
            artifact = out / f"export-{attempt}"
            doc = export(model, artifact, classes=metrics["classes"], **Preprocess().manifest_kwargs(),
                         dataset_repo="store:" + parse_dataset_ref(config["dataset"])[0],
                         dataset_revision=dataset.name, camera_profile_revision="training-provenance-" + sha(profile),
                         trainer="rosy-training-job", val_iou=metrics["val_iou"],
                         experiment={"tracker": "local", "run_id": out.name, "path": "jobs/" + out.name})
            return receipt({"artifact": str(artifact), "revision": doc["model_revision"]},
                           [artifact / "model.onnx", artifact / "model_manifest.json"])
        exported = job.step("export", export_stage)

        def intake_stage(attempt):
            check_indexed()
            accepted = Path(config["intake_out"]) / exported["revision"]
            if (accepted / "model_manifest.json").exists() and (
                    sha(accepted / "model_manifest.json") != sha(Path(exported["artifact"]) / "model_manifest.json")):
                raise JobError("existing intake revision has different manifest; do not overwrite")
            code, report = intake_run(exported["artifact"], out=config["intake_out"], gate_path=gate_path,
                                      root=config["replay_root"], store=store.root)
            if code:
                if report.get("transient") or report.get("config_error"):
                    raise JobError("intake setup/infrastructure failed: " + "; ".join(report["reasons"]))
                raise Rejected("intake quality failed: " + "; ".join(report["reasons"]))
            return snapshot_intake(exported["artifact"], report)
        qualified = job.step("intake", intake_stage)

        def ready_stage(attempt):
            check_indexed()
            target = publish_ready(qualified["artifact"], store.root, out.name, before_ready=check_indexed)
            summary = out / "ready-receipt.json"
            summary.write_text(json.dumps({"revision": exported["revision"], "location": str(target)}))
            return receipt({"revision": exported["revision"], "location": str(target)}, [summary])
        result = job.step("ready", ready_stage)
        # A watcher may have moved the last receipt's folder after a crash/restart.
        check_indexed()
        result["location"] = str(publish_ready(qualified["artifact"], store.root, out.name, before_ready=check_indexed))
        job.finish()
        return result


def _run_drivable_candidate(config, out, dataset, profile, training, parent, inputs, check_indexed):
    """Train an admitted frozen head; leave intake, READY, and device delivery closed."""
    job = Job(out, inputs)
    import numpy as np
    import torch
    from store import parse_dataset_ref
    from rosy_lane_model import RosyLaneDataset
    from drivable_head import (LaneWithDrivable, drivable_target, load_frozen_lane,
                               train_head, verify_candidate_lane_parity, verify_parent_parity)
    from export_cell import export
    from run_log import RunLog

    seed = training["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    datasets = [RosyLaneDataset(dataset, split, **parent["input"])
                for split in ("train", "val")]
    train_ds, val_ds = datasets
    if not len(train_ds) or not len(val_ds):
        raise JobError("both session-level train and val splits required")
    index = len(train_ds.classes) - 1
    coverage = {}
    for split, ds in zip(("train", "val"), datasets):
        positive = negative = 0
        for frame in range(len(ds)):
            _, mask = ds[frame]
            target, keep = drivable_target(mask, index, ds.ignore_index, training["ignore_top"])
            positive += int((target.bool() & keep).sum())
            negative += int((~target.bool() & keep).sum())
        coverage[split] = {"positive": positive, "negative": negative}
        if not positive or not negative:
            raise JobError(f"{split} needs positive and negative drivable pixels below ignore_top")
    frames = [ds[0][0].unsqueeze(0) for ds in datasets]
    lane, _ = load_frozen_lane(parent["torchscript"], classes=train_ds.classes[:-1])
    parent_parity = verify_parent_parity(lane, parent["torchscript"], parent["onnx"],
                                         frames, ignore_top=training["ignore_top"])
    check_indexed()

    with job:
        def train_stage(attempt):
            check_indexed()
            attempt_dir = out / f"train-{attempt}"
            attempt_dir.mkdir(exist_ok=False)
            with gpu_lease():
                check_indexed()
                if not torch.cuda.is_available():
                    raise JobError("CUDA required")
                torch.cuda.manual_seed_all(seed)
                tracker = RunLog(attempt_dir, tensorboard=False)
                tracker.write_config({**inputs, "training": training,
                                      "gpu": torch.cuda.get_device_name(0),
                                      "coverage": coverage, "parent_parity": parent_parity})
                model = LaneWithDrivable(lane, ignore_top=training["ignore_top"])
                try:
                    result = train_head(model, train_ds, val_ds, epochs=training["epochs"],
                                        lr=training["lr"], batch_size=training["batch_size"],
                                        device="cuda:0", log=lambda message: print(message, flush=True))
                    check_indexed()
                    if result["best_epoch"] is None:
                        raise JobError("drivable validation has no scored pixels")
                    for row in result["history"]:
                        tracker.on_epoch(row)
                    checkpoint = attempt_dir / "head.pt"
                    torch.save(model.drivable.cpu().state_dict(), checkpoint)
                    metrics = attempt_dir / "metrics.json"
                    metrics.write_text(json.dumps({**result, "coverage": coverage,
                                                   "parent_parity": parent_parity}, allow_nan=False),
                                       encoding="utf-8")
                    tracker.finish({"status": "candidate_trained", "best_epoch": result["best_epoch"]})
                    return receipt({"checkpoint": str(checkpoint), "metrics": str(metrics)},
                                   [checkpoint, metrics, attempt_dir / "config.json"])
                finally:
                    tracker.close()
        trained = job.step("train", train_stage)

        def export_stage(attempt):
            check_indexed()
            metrics = json.loads(Path(trained["metrics"]).read_text(encoding="utf-8"))
            frozen, _ = load_frozen_lane(parent["torchscript"], classes=train_ds.classes[:-1])
            model = LaneWithDrivable(frozen, ignore_top=training["ignore_top"])
            model.drivable.load_state_dict(torch.load(trained["checkpoint"], map_location="cpu",
                                                      weights_only=True))
            artifact = out / f"export-{attempt}"
            doc = export(model, artifact, classes=train_ds.classes, **parent["input"],
                         dataset_repo="store:" + parse_dataset_ref(config["dataset"])[0],
                         dataset_revision=dataset.name,
                         camera_profile_revision="training-provenance-" + sha(profile),
                         trainer="rosy-frozen-drivable-head", revision_prefix="v13-drivable",
                         parent_lane_model=parent["lineage"],
                         camera_provenance=inputs["camera_provenance"],
                         dataset_annotation=(None if "lane_derived" not in inputs else
                                             {k: inputs["lane_derived"][k] for k in ("annotation_origin", "adr")}),
                         val_iou={"drivable": metrics["val_drivable_iou_all"]},
                         experiment={"tracker": "local", "run_id": out.name,
                                     "path": "jobs/" + out.name})
            candidate_parity = verify_candidate_lane_parity(parent["onnx"],
                artifact / "model.onnx", frames, ignore_top=training["ignore_top"])
            proof = artifact / "candidate_parity.json"
            proof.write_text(json.dumps(candidate_parity, sort_keys=True) + "\n", encoding="utf-8")
            check_indexed()
            return receipt({"artifact": str(artifact), "revision": doc["model_revision"]},
                           [artifact / "model.onnx", artifact / "model_manifest.json", proof])
        exported = job.step("export", export_stage)
        check_indexed()
        job.finish("candidate")
        return {**exported, "status": "candidate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(json.loads(args.config.read_text()), args.out)))
    except (JobError, OSError, subprocess.SubprocessError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
