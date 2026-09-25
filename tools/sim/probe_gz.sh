#!/bin/bash
echo "--- gz log (이번 실행 오류) ---"
grep -a -E 'participant index|Error|error|died' /tmp/rosy_gz.log 2>/dev/null | head -6
echo "--- yaml 지금 존재? ---"
ls -t /tmp/rosy_gz_multi_*/robots.yaml 2>/dev/null | head -2
echo "--- gz 프로세스 생존? ---"
ps aux | grep -E '[g]z sim|[g]zserver|[g]z_multi' | awk '{print $2, $11, $12}' | head -4
echo "--- 코어 프로세스 ---"
ps aux | grep '[l]ib/runtime/core' | wc -l
