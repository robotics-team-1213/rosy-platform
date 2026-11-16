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
shift 2
exec "$@"
