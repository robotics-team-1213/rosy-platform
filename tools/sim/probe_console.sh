#!/bin/bash
echo "--- 콘솔 프로세스 ---"
ps aux | grep '[c]li.py console' | head -2
echo "--- 8090 청취 ---"
ss -tlnp 2>/dev/null | grep 8090 || echo "무청취"
echo "--- gz/코어/컨트롤 프로세스 수 ---"
ps aux | grep -cE '[g]z sim|[l]ib/core/core|[r]os2 launch|[c]omponent_container'
echo "--- 콘솔 stdout (sim6.log 마지막) ---"
tail -2 /tmp/rosy_sim6.log 2>/dev/null
echo "--- 백그라운드 검증 스크립트 생존 ---"
ps aux | grep '[s]im_verify' | wc -l
