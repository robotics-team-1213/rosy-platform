#!/bin/bash
echo "--- 최신 yaml ---"
Y=$(ls -t /tmp/rosy_gz_multi_*/robots.yaml 2>/dev/null | head -1)
ls -la "$Y" 2>/dev/null
grep -c 'robot_id' "$Y" 2>/dev/null
echo "--- 콘솔/코어 프로세스 ---"
ps aux | grep -E '[c]li.py console|[l]ib/runtime/core' | awk '{print $2, $14, $15, $16}' | head -5
echo "--- fleet state (60s 여유) ---"
curl -s --max-time 60 http://127.0.0.1:8090/api/fleet/state | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('online:', d['fleet']['online'], '/', d['fleet']['total'])
for r in d['robots']:
    st = r.get('state') or {}
    p = st.get('pose') or {}
    print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| map', st.get('map_id'), '| pose', round(p.get('x',0),3), round(p.get('y',0),3))
" 2>/dev/null || echo "fleet state 응답 없음/실패"
