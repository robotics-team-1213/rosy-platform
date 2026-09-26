#!/bin/bash
echo "--- 코어 프로세스 ---"
ps aux | grep '[l]ib/runtime/gateway' | head -4
echo "--- 18080/18081 청취 ---"
ss -tlnp 2>/dev/null | grep -E '18080|18081' || echo "무청취"
echo "--- yaml ---"
cat /tmp/rosy_gz_multi_*/robots.yaml 2>/dev/null | head -10
echo "--- gz log: core up / 크래시 ---"
grep -a -c 'core up' /tmp/rosy_gz.log 2>/dev/null
grep -a -E 'AttributeError|Traceback|died' /tmp/rosy_gz.log 2>/dev/null | tail -4
echo "--- 코어 직접 curl ---"
curl -s --max-time 3 http://127.0.0.1:18080/api/v1/robot/state | head -c 120 || echo "18080 응답 없음"
