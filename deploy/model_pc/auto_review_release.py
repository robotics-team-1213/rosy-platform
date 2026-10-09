"""Activate a review UI from the Model PC's already accepted signed code release."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_review_release import APP, WEB, install

if os.name == "posix":
    import fcntl


def apply(model_root: Path, review_root: Path, state_dir: Path, python: Path,
          host: str, port: int, unit: Path, minimum_sequence: int) -> str:
    with (model_root / "work.lock").open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return "waiting for model-code update or learning job"
        return apply_locked(model_root, review_root, state_dir, python, host, port, unit, minimum_sequence)


def apply_locked(model_root: Path, review_root: Path, state_dir: Path, python: Path,
                 host: str, port: int, unit: Path, minimum_sequence: int) -> str:
    state = json.loads((model_root / "state.json").read_text(encoding="utf-8"))
    sequence = state["sequence"]
    commit = state.get("source_commit")
    if (sequence <= minimum_sequence or state.get("pending") or state.get("result") in {"rejected", "rolled-back", "recovered"}
            or not isinstance(commit, str) or len(commit) != 40):
        return "waiting for a newer accepted model-code release"
    source = (model_root / "current").resolve(strict=True)
    if source != (model_root / "releases" / f"{sequence}-{commit}").resolve():
        raise ValueError("model-code current differs from accepted state")
    release = f"model-code-{sequence}-{commit[:12]}"
    target = review_root / "releases" / release
    if target.is_dir() and (review_root / "current").resolve(strict=True) == target.resolve():
        return f"already active: {release}"
    for required in (APP, WEB / "index.html", WEB / "pixels.html", Path("shared/web/shared-assets.json")):
        if not (source / required).is_file():
            raise ValueError(f"signed source lacks review app file: {required}")
    with tempfile.TemporaryDirectory(prefix="rosy-review-release-") as staging:
        source_copy = Path(staging) / "source"
        shutil.copytree(source, source_copy, ignore=lambda path, names: {"data"} if Path(path) == source else set())
        install(source_copy, release, review_root, state_dir, python, host, port, unit)
    return f"activated: {release}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-code-root", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8774)
    parser.add_argument("--minimum-sequence", type=int, required=True)
    args = parser.parse_args()
    unit = Path.home() / ".config/systemd/user/rosy-review-v13.service"
    print(apply(args.model_code_root, args.review_root, args.state, args.python,
                args.host, args.port, unit, args.minimum_sequence))


if __name__ == "__main__":
    main()
