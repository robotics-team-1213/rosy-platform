#!/usr/bin/env bash
# One command for a fresh model PC: preflight -> provision the GPU learning env -> list person-only steps.
#   bootstrap_model_pc.sh --check              report only; changes nothing
#   bootstrap_model_pc.sh [--venv PATH]        preflight, then provision_policy_gpu.sh
# Never installs model code, signing keys or tokens: those stay with a person (printed at the end).
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK=0; VENV=""; MIN_FREE_GB=${ROSY_MIN_FREE_GB:-15}
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --venv) VENV="${2:?--venv needs a path}"; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
FAIL=0
ok()   { echo "  ok    $*"; }
warn() { echo "  WARN  $*"; }
bad()  { echo "  FAIL  $*"; FAIL=1; }

echo "== preflight =="
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  ok "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
else bad "nvidia-smi missing or no GPU (training would be CPU-only)"; fi
if command -v python3.12 >/dev/null 2>&1; then ok "python3.12: $(python3.12 -V)"; else bad "python3.12 not installed"; fi
if command -v uv >/dev/null 2>&1; then ok "uv: $(uv --version)"; else warn "uv not found (provision falls back to python -m venv; uv is faster and preferred)"; fi
LINGER=$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo unknown)
if [ "$LINGER" = yes ]; then ok "linger enabled"; else warn "linger=$LINGER (user services stop at logout; a person runs: sudo loginctl enable-linger $(id -un))"; fi
FREE_GB=$(( $(df -Pk "$HOME" | awk 'NR==2{print $4}') / 1048576 ))
if [ "$FREE_GB" -ge "$MIN_FREE_GB" ]; then ok "free disk in HOME: $FREE_GB GB"; else bad "free disk in HOME: $FREE_GB GB < $MIN_FREE_GB GB"; fi

if [ "$CHECK" = 1 ]; then
  echo "== check only: nothing installed =="
  exit "$FAIL"
fi
if [ "$FAIL" != 0 ]; then echo "preflight failed; fix the FAIL lines first" >&2; exit 1; fi

echo "== provision =="
if [ -n "$VENV" ]; then bash "$HERE/provision_policy_gpu.sh" "$VENV"; else bash "$HERE/provision_policy_gpu.sh"; fi
STATUS=$?

cat <<'TXT'

== person-only steps (not done by this script) ==
 1. Model code: run deploy/site/install-model-code.sh with the release signing PUBLIC key
    (needs the signer; see deploy/model_pc/README.md).
 2. Team HF login: `hf auth login` as the team account. hub_sync upload checks HF whoami and
    refuses any other account (or pass --token-file with a team token file, chmod 600).
 3. Real demonstrations (leader-arm recording) for any model quality beyond the synthetic proof.
Then prove the env with the VENV python (not the system python):
   <venv>/bin/python learning/training/omx/il_proof.py --out <new dir> --device cuda [--smolvla]
   (default venv: ~/.local/share/rosy-learning/venv-policy-gpu)
TXT
exit "$STATUS"