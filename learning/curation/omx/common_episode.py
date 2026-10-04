"""Wrap a validated OMX demonstration as rosy.episode/1, preserving original bytes.

common_episode.py <source-episode> <new-output-directory>
No robot connection, actuator command, upload, or synthetic task-success label.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "contracts/learning/src"))

from rosy.contracts.learning import seal, validate_episode  # noqa: E402
from rosy.contracts.learning.omx import validate_demonstration as validate_omx, owner_correlations, validate_profile  # noqa: E402


def convert(source, output, *, owner_receipts=()):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("a new directory separate from the source Episode is required")
    if output.drive.upper() == "F:":
        raise ValueError("artifact output belongs on X:, not the source drive")
    validated = validate_omx(source)
    manifest, samples = validated["manifest"], validated["samples"]
    receipt_payloads, receipts = {}, []
    if owner_receipts:
        # The optional offline input uses the existing wire validator; the contracts wheel stays stdlib-only.
        sys.path.insert(0, str(ROOT / 'contracts/foundation'))
        from core_common.protocol.schemas import DeviceActionReceipt
        for index, file in enumerate(owner_receipts):
            payload = Path(file).read_bytes()
            receipt = json.loads(payload)
            DeviceActionReceipt.model_validate(receipt)
            receipts.append(receipt)
            receipt_payloads[f'owner-receipts/{index:06d}.json'] = payload
    correlations = owner_correlations(validated, receipts)
    paths = ["manifest.json", "samples.jsonl", "events.jsonl"]
    paths += sorted({row["image_path"] for row in samples})
    payloads = {}
    for relative in paths:
        file = source / relative
        if file.is_symlink() or not file.resolve().is_relative_to(source):
            raise ValueError("source path escapes Episode")
        payloads[relative] = file.read_bytes()
    if json.loads(payloads["manifest.json"]) != manifest:
        raise ValueError("source manifest changed during validation")
    for name in ("samples", "events"):
        if hashlib.sha256(payloads[name + ".jsonl"]).hexdigest() != manifest[name + "_sha256"]:
            raise ValueError("source stream changed during validation")
    for row in samples:
        if hashlib.sha256(payloads[row["image_path"]]).hexdigest() != row["image_sha256"]:
            raise ValueError("source image changed during validation")

    output.mkdir(parents=True)
    references = {}
    for relative, payload in payloads.items():
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        references[relative] = {"path": target.relative_to(output).as_posix(), "bytes": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest()}
    receipt_refs = []
    for relative, payload in receipt_payloads.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        receipt_refs.append(dict(path=relative, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
    provenance = manifest["provenance"]
    doc = seal({"schema": "rosy.episode/1", "episode_id": manifest["episode_id"],
                "profile": "omx_demonstration_v1", "device": provenance["instance_id"],
                "robot_type": manifest["robot_type"], "environment": "sim",
                "clock_domain": provenance["clock_domain"], "task": manifest["task"], "skill": None,
                "revisions": {"policy": None, "model": None,
                              "calibration": provenance["calibration_revision"], "camera_profile": None},
                "sources": list(references.values()) + receipt_refs,
                "streams": {"observation": references["samples.jsonl"],
                            "action": references["samples.jsonl"], "events": references["events.jsonl"]},
                "correlations": correlations, "status": "complete",
                "outcome": {"task": manifest["task_outcome"], "action": "unknown", "judge": "operator",
                            "evidence": [references["manifest.json"]]}})
    validate_episode(doc, root=output)
    validate_profile(doc, root=output)
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output / "manifest.json")
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument('--owner-receipt', action='append', type=Path, default=[],
                    help='repeat for each recorded goal, all in one Action/attempt/journal')
    args = ap.parse_args()
    print(json.dumps(convert(args.source, args.output, owner_receipts=args.owner_receipt)))


if __name__ == "__main__":
    main()
