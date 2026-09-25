#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# D-131 실시간 검증 — 시뮬 기동 + T6 선택 편성 + 리더 주행 + 증거 수집.
# LOCAL 증거다(D-91): DEVICE/FIELD 주장이 아니다. 한 세션 안에서 전 과정을 완주한다.
set -u
cd "$REPO"
BASE=http://127.0.0.1:8090

echo "[0] cleanup"
# launch 가 남긴 자식 트리 전체를 정리한다 — killall python3/gz 만으로는
# component_container·robot_state_publisher·CORE 프로세스 등이 고아로 누적된다.
pkill -9 -f 'ros2 launch' 2>/dev/null || true
pkill -9 -f 'component_container' 2>/dev/null || true
pkill -9 -f 'robot_state_publisher' 2>/dev/null || true
pkill -9 -f 'joint_state_publisher' 2>/dev/null || true
pkill -9 -f 'parameter_bridge' 2>/dev/null || true
pkill -9 -f 'ros_gz' 2>/dev/null || true
pkill -9 -f 'cli.py console' 2>/dev/null || true
pkill -9 -f 'run_fleet_sim' 2>/dev/null || true
pkill -9 -f 'lib/runtime/core' 2>/dev/null || true
killall -9 gz ruby gzserver python3 create 2>/dev/null || true
sleep 10

echo "[1] launch sim"
setsid nohup "$REPO/tools/run_fleet_sim.sh" 2 > /tmp/rosy_sim6.log 2>&1 < /dev/null &

echo "[2] wait console"
up=0
for i in $(seq 1 90); do
  curl -s --max-time 2 $BASE/api/fleet/state > /dev/null 2>&1 && { up=1; break; }
  sleep 5
done
if [ $up -ne 1 ]; then echo "FAIL: console never came up"; tail -5 /tmp/rosy_sim6.log; exit 1; fi
echo "console up"

echo "[3] wait robots 2/2 online"
ok=0
for i in $(seq 1 60); do
  curl -s --max-time 3 $BASE/api/fleet/state > /tmp/ev_state.json 2>/dev/null || true
  grep -q '"online":2' /tmp/ev_state.json 2>/dev/null && { ok=1; break; }
  sleep 5
done
if [ $ok -ne 1 ]; then echo "FAIL: robots not 2/2"; cat /tmp/ev_state.json 2>/dev/null | head -c 400; exit 1; fi
echo "robots 2/2 online"

echo "[4] tokens (D-129)"
curl -s -o /dev/null -w "tokens: %{http_code}\n" --max-time 5 $BASE/ui/tokens.css

echo "[5] arm formation (T6 members: leader + rosy_02)"
curl -s --max-time 20 -X POST $BASE/api/fleet/formation/start \
  -H 'Content-Type: application/json' \
  -d '{"leader":"rosy_01","formation":"COLUMN","spacing":0.6,"members":["rosy_01","rosy_02"]}' > /tmp/ev_arm.json
head -c 300 /tmp/ev_arm.json; echo

echo "[6] drive the leader (+1.0m x)"
curl -s --max-time 5 $BASE/api/fleet/state > /tmp/ev_state.json
read NX NY < <(python3 -c "import json; p=json.load(open('/tmp/ev_state.json'))['robots'][0]['state']['pose']; print(round(p['x']+1.0,2), round(p['y'],2))")
echo "leader goal -> ($NX, $NY)"
curl -s --max-time 10 -X POST $BASE/api/fleet/robots/rosy_01/goal \
  -H 'Content-Type: application/json' \
  -d "{\"x\":$NX,\"y\":$NY,\"yaw\":0}" | head -c 200; echo

echo "[7] sample formation while driving"
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 5
  curl -s --max-time 5 $BASE/api/fleet/state > /tmp/ev_state_now.json
  curl -s --max-time 5 $BASE/api/fleet/formation > /tmp/ev_form_$i.json
  python3 -c "
import json, math
f = json.load(open('/tmp/ev_form_$i.json'))
s = json.load(open('/tmp/ev_state_now.json'))
poses = {r['robot_id']: (r.get('state') or {}).get('pose') for r in s['robots']}
lead = poses.get(f.get('leader'))
r = f.get('relay') or {}
print('sample $i:', f.get('state'), '| leader_hz', r.get('leader_rx_hz'), '| age', r.get('leader_age_s'), '| tx', r.get('follower_tx_hz'), '| conn', r.get('follower_connected'))
if lead and f.get('active'):
    for rid, off in (f.get('assignment') or {}).items():
        p = poses.get(rid)
        if not p or not lead.get('yaw') and lead.get('yaw') != 0: continue
        hx, hy = math.cos(lead['yaw']), math.sin(lead['yaw'])
        lx, ly = -math.sin(lead['yaw']), math.cos(lead['yaw'])
        wx = lead['x'] - off['distance']*hx + off['lateral']*lx
        wy = lead['y'] - off['distance']*hy + off['lateral']*ly
        if p:
            print('   ', rid, 'slot(%.2f, %.2f)' % (wx, wy), 'pose(%.2f, %.2f)' % (p['x'], p['y']), 'err %.3fm' % math.hypot(p['x']-wx, p['y']-wy))
        else:
            print('   ', rid, 'slot(%.2f, %.2f)' % (wx, wy), 'pose 없음')
"
done

echo "[8] done — evidence in /tmp/ev_*.json"
tail -2 /tmp/rosy_sim6.log
