#!/bin/bash
echo "--- gz log size/tail ---"
wc -c /tmp/rosy_gz.log
tail -c 2000 /tmp/rosy_gz.log | strings | tail -12
echo "--- launch/gz procs ---"
ps aux | grep -E '[r]os2 launch|[g]z sim|[g]zserver' | head -4
