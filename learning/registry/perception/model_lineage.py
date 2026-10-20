"""Read-only links between existing model, dataset, intake and delivery records."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "middleware/perception"))
from control.sensing.perception.learned.manifest import (  # noqa: E402
    check_revision, load_manifest, sha256_file, verify_files,
)
from store import Store, read_fixed_manifest, refuse_publication_links, safe_name  # noqa: E402


def _inside(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact path escapes configured root")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("artifact path contains a symlink")
        if parent == root:
            break
    return path


def _object(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    return doc


def _fixed(root, name, revision):
    if not safe_name(name) or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
        raise ValueError("invalid fixed dataset/eval reference")
    path = _inside(root, Path(root) / name / revision)
    if not path.exists():
        return None
    doc = read_fixed_manifest(path)
    return {"path": str(path), "content_sha": revision, "declared": doc}


def inspect_model(models, store, revision, *, journal=None):
    """Return diagnostic evidence, never a quality or operational permission verdict."""
    check_revision(revision)
    folder = _inside(models, Path(models) / revision)
    refuse_publication_links(folder)
    manifest = load_manifest(folder)
    if manifest.model_revision != revision:
        raise ValueError("model revision differs from folder")
    verify_files(manifest)
    result = {
        "model": {"revision": revision, "path": str(folder),
                  "manifest_sha256": sha256_file(folder / "model_manifest.json"),
                  "files": [{"name": f.name, "sha256": f.sha256} for f in manifest.files]},
        "dataset": None, "eval": None, "intake": None, "delivery": [],
        "missing": ["source_proof", "human_review", "training_receipt"],
    }
    owner = Store(store)
    repo = manifest.dataset_repo
    if repo.startswith("store:"):
        result["dataset"] = _fixed(owner.datasets_dir, repo[6:], manifest.dataset_revision)
    report_path = folder / "intake_report.json"
    if report_path.exists():
        report = _object(report_path)
        if report.get("model_revision") != revision or report.get("files") != result["model"]["files"]:
            raise ValueError("intake report does not bind this model and its files")
        result["intake"] = {"path": str(report_path), "sha256": sha256_file(report_path),
                            "verdict": report.get("verdict"), "tool_commit": report.get("tool_commit")}
        if not report.get("tool_commit"):
            result["missing"].append("tool_commit")
        evaluation = report.get("eval")
        if evaluation is not None:
            if not isinstance(evaluation, dict) or not isinstance(evaluation.get("set"), dict):
                raise ValueError("invalid intake eval reference")
            fixed = evaluation["set"]
            declared_path = fixed.get("path")
            if not isinstance(declared_path, str):
                raise ValueError("missing intake eval path")
            parts = declared_path.replace("\\", "/").rstrip("/").split("/")
            if len(parts) < 3 or parts[-3] != "evalsets" or parts[-1] != fixed.get("content_sha"):
                raise ValueError("intake eval path/content hash disagree")
            result["eval"] = _fixed(owner.evalsets_dir, parts[-2], fixed["content_sha"])
    if journal is not None:
        for line in Path(journal).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("schema") != "rosy.model-pointer-change/1":
                raise ValueError("invalid pointer journal record")
            if row.get("pointer_revision") == revision:
                result["delivery"].append(row)
    for key in ("dataset", "eval", "intake", "delivery"):
        if not result[key]:
            result["missing"].append(key)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_model(args.models, args.store, args.revision, journal=args.journal)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        print(f"lineage error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
