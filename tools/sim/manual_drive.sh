#!/bin/bash
BASE=http://127.0.0.1:8090
T=25

echo "[1] fleet state (느린 gather 허용)"
curl -s --max-time $T $BASE/api/fleet/state > /tmp/ev_state.json
python3 -c "
import json
d = json.load(open('/tmp/ev_state.json'))
print('online:', d['fleet']['online'], '/', d['fleet']['total'])
for r in d['robots']:
    st = r.get('state') or {}
    p = st.get('pose') or {}
    print(' ', r['robot_id'], '| online', r['online'], '| nav', st.get('navigation'), '| pose', round(p.get('x',0),3), round(p.get('y',0),3))
"

echo "[2] arm (T6 members)"
curl -s --max-time $T -X POST $BASE/api/fleet/formation/start \
  -H 'Content-Type: application/json' \
  -d '{"leader":"rosy_01","formation":"COLUMN","spacing":0.6,"members":["rosy_01","rosy_02"]}' > /tmp/ev_arm.json
head -c 400 /tmp/ev_arm.json; echo

echo "[3] drive leader (+1.2m)"
curl -s --max-time $T $BASE/api/fleet/state > /tmp/ev_state.json
read NX NY < <(python3 -c "import json; p=json.load(open('/tmp/ev_state.json'))['robots'][0]['state']['pose']; print(round(p['x']+1.2,2), round(p['y'],2))")
echo "leader goal -> ($NX, $NY)"
curl -s --max-time $T -X POST $BASE/api/fleet/robots/rosy_01/goal \
  -H 'Content-Type: application/json' \
  -d "{\"x\":$NX,\"y\":$NY,\"yaw\":0}" | head -c 200; echo

echo "[4] samples x8 (4s 간격)"
for i in 1 2 3 4 5 6 7 8; do
  sleep 4
  curl -s --max-time $T $BASE/api/fleet/formation > /tmp/ev_form_$i.json
  python3 -c "
import json
f = json.load(open('/tmp/ev_form_$i.json'))
r = f.get('relay') or {}
tx = (r.get('follower_tx_hz') or {}).get('rosy_02')
print('sample $i:', f.get('state'), '| leader_hz', r.get('leader_rx_hz'), '| tx_hz', tx, '| err', (r.get('follower_last_error') or {}).get('rosy_02'))
"
done

echo "[5] 최종 상태"
curl -s --max-time $T $BASE/api/fleet/formation | head -c 400; echo
