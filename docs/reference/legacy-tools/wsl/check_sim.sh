#!/usr/bin/env bash
# 런치 로그 확인(일회성)
logdir=$(ls -td /root/.ros/log/*/ 2>/dev/null | head -1)
echo "logdir: $logdir"
tail -n 40 "$logdir/launch.log" 2>/dev/null || echo "no launch.log"
echo "=== processes ==="
ps aux | grep -E "gz sim|ruby|parameter_bridge|core" | grep -v grep | head -5 || true
