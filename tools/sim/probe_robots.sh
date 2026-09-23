#!/bin/bash
# 로봇 상태 프로브 — WSL 내부에서 두 CORE 직접 조회
echo "--- rosy_02 swarm/state ---"
curl -s --max-time 4 http://127.0.0.1:18081/api/v1/swarm/state | head -c 400
echo
echo "--- rosy_01 robot/state ---"
curl -s --max-time 4 http://127.0.0.1:18080/api/v1/robot/state | head -c 400
echo
echo "--- rosy_02 robot/state ---"
curl -s --max-time 4 http://127.0.0.1:18081/api/v1/robot/state | head -c 400
echo
