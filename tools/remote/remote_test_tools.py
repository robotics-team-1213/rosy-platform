"""Fixed optional dependency recipes rendered by the native test gateway."""

from __future__ import annotations

import hashlib

PROFILE = "pinky-raw"
RAW_REQUIREMENTS = "learning/curation/pinky/requirements-raw.txt"
SD_PROFILE = "sd-writer"
SD_INPUTS = ("tools/remote/powershell-test-tool.json", "tools/remote/sd_test_tools.py")


def validate(profile: str | None) -> None:
    if profile not in (None, PROFILE, SD_PROFILE):
        raise SystemExit(f"[remote-pytest] unknown test-tools profile: {profile!r}")


# Isolated Python ignores ambient PYTHONPATH. Only this fixed target is added;
# distribution metadata and imported module origins must both belong to it.
READINESS = r'''
import importlib
from importlib import metadata
from pathlib import Path
import re
import sys

target, pins = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
sys.path.insert(0, str(target))
normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
expected = dict(line.strip().split("==", 1) for line in pins.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#"))
modules = {"mcap": "mcap", "mcap-ros2-support": "mcap_ros2",
           "numpy": "numpy", "opencv-python-headless": "cv2"}
assert set(expected) == set(modules), "unexpected raw pin closure"
selected = {normalize(d.metadata['Name']): d for d in metadata.distributions(path=[str(target)])}
for name, version in expected.items():
    dist = selected[name]
    assert dist.version == version, (name, dist.version, version)
    assert Path(dist.locate_file('')).resolve().is_relative_to(target), name
    module = importlib.import_module(modules[name])
    origins = ([module.__file__] if getattr(module, '__file__', None)
               else list(getattr(module, '__path__', [])))
    assert origins and all(Path(p).resolve().is_relative_to(target) for p in origins), (name, origins)
    print('[remote] raw import:', name, version, origins, flush=True)
# Resolve each target distribution's active requirements against the selected
# target first and then the isolated interpreter's base environment. This keeps
# the two OpenCV distributions separate while checking the actual raw closure.
from packaging.requirements import Requirement
for dist in selected.values():
    for text in dist.requires or []:
        req = Requirement(text)
        if req.marker and not req.marker.evaluate({'extra': ''}):
            continue
        dependency = selected.get(normalize(req.name))
        version = dependency.version if dependency else metadata.version(req.name)
        assert req.specifier.contains(version, prereleases=True), (dist.metadata['Name'], text, version)
print('[remote] pinky-raw ready:', target, expected, flush=True)
'''

PROFILE_SETUP = r'''
$P install -c "$N/constraints.txt" --target "$N/raw-tools" -r learning/curation/pinky/requirements-raw.txt
cp learning/curation/pinky/requirements-raw.txt "$N/.raw-pins"
"$N/bin/python" -I - "$N/raw-tools" "$N/.raw-pins" <<'ROSY_RAW_READY'
''' + READINESS + r'''
ROSY_RAW_READY
echo pinky-raw > "$N/.test-tools"
'''

PROFILE_JOB = r'''
[ "$(cat "$V/.test-tools" 2>/dev/null)" = pinky-raw ] && \
  [ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$2" ] || { echo "[remote] test-tools context mismatch" >&2; exit 1; }
"$V/bin/python" -I - "$V/raw-tools" "$V/.raw-pins" <<'ROSY_RAW_READY'
''' + READINESS + r'''
ROSY_RAW_READY
[ $? = 0 ] || exit 1
export PYTHONPATH="$V/raw-tools:$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}"
'''


SD_SETUP = r'''
"$N/bin/python" -I tools/remote/sd_test_tools.py install "$N" tools/remote/powershell-test-tool.json
echo sd-writer > "$N/.test-tools"
'''

SD_JOB = r'''
[ "$(cat "$V/.test-tools" 2>/dev/null)" = sd-writer ] && \
  [ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$2" ] || { echo "[remote] test-tools context mismatch" >&2; exit 1; }
"$V/bin/python" -I tools/remote/sd_test_tools.py ready "$V" tools/remote/powershell-test-tool.json || exit 1
export PATH="$V/bin:$V/sd-tools:$PATH"
export POWERSHELL_TELEMETRY_OPTOUT=1 POWERSHELL_DIAGNOSTICS_OPTOUT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
export XDG_CACHE_HOME="$V/sd-state/cache" XDG_CONFIG_HOME="$V/sd-state/config" XDG_DATA_HOME="$V/sd-state/data"
export PSModuleAnalysisCachePath="$V/sd-state/ModuleAnalysisCache"
'''


def inputs(profile: str) -> tuple[str, ...]:
    validate(profile)
    if profile == PROFILE:
        return (RAW_REQUIREMENTS,)
    if profile == SD_PROFILE:
        return SD_INPUTS
    raise SystemExit("[remote-pytest] selected test-tools profile required")


def identity(base: str, blob: str, profile: str = PROFILE) -> str:
    inputs(profile)
    setup, job = (PROFILE_SETUP, PROFILE_JOB) if profile == PROFILE else (SD_SETUP, SD_JOB)
    return hashlib.sha256("\n".join([base, profile, blob, setup, job]).encode()).hexdigest()[:16]


def render_setup(base_recipe: str, profile: str | None) -> str:
    validate(profile)
    setup = SD_SETUP if profile == SD_PROFILE else PROFILE_SETUP
    return base_recipe if profile is None else base_recipe.replace(
        'echo "$DEPS" > "$N/.deps-sha"', setup + '\necho "$DEPS" > "$N/.deps-sha"', 1)


def render_job(base_job: str, profile: str | None) -> str:
    validate(profile)
    # Context validation precedes shift, which otherwise consumes the bound deps.
    boundary = DEFAULT_CONTEXT
    if profile is None:
        return base_job
    if profile == SD_PROFILE:
        return base_job.replace(boundary, SD_JOB, 1)
    return base_job.replace(boundary, PROFILE_JOB, 1).replace(
        'export PYTHONPATH="$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1',
        'export PYTHONUTF8=1', 1)


DEFAULT_CONTEXT = '[ ! -e "$V/.test-tools" ] || { echo "[remote] test-tools context mismatch" >&2; exit 1; }\n'

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
# pytest 9.2 changes setattr restoration for dict-backed State; keep the verified runner version.
$P install -c "$N/constraints.txt" -r "$N/site-extra.txt" pytest==9.1.1 setuptools wheel flake8 httpx pyyaml \
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
