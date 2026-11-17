#!/usr/bin/env bash
# D-866 §4: run a GPU batch job (training, seed sweep) on a lab PC under a `gpu` lock in ~/rosy-jobs. host_probe
# then counts the PC's simulator slot as taken and subtracts the cores and GB from the test budget. exec keeps
# the lock's pid the job's own, so the lock stops counting the moment the job ends, however it ends.
# Usage: tools/remote/hold_gpu.sh <cores> <GB> <command...>
set -eu
[[ $1 =~ ^[0-9]+$ && $2 =~ ^[0-9]+$ ]] || { echo "usage: hold_gpu.sh <cores> <GB> <command...>" >&2; exit 2; }
mkdir -p ~/rosy-jobs && echo "$$ gpu $1 $2" > ~/rosy-jobs/train-$$.lock
# 2026-11-17: an early-stop probe ran CPU inference at 14 cores under an 8-core lock and pushed every test to serial;
# children inherit the lock's core budget as their thread pool size unless the caller set one.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-$1}" MKL_NUM_THREADS="${MKL_NUM_THREADS:-$1}"
# 2026-11-17: on a PC whose Ollama loads models on demand (marker ~/rosy-jobs/ollama-on-demand; the model PC, not the AI PC
# whose lending D-958 gpu_tenants owns) a model left resident is unloaded first (one sat 4 days at keep_alive -1, 7.9 GB);
# the next request loads it again. Ollama down or slow never blocks the job.
if [ -e ~/rosy-jobs/ollama-on-demand ]; then
  url="${ROSY_OLLAMA_URL:-http://127.0.0.1:11434}"
  for m in $(curl -s --max-time 3 "$url/api/ps" | python3 -c 'import json,sys; print(" ".join(m["name"] for m in json.load(sys.stdin).get("models", [])))' 2>/dev/null); do
    curl -s --max-time 10 "$url/api/generate" -d "{\"model\": \"$m\", \"keep_alive\": 0}" >/dev/null && echo "hold_gpu: unloaded Ollama model $m" >&2 || true
  done
fi
shift 2
exec "$@"
