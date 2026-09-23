#!/bin/bash
BASE=http://127.0.0.1:8090
for i in 1 2 3 4 5 6 7 8; do
  echo "=== 관측 $i ==="
  curl -s --max-time 25 $BASE/api/fleet/state | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('online:', d['fleet']['online'], '/', d['fleet']['total'])
    for r in d['robots']:
        st = r.get('state') or {}
        p = st.get('pose') or {}
        print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| pose', round(p.get('x',0),3), round(p.get('y',0),3))
except Exception as e:
    print('state 파싱 실패:', e)
"
  curl -s --max-time 25 $BASE/api/fleet/formation | python3 -c "
import json, sys
try:
    f = json.load(sys.stdin)
    r = f.get('relay') or {}
    tx = (r.get('follower_tx_hz') or {}).get('rosy_02')
    print('formation:', f.get('state'), '| leader_hz', r.get('leader_rx_hz'), '| tx_hz', tx, '| err', (r.get('follower_last_error') or {}).get('rosy_02'))
except Exception as e:
    print('formation 파싱 실패:', e)
"
  sleep 8
done
