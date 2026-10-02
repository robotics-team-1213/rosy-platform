#!/usr/bin/env python3
"""Build one signed device-twin payload release with the repo's real release tooling.

Runs inside the twin base container (Linux, so exec bits and LF are real):

    python3 build_twin_release.py --repo /work/repo --twin /work/twin --release-id 2026.10.02-002 \
        --revision <40 hex> --python-runtime <64 hex> --variant good \
        --private-key /keys/twin.private.pem --public-key /keys/rosy-release-2026-01.pem --out /out

The payload is the real native runtime (install-native-runtime.sh into
deploy/robot/native, as build-native-payload.sh does) plus fake ROS programs
under twin/. Only ROS is faked. build_payload_release.py build, then
sign_image_release.py with the throwaway twin key, then build_payload_release.py
pack (verifying the signature) produce <out>/<id>.tar.gz.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

VARIANTS = ("good", "crash-after-ready", "never-ready")


def run(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(argv)} failed ({done.returncode}): {done.stdout}{done.stderr}")
    return done.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--twin", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--python-runtime", required=True)
    parser.add_argument("--variant", choices=VARIANTS, default="good")
    parser.add_argument("--layer-marker", action="store_true",
                        help="add deploy/robot/native/twin-layer-marker.txt (an image-layer change)")
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    release_tools = args.repo / "deploy/robot/pinky_pro/release"
    native = args.repo / "deploy/robot/pinky_pro/native"
    work = Path(tempfile.mkdtemp(prefix=f"twin-{args.release_id}-"))
    try:
        payload = work / "payload"
        (payload / "install").mkdir(parents=True)
        (payload / "install/.rosy-release").write_text(args.release_id + "\n", encoding="utf-8")
        (payload / "rosy-packages.txt").write_text("bringup\ncontrol\ncore\n", encoding="utf-8")
        (payload / "source-revision.txt").write_text(args.revision + "\n", encoding="utf-8")
        (payload / "python-runtime.sha256").write_text(args.python_runtime + "\n", encoding="utf-8")
        (payload / "deploy/robot").mkdir(parents=True)
        run(["bash", str(native / "install-native-runtime.sh"), str(payload / "deploy/robot/native")])
        if args.layer_marker:
            (payload / "deploy/robot/native/twin-layer-marker.txt").write_text(
                f"image-layer change carried by {args.release_id}\n", encoding="utf-8")
        shutil.copytree(args.twin / "release_payload/twin", payload / "twin")
        for script in (payload / "twin").glob("*.py"):
            script.chmod(0o755)
        (payload / "twin/variant").write_text(args.variant + "\n", encoding="utf-8")

        release = work / args.release_id
        out = args.out / f"{args.release_id}.tar.gz"
        run([sys.executable, "-B", str(release_tools / "build_payload_release.py"), "build",
             "--payload-root", str(payload), "--release-id", args.release_id, "--out", str(release)])
        run([sys.executable, "-B", str(release_tools / "sign_image_release.py"), str(release),
             "--private-key", str(args.private_key), "--public-key", str(args.public_key)])
        packed = json.loads(run([sys.executable, "-B", str(release_tools / "build_payload_release.py"), "pack",
                                 "--release-dir", str(release), "--out", str(out),
                                 "--public-key", str(args.public_key)]).strip().splitlines()[-1])
        print(json.dumps({"ok": True, "release_id": args.release_id, "variant": args.variant,
                          "tarball": str(out), "sha256": packed["sha256"], "members": packed["members"]}))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
