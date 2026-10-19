"""Dependency recipes for the native test gateway."""

VENV = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; N=$R/venvs/.new-$DEPS; cd "$R/runs/$1"; shift 2
mkdir -p "$R/venvs"
exec 9>"$R/venvs/$DEPS.lock"; flock -x -w 600 9
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] && exit 0
echo "[remote] building $N (CI install inputs changed)"
rm -rf "$N"
# The site PC (Ubuntu 26.04) has no system 3.12; `uv python install 3.12` puts one in ~/.local/bin.
PY=/usr/bin/python3; "$PY" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null || PY=~/.local/bin/python3.12
# D-802: uv is the one installer on every lab PC (host-state deploys it); no pip/venv fallback that differs per PC.
UV=$(command -v uv || ls ~/.local/bin/uv 2>/dev/null || true)
[ -n "$UV" ] || { echo "[remote] uv missing (D-802): sudo python3 deploy/hosts/common/rosy-host-state install <role> --approve uv"; exit 1; }
"$UV" venv -q --seed -p "$PY" "$N"
P="$N/bin/python -m pip -q --disable-pip-version-check --no-cache-dir"
REQ=deploy/robot/pinky_pro/image/device-python-requirements.txt
$P install --require-hashes --no-deps --only-binary=:all: -r "$REQ"
grep -o '^[A-Za-z0-9._-]*==[^ ]*' "$REQ" > "$N/constraints.txt"
"$N/bin/python" - "$N/constraints.txt" deploy/site/requirements-fleet.txt deploy/site/requirements-vision.txt "$N/site-extra.txt" <<'PY'
import re
import sys
from pathlib import Path

normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
pinned = {normalize(line.split("==", 1)[0]) for line in Path(sys.argv[1]).read_text().splitlines()}
extra = (line for filename in sys.argv[2:-1] for line in Path(filename).read_text().splitlines(keepends=True)
         if normalize(line.split("==", 1)[0]) not in pinned)
Path(sys.argv[-1]).write_text("".join(extra))
PY
$P install -c "$N/constraints.txt" -r "$N/site-extra.txt" pytest setuptools wheel flake8 httpx pyyaml \
  jsonschema ext4 numpy pillow playwright pytest-xdist==3.8.0
$P install --require-hashes --no-deps --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --target "$N/receiver-crypto" -r deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt
$P wheel --no-deps --no-build-isolation --wheel-dir "$N/wheelhouse" "$@"
$P install --no-deps --no-index "$N"/wheelhouse/*.whl
$P check
echo "$DEPS" > "$N/.deps-sha"
grep -rlI --exclude-dir=__pycache__ "$N" "$N/bin" | xargs -r sed -i "s|$N|$V|g"
mv "$N" "$V"
echo "[remote] ready $V"
"""
