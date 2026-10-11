"""D-666 immutable paired replay. Completed diagnostics always remain HOLD."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for holder in ("learning/registry/perception", "learning/curation/perception",
               "learning/evaluation/perception", "middleware/perception", "contracts/foundation"):
    path = str(ROOT / holder)
    if path not in sys.path:
        sys.path.insert(0, path)

from datetime import datetime
import json

import cv2
import numpy as np

import build
import intake
from intake_eval_gate import evaluation_semantics
import review_evidence as review
import review_masks
import store
from control.sensing.perception.learned.manifest import verify_files
from control.sensing.perception.learned.runner import LaneSegModel
from core_common.observation import ObservationSnapshot, SnapshotValidity
from road_fitness import evaluate_model_frame, summarize_frames
from source_uncertainty import summarize_sources

SCHEMA = "rosy.perception.region-inputs/1"


def _identities(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("non-empty frame list required")
    result = {}
    for row in rows:
        key = row.get("identity") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key.strip() or key in result:
            raise ValueError("invalid or duplicate frame identity")
        result[key] = row
    return result


def _truth_dataset(folder, semantic):
    store.refuse_publication_links(Path(folder))
    folder = Path(folder).resolve()
    doc = intake._verified_manifest(folder)
    if doc.get("schema") != "rosy.perception.dataset/1" or doc.get("purpose") != "eval" or doc.get("ignore_index") != 255:
        raise ValueError("fixed evaluation dataset required")
    class_bytes = review.safe_file(folder, "pixel-classes.yaml").read_bytes()
    classes = build.load_classes(Path("pixel-classes.yaml"), source_bytes=class_bytes)
    if classes != doc["classes"]:
        raise ValueError("review classes differ from dataset")
    roads = [c for c in classes if c["role"] == "drivable"]
    if len(roads) != 1 or roads[0].get("semantic") != semantic:
        raise ValueError("drivable semantic differs from evaluation target")
    authority = review.validate_authority(json.loads(review.safe_file(folder, "authority.json").read_bytes()))
    if (authority["decision_sha256"] != doc.get("authority_sha256")
            or authority["pixel_classes_sha256"] != review.sha(class_bytes)
            or doc.get("classes_sha256") != review.sha(class_bytes)
            or authority["classes_signature"] != review_masks.signature(classes)):
        raise ValueError("review authority class/content binding differs")
    approved = _identities(authority["frames"])
    rows = _identities(doc["frames"])
    for identity, frame in rows.items():
        row = approved.get(identity)
        if not row or row["mask_decision"] != "approved" or row["frame_excluded"]:
            raise ValueError("frame lacks exact approved human mask")
        if frame.get("split") != "eval" or not all(isinstance(frame.get(k), str) and frame[k]
                                                    for k in ("session", "capture_group")):
            raise ValueError("eval split and source group required")
        pairs = {"frame": "frame", "image_sha256": "image_sha256", "mask_sha256": "mask_sha256",
                 "mask_version": "mask_version", "session": "source_session", "capture_group": "capture_group"}
        if any(frame.get(k) != row[v] or type(frame.get(k)) is not type(row[v]) for k, v in pairs.items()):
            raise ValueError("approved frame identity/hash/version differs")
        if frame.get("approval_sha256") != review.sha(review.encoded(row["pixel_approval"])):
            raise ValueError("pixel approval hash differs")
    return folder, doc, rows, approved, roads[0]["index"]


def _read_frame(dataset, identity):
    folder, doc, rows, approved, target = dataset
    frame, approval = rows[identity], approved[identity]
    image_raw = review.safe_file(folder, frame["image"]).read_bytes()
    mask_raw = review.safe_file(folder, frame["mask"]).read_bytes()
    if review.sha(image_raw) != frame["image_sha256"] or review.sha(mask_raw) != frame["mask_sha256"]:
        raise ValueError("approved image or mask hash differs")
    image = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
    mask = cv2.imdecode(np.frombuffer(mask_raw, np.uint8), cv2.IMREAD_UNCHANGED)
    shape = (approval["height"], approval["width"])
    if image is None or mask is None or image.shape[:2] != shape or mask.shape != shape or mask.dtype != np.uint8:
        raise ValueError("approved image/mask dimensions or encoding differ")
    if not np.isin(mask, [c["index"] for c in doc["classes"]] + [255]).all():
        raise ValueError("review mask contains an undeclared class")
    unknown = int((mask == 255).sum())
    if (type(frame.get("reviewed_unknown_count")) is not int or frame["reviewed_unknown_count"] != unknown
            or approval["pixel_approval"].get("reviewed_unknown_count", 0) != unknown):
        raise ValueError("unknown pixels differ from reviewed approval")
    return image, np.where(mask == 255, 255, mask == target).astype(np.uint8)


def _snapshot(row):
    if not isinstance(row, dict) or not isinstance(row.get("evidence_refs"), list):
        raise ValueError("invalid observation snapshot")
    value = dict(row)
    try:
        value["received_at"] = datetime.fromisoformat(value["received_at"])
        value["validity"] = SnapshotValidity(value["validity"])
        value["evidence_refs"] = tuple(value["evidence_refs"])
        return ObservationSnapshot(**value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid observation snapshot: {exc}") from exc


def _semantics(model_classes, classes):
    names = {c["name"] for c in model_classes} & {c["name"] for c in classes}
    result = evaluation_semantics(model_classes, classes, list(names))
    if result["semantic_mismatches"] or result["unverified_semantics"]:
        raise ValueError("model/training/evaluation label semantic differs or is unverified")
    first, second = ({c["name"]: c["role"] for c in cs} for cs in (model_classes, classes))
    if any(first[n] != second[n] for n in names):
        raise ValueError("model/training/evaluation class role differs")


def run(model_folder, *, store_root, road_eval, region_eval, inputs, max_age_ns):
    if type(max_age_ns) is not int or max_age_ns <= 0:
        raise ValueError("max_age_ns must be a positive integer")
    for path in (model_folder, inputs):
        store.refuse_publication_links(Path(path))
    model_folder, inputs = Path(model_folder).resolve(), Path(inputs).resolve()
    manifest_path = model_folder / "model_manifest.json"
    model_raw = manifest_path.read_bytes()
    road = _truth_dataset(road_eval, "road_surface/1")
    region = _truth_dataset(region_eval, "current_road_region/1")
    if road[2].keys() != region[2].keys():
        raise ValueError("road/region frame identities differ")
    observations = store.read_fixed_manifest(inputs)
    if observations.get("schema") != SCHEMA:
        raise ValueError("region input schema differs")
    model_doc = json.loads(model_raw)
    expected = {"model_revision": model_doc["model_revision"], "road_eval_sha256": road[0].name,
                "region_eval_sha256": region[0].name,
                "preprocessing_sha256": review.sha(review.encoded(model_doc["input"]))}
    if any(observations.get(k) != v for k, v in expected.items()):
        raise ValueError("fixed model/evaluation/preprocessing input binding differs")
    _semantics(model_doc["output"]["classes"], road[1]["classes"])
    observed = _identities(observations.get("frames"))
    if observed.keys() != road[2].keys():
        raise ValueError("observed/evaluation frame identities differ")
    refs = observations.get("training_refs")
    if not isinstance(refs, list) or not refs or any(not isinstance(r, str) for r in refs) or len(set(refs)) != len(refs):
        raise ValueError("fixed training refs required")
    registry = store.Store(store_root)
    training, sessions, groups, images = [], set(), set(), set()
    for ref in refs:
        name, digest = store.parse_dataset_ref(ref)
        path = registry.dataset_path(name, digest)
        doc = intake._verified_manifest(path)
        if path in training:
            raise ValueError("duplicate fixed training dataset")
        if not doc["frames"]:
            raise ValueError("non-empty training frame list required")
        if digest == model_doc["dataset"]["revision"]:
            _semantics(model_doc["output"]["classes"], doc["classes"])
        for frame in doc["frames"]:
            if not all(isinstance(frame.get(k), str) and frame[k] for k in ("session", "capture_group")):
                raise ValueError("training source group is unverified")
            sessions.add(frame["session"])
            groups.add(frame["capture_group"])
            images.add(review.sha(review.safe_file(path.resolve(), frame["image"]).read_bytes()))
        training.append(path)
    if model_doc["dataset"]["revision"] not in {p.name for p in training}:
        raise ValueError("candidate training dataset is absent from fixed refs")
    reservations = registry.eval_reservations()
    for identity, frame in road[2].items():
        other, supplied = region[2][identity], observed[identity]
        if any(frame[k] != other[k] for k in ("image_sha256", "session", "capture_group")):
            raise ValueError("paired road/region source image differs")
        if supplied.get("image_sha256") != frame["image_sha256"]:
            raise ValueError("observed image hash differs")
        if reservations.get(frame["session"]) != frame["capture_group"]:
            raise ValueError("evaluation source reservation differs")
        if frame["session"] in sessions or frame["capture_group"] in groups or frame["image_sha256"] in images:
            raise ValueError("training/evaluation source or image overlap")
    model = LaneSegModel.open(model_folder)
    if model.manifest.raw != model_doc:
        raise ValueError("model manifest changed while loading")
    reports = []
    for identity, supplied in observed.items():
        image, road_truth = _read_frame(road, identity)
        _, region_truth = _read_frame(region, identity)
        report = evaluate_model_frame(model, image, _snapshot(supplied.get("image_snapshot")),
                                      _snapshot(supplied.get("anchor_snapshot")), supplied.get("seed_pixels"),
                                      road_truth, region_truth, domain=supplied.get("domain"),
                                      conditions=supplied.get("conditions"), now_ns=supplied.get("now_ns"),
                                      max_age_ns=max_age_ns)
        reports.append({"identity": identity, "session": frame["session"],
                        "capture_group": frame["capture_group"], **report})
    for path in [road[0], region[0], inputs, *training]:
        store.read_fixed_manifest(path)
    verify_files(model.manifest)
    if manifest_path.read_bytes() != model_raw:
        raise ValueError("model manifest changed during replay")
    return {"fitness_verdict": "HOLD", "hold_reasons": ["live_review_freshness_unverified",
            "reviewer_independence_unverified", "upstream_training_closure_unverified",
            "physical_projection_unverified", "acceptance_profile_and_device_evidence_missing"],
            "bindings": {**expected, "inputs_sha256": inputs.name,
                         "model_manifest_sha256": review.sha(model_raw), "training_refs": refs,
                         "road_authority_sha256": road[1]["authority_sha256"],
                         "region_authority_sha256": region[1]["authority_sha256"],
                         "declared_training_disjoint": True, "max_age_ns": max_age_ns},
            "frames": reports, "summary": summarize_frames(reports),
            "source_uncertainty": summarize_sources(reports)}


def execute(args) -> int:
    output = Path(args.out)
    try:
        if output.exists() or output.is_symlink():
            raise ValueError("output already exists")
        report = run(args.model, store_root=args.store, road_eval=args.road_eval,
                     region_eval=args.region_eval, inputs=args.inputs, max_age_ns=args.max_age_ns)
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        with output.open("x", encoding="utf-8") as stream:
            stream.write(raw)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"fitness diagnostic error: {exc}")
        return 2
    print(f"fitness diagnostic HOLD: {output}")
    return 0
