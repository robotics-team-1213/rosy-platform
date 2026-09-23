#!/bin/bash
LATEST=$(ls -td /tmp/rosy_gz_multi_*/ 2>/dev/null | head -1)
echo "yaml dir: $LATEST"
cat "${LATEST}robots.yaml" 2>/dev/null
echo "--- fleet state (30s 여유) ---"
curl -s --max-time 30 http://127.0.0.1:8090/api/fleet/state | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('online:', d['fleet']['online'], '/', d['fleet']['total'])
for r in d['robots']:
    st = r.get('state') or {}
    p = st.get('pose') or {}
    print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| pose', round(p.get('x',0),3), round(p.get('y',0),3))
"
