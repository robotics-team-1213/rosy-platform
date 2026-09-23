#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "--- ros2 launch 프로세스 ---"
ps aux | grep -E '[r]os2 launch|[g]z sim' | awk '{print $2, $3"%", $11, $12, $13}' | head -4
echo "--- gz log 전체 ---"
cat /tmp/rosy_gz.log
echo "--- 재기동: 잔존 정리 후 1회 ---"
pkill -9 -f '[r]os2 launch' 2>/dev/null
pkill -9 -f '[g]z sim' 2>/dev/null
pkill -9 -f '[p]arameter_bridge' 2>/dev/null
sleep 3
cd "$REPO"
setsid nohup "$REPO/tools/run_fleet_sim.sh" 2 > /tmp/rosy_sim7.log 2>&1 < /dev/null &
sleep 5
head -6 /tmp/rosy_sim7.log
