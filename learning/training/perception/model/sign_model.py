"""Sign a model folder's manifest with the release signing key (D-423 §3.4).

sign_model.py <model_folder> --key <ed25519 private key> [--check <trusted keys dir>]

Writes model_manifest.json.sig: base64 of an Ed25519 signature over the exact bytes
of model_manifest.json, made by deploy/robot/pinky_pro/release/signing.py
(sign_checksums), the same module and key environment as payload releases. The
manifest pins every model file by sha256, so this one signature covers the bundle.
Run where the release key lives (the signing environment), after intake and before
deliver. --check verifies the result with the robot's verifier against a folder of
trusted public keys. The robot refuses an unsigned object_det bundle unless
object_detector_node's allow_unsigned_models dev flag is on."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "deploy" / "robot" / "pinky_pro" / "release", ROOT / "src" / "runtime" / "sensing",
           ROOT / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

from signing import sign_checksums  # noqa: E402  (deploy/robot/pinky_pro/release/signing.py)
from control.sensing.perception.learned.manifest import MANIFEST_NAME  # noqa: E402
from control.sensing.perception.learned.signature import (  # noqa: E402
    SIGNATURE_NAME, SignatureError, verify_manifest_signature)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("--key", required=True, help="Ed25519 private key (PEM), signing environment only")
    ap.add_argument("--check", help="verify against this folder of trusted public keys (*.pem)")
    args = ap.parse_args(argv)
    folder = Path(args.folder)
    manifest = folder / MANIFEST_NAME
    if not manifest.is_file():
        print(f"refused: no {MANIFEST_NAME} in {folder}", file=sys.stderr)
        return 2
    (folder / SIGNATURE_NAME).write_text(sign_checksums(manifest.read_bytes(), Path(args.key)) + "\n",
                                         encoding="ascii")
    if args.check:
        try:
            key = verify_manifest_signature(folder, args.check)
        except SignatureError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(f"verified with {key}")
    print(f"signed {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
