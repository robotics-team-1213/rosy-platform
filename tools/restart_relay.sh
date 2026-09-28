#!/usr/bin/env bash
# 오래된 릴레이 정리 후 재기동, 상태 확인까지
for pid in $(pgrep -f "sim_jpeg_relay.py"); do kill -9 "$pid" 2>/dev/null; done
sleep 1
bash /rosy/tools/start_relay_only.sh
sleep 10
echo "==relay log tail=="
tail -3 /tmp/rosy_relay.log
echo "==core vision=="
curl -s -H "Authorization: Bearer rosy-dev-operator" http://127.0.0.1:8080/api/v1/vision/front/status
echo
