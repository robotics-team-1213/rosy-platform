#!/usr/bin/env bash
# BUILD_GO: decide whether what came out of a build is shippable.
#
# Producing an image is not the gate. This is. It checks the distribution
# directory and, when it can mount the image, the tree inside it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RELEASE_TOOLS="$REPO_ROOT/deploy/release"
PYTHON="${ROSY_PYTHON:-python3}"

DIST="${1:-}"
[[ -n "$DIST" && -d "$DIST" ]] || { echo "usage: verify-artifacts.sh dist/<release-id>" >&2; exit 2; }

fail() { echo "FAIL: $*" >&2; exit 1; }

for required in manifest.json SHA256SUMS SHA256SUMS.sig sbom.spdx.json release-notes.md; do
    [[ -f "$DIST/$required" ]] || fail "missing artifact: $required"
done

compgen -G "$DIST/*.img.xz" >/dev/null || fail "missing compressed image"
compgen -G "$DIST/*.bmap" >/dev/null || fail "missing bmap"

echo "==> manifest"
"$PYTHON" "$RELEASE_TOOLS/manifest.py" "$DIST/manifest.json" --json || fail "manifest rejected"

echo "==> checksums and signature"
PUBLIC_KEY="${ROSY_RELEASE_PUBLIC_KEY:-/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem}"
[[ -f "$PUBLIC_KEY" ]] || fail "trusted release key not found at $PUBLIC_KEY"
"$PYTHON" - "$RELEASE_TOOLS" "$DIST" "$PUBLIC_KEY" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from signing import verify_release_files

rejections = verify_release_files(Path(sys.argv[2]), Path(sys.argv[3]))
for rejection in rejections:
    print(rejection, file=sys.stderr)
sys.exit(1 if rejections else 0)
PY

if [[ -n "${ROSY_IMAGE_MOUNT:-}" ]]; then
    echo "==> image tree ($ROSY_IMAGE_MOUNT)"
    "$PYTHON" - "$RELEASE_TOOLS" "$ROSY_IMAGE_MOUNT" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from image_checks import inspect_image

findings = inspect_image(Path(sys.argv[2]))
for finding in findings:
    print(finding, file=sys.stderr)
sys.exit(1 if findings else 0)
PY
else
    echo "==> image tree SKIPPED — set ROSY_IMAGE_MOUNT to the mounted root."
    echo "    BUILD_GO is not satisfied without it (design 12.2)."
    exit 1
fi

NATIVE_RELEASE_ID="${ROSY_NATIVE_RELEASE_ID:-}"
[[ -n "$NATIVE_RELEASE_ID" ]] \
    || fail "ROSY_NATIVE_RELEASE_ID is required for the native product artifact"
NATIVE_PUBLIC_KEY="${ROSY_NATIVE_RELEASE_PUBLIC_KEY:-$ROSY_IMAGE_MOUNT/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem}"
# D-225 2.2: the factory release is unsigned in the image and signed after
# first boot. The gate proves both halves: the image carries it sealed and
# unsigned, and native_release.py verify() accepts a scratch copy of it with
# the dist's offline factory-release/<id>/SHA256SUMS.sig added.
echo "==> factory native release ($NATIVE_RELEASE_ID): unsigned in the image, signed after first boot"
"$PYTHON" "$SCRIPT_DIR/verify-mounted-image.py" \
    --root "$ROSY_IMAGE_MOUNT" \
    --release-id "$NATIVE_RELEASE_ID" \
    --factory-dist "$DIST" \
    --public-key "$NATIVE_PUBLIC_KEY" \
    || fail "factory native release rejected"

echo "BUILD_GO checks passed for $DIST"
