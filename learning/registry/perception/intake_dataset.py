"""Immutable dataset/source bindings for intake; no quality judgment."""
from pathlib import Path
import json
import re

from control.sensing.perception.learned.manifest import validate_label_semantic


class EvalSetError(ValueError):
    """The gate's eval set is missing or unreadable: the site's setup, not the model."""


def _verified_manifest(path: Path) -> dict:
    """Bind the manifest being read to the store's immutable content version."""
    import store
    try:
        doc = store.read_fixed_manifest(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("classes"), list):
            raise ValueError("no classes list")
        for c in doc["classes"]:
            if (not isinstance(c, dict) or not isinstance(c.get("name"), str)
                    or not c["name"] or not isinstance(c.get("role"), str)):
                raise ValueError("invalid class entry")
            validate_label_semantic(c)
        if not isinstance(doc.get("frames"), list) or any(
                not isinstance(f, dict) or not isinstance(f.get("session"), str) for f in doc["frames"]):
            raise ValueError("invalid frames/session metadata")
        return doc
    except (OSError, ValueError) as exc:
        raise EvalSetError(f"dataset {path}: {exc}") from exc


def _sessions(manifest: dict) -> set[str]:
    """Sessions of a dataset/eval set manifest: frames[].session and labels[].session."""
    return ({f["session"] for f in manifest.get("frames") or [] if isinstance(f, dict) and "session" in f}
            | {v["session"] for v in manifest.get("labels") or [] if isinstance(v, dict) and "session" in v})


def training_sessions(store, revision, *, verify_content=False) -> tuple[str, set[str], set[str], set[str], dict] | None:
    """The store dataset version the model was trained on ("<name>@<sha>", its sessions),
    found as <store>/datasets/*/<revision>/manifest.json, with its manifest; None when it cannot be resolved
    (no store, a revision that is not a 64-hex content sha, no such folder)."""
    if not store or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
        return None
    for mf in sorted(Path(store).glob(f"datasets/*/{revision}/manifest.json")):
        try:
            doc = (_verified_manifest(mf.parent) if verify_content else
                   json.loads(mf.read_text(encoding="utf-8")))
            groups = {row.get("capture_group") for row in doc["frames"] if row.get("capture_group")}
            grouped_sessions = {row["session"] for row in doc["frames"] if row.get("capture_group")}
            for row in doc.get("sources", []):
                if isinstance(row, dict) and row.get("capture_group"):
                    groups.add(row["capture_group"])
                    grouped_sessions.add(row.get("session"))
            return (f"{mf.parent.parent.name}@{revision}", _sessions(doc), groups,
                    grouped_sessions, doc)
        except (OSError, ValueError):
            if verify_content:
                raise
            continue
    return None


