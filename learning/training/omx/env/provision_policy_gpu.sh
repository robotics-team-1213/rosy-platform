#!/usr/bin/env bash
# Create (or re-verify) the SmolVLA + ACT GPU learning env at a NEW path. Never deletes anything.
#   provision_policy_gpu.sh [VENV_DIR] [--verify-only]
# Default VENV_DIR: $ROSY_POLICY_GPU_VENV or ~/.local/share/rosy-learning/venv-policy-gpu
# Env: ROSY_PYTHON (default python3.12), ROSY_REQUIRE_CUDA=1 (fail instead of warn without a GPU).
# stdout = one JSON receipt; progress and warnings go to stderr.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REQ="$HERE/requirements-policy-gpu.txt"
VENV=""; VERIFY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --verify-only) VERIFY_ONLY=1 ;;
    -h|--help) sed -n '2,6p' "$0" >&2; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) VENV="$arg" ;;
  esac
done
VENV="${VENV:-${ROSY_POLICY_GPU_VENV:-$HOME/.local/share/rosy-learning/venv-policy-gpu}}"
PYBIN="${ROSY_PYTHON:-python3.12}"
log() { echo "[provision] $*" >&2; }
[ -f "$REQ" ] || { echo "missing $REQ" >&2; exit 2; }
REQ_SHA=$(sha256sum "$REQ" | cut -d' ' -f1)
MARKER="$VENV/.rosy-requirements.sha256"

if [ ! -x "$VENV/bin/python" ]; then
  [ "$VERIFY_ONLY" = 1 ] && { echo "no env at $VENV" >&2; exit 3; }
  # Refuse a non-empty directory that is not a venv: it is somebody else's data.
  if [ -e "$VENV" ] && [ -n "$(ls -A "$VENV" 2>/dev/null)" ]; then
    echo "$VENV exists and is not a venv; choose another path" >&2; exit 3
  fi
  mkdir -p "$(dirname "$VENV")"
  if command -v uv >/dev/null 2>&1; then
    log "creating venv with uv at $VENV"
    uv venv --python "$PYBIN" "$VENV" >&2
  else
    log "uv not found; falling back to python -m venv"
    "$PYBIN" -m venv "$VENV" >&2
  fi
fi

if [ "$VERIFY_ONLY" = 0 ] && [ "$(cat "$MARKER" 2>/dev/null || true)" != "$REQ_SHA" ]; then
  log "installing requirements (several GB, one-time)"
  if command -v uv >/dev/null 2>&1; then
    # torch/nvidia wheels exist on both indexes; the +cu128 pin is only on the PyTorch index.
    uv pip install --python "$VENV/bin/python" --index-strategy unsafe-best-match -r "$REQ" >&2
  else
    "$VENV/bin/python" -m pip install -r "$REQ" >&2
  fi
  echo "$REQ_SHA" > "$MARKER"
else
  log "requirements already installed (hash match) or verify-only"
fi

"$VENV/bin/python" -I - "$REQ" "$VENV" "$REQ_SHA" "${ROSY_REQUIRE_CUDA:-0}" <<'PY'
import importlib, importlib.metadata as md, json, sys
req, venv, req_sha, require_cuda = sys.argv[1:5]
pins = {}
for line in open(req, encoding='utf-8'):
    if '==' in line and not line.startswith('#'):
        name, version = line.strip().split('==', 1)
        pins[name.lower().replace('_', '-')] = version
receipt = dict(schema='rosy.learning-env-receipt/1', venv=venv, python=sys.version.split()[0],
               requirements_sha256=req_sha, packages={}, drift={}, imports={}, warnings=[])
for name in ('lerobot', 'torch', 'torchvision', 'transformers', 'safetensors', 'accelerate', 'numpy'):
    try:
        have = md.version(name)
    except md.PackageNotFoundError:
        have = None
    receipt['packages'][name] = have
    if have != pins.get(name):
        receipt['drift'][name] = dict(pinned=pins.get(name), installed=have)
failed = []
for module in ('lerobot.policies.act.modeling_act', 'lerobot.policies.smolvla.modeling_smolvla', 'transformers'):
    try:
        importlib.import_module(module)
        receipt['imports'][module] = 'ok'
    except Exception as exc:  # report every failure, then exit non-zero
        receipt['imports'][module] = f'{type(exc).__name__}: {exc}'[:300]
        failed.append(module)
try:
    import torch
    receipt['cuda'] = dict(available=bool(torch.cuda.is_available()), torch_cuda=torch.version.cuda,
                           device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
except Exception as exc:
    receipt['cuda'] = dict(available=False, error=f'{type(exc).__name__}: {exc}'[:300])
    failed.append('torch')
if not receipt['cuda']['available']:
    receipt['warnings'].append('torch.cuda is not available: GPU training will not work here')
    if require_cuda == '1':
        failed.append('cuda')
if receipt['drift']:
    receipt['warnings'].append('installed versions differ from the pinned file')
receipt['ok'] = not failed
print(json.dumps(receipt, indent=2))
sys.exit(0 if not failed else 1)
PY
