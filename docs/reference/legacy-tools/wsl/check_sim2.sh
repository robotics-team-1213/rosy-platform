#!/usr/bin/env bash
# 현재 런치의 로그 확인(일회성) — HOME=/ 이라 /.ros/log 에 쌓인다
logdir=$(ls -td /.ros/log/*/ 2>/dev/null | head -1)
echo "logdir: $logdir"
tail -n 45 "$logdir/launch.log" 2>/dev/null || echo "no launch.log yet"
