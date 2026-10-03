"""Check a model folder before handing it over: check_manifest.py <model_folder>.

Runs load_manifest + verify_files and, when onnxruntime is importable, LaneSegModel.open.
Prints `OK <model_revision>` or the error; exit 1 on failure."""

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, REPO + "/src/runtime/sensing")
sys.path.insert(0, REPO + "/src/contracts/foundation")  # core_common, imported by control (D-424)

from control.sensing.perception.learned.manifest import (  # noqa: E402
    ManifestError, load_manifest, verify_files)


def check(folder: str) -> str:
    manifest = load_manifest(folder)
    verify_files(manifest)
    if manifest.backend == "ncnn":
        from control.sensing.perception.learned.detector import ObjectDetModel
        from control.sensing.perception.learned.runner import LaneSegModel
        opener = ObjectDetModel if manifest.task == "object_det" else LaneSegModel
        opener.open(folder)  # missing NCNN is an error, never an unverified OK
        return manifest.model_revision
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return manifest.model_revision
    if manifest.task == "object_det":
        from control.sensing.perception.learned.detector import ObjectDetModel
        ObjectDetModel.open(folder)
        return manifest.model_revision
    from control.sensing.perception.learned.runner import LaneSegModel
    LaneSegModel.open(folder)
    return manifest.model_revision


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: check_manifest.py <model_folder>", file=sys.stderr)
        return 2
    try:
        print("OK", check(argv[0]))
    except ManifestError as exc:
        print(f"FAIL {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
