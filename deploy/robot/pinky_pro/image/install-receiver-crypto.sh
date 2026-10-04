#!/usr/bin/env bash
# Build-time only: hashlocked binary wheels become signed switchable payload.
set -euo pipefail
[[ $# == 3 ]] || { echo 'usage: install-receiver-crypto.sh REQUIREMENTS WHEELHOUSE RELEASE_ROOT' >&2; exit 2; }
requirements="$1"
wheelhouse="$2"
release_root="$3"
[[ "$(uname -m)" == aarch64 ]] || { echo 'ARM64 build required' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
[[ -f "$requirements" && -d "$wheelhouse" && -d "$release_root" ]] || exit 1
[[ ! -e "$release_root/runtime-python" ]] || { echo 'refusing reused auxiliary runtime' >&2; exit 1; }
python3 -m pip install --no-index --find-links "$wheelhouse" --require-hashes --no-deps \
    --only-binary=:all: --no-compile --target "$release_root/runtime-python" -r "$requirements"
# No build-time CFFI CLI is part of the CORE import runtime.
python3 -c 'from pathlib import Path; import shutil,sys; p=Path(sys.argv[1])/"bin"; assert not p.is_symlink(); shutil.rmtree(p) if p.exists() else None' "$release_root/runtime-python"
# Actual ARM import and primitive roundtrip are required on the native builder.
PYTHONPATH="$release_root/runtime-python" python3 -B -s -c 'import pathlib,sys,cryptography; from cryptography.hazmat.primitives import hashes; from cryptography.hazmat.primitives.asymmetric import ec; assert pathlib.Path(cryptography.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve()); assert cryptography.__version__ == "49.0.0"; key=ec.generate_private_key(ec.SECP256R1()); msg=b"rosy-receiver-build-proof"; sig=key.sign(msg, ec.ECDSA(hashes.SHA256())); key.public_key().verify(sig,msg,ec.ECDSA(hashes.SHA256())); print("receiver crypto ARM import/sign/verify PASS")' "$release_root/runtime-python"
