"""D-323 T4 — link.js DeviceSession 상태머신. Node 서브프로세스 패턴."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "link.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const link = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def _harness():
    return """
const sockets = [];
const timers = [];
const posts = [];
const whoamiCalls = [];
const states = [];
const conflicts = [];
function makeSession(overrides = {}) {
  // 세션마다 독립 배열 — 한 시험에서 여러 세션을 만들어도 오염되지 않는다.
  const own = {sockets: [], timers: [], posts: [], whoamiCalls: [], states: [], conflicts: []};
  const openSocket = (url) => {
    const socket = {url, sent: [], closed: [], open: false};
    socket.send = (raw) => socket.sent.push(JSON.parse(raw));
    socket.close = (code) => socket.closed.push(code);
    own.sockets.push(socket);
    return socket;
  };
  const schedule = (fn, ms) => { own.timers.push({fn, ms}); return () => {}; };
  const postJson = overrides.postJson || ((path, body) => {
    own.posts.push({path, body});
    return Promise.resolve({status: 200});
  });
  return {
    session: link.createDeviceSession({
      token: 'T',
      openSocket,
      schedule,
      postJson,
      whoami: overrides.whoami || (async () => { own.whoamiCalls.push(1); return {role: 'operator'}; }),
      onState: (s) => own.states.push(s),
      onConflict: (c) => own.conflicts.push(c),
    }),
    ...own,
  };
}
const fireTimers = (timers) => { const pending = timers.splice(0); pending.forEach(t => t.fn()); };
const connect = (socket, snapshot = {type: 'state'}) => {
  socket.open = true;
  socket.onopen?.();
  socket.onmessage?.({data: JSON.stringify(snapshot)});
};
"""


def test_first_frame_is_auth_then_open_and_snapshots_flow():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    connect(h.sockets[0]);
    h.sockets[0].onmessage({data: JSON.stringify({type: 'state', battery: 7.4})});
    console.log(JSON.stringify({
      firstFrame: h.sockets[0].sent[0],
      state: h.states.at(-1),
    }));
    """)
    assert out["firstFrame"] == {"type": "auth", "token": "T"}
    assert out["state"] == "OPEN"


def test_close_4403_is_forbidden_and_never_retries():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    connect(h.sockets[0]);
    h.sockets[0].open = false;
    h.sockets[0].onclose?.({code: 4403});
    fireTimers(h.timers);
    console.log(JSON.stringify({
      state: h.states.at(-1),
      sockets: h.sockets.length,
      timers: h.timers.length,
    }));
    """)
    assert out["state"] == "FORBIDDEN"
    assert out["sockets"] == 1 and out["timers"] == 0


def test_other_closes_back_off_monotonically_capped_at_30s():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    const delays = [];
    for (let i = 0; i < 7; i++) {
      const socket = h.sockets.at(-1);
      socket.open = true; socket.onopen?.();
      socket.open = false; socket.onclose?.({code: 1006});
      if (h.timers.length) delays.push(h.timers[0].ms);
      fireTimers(h.timers);
    }
    console.log(JSON.stringify({delays, state: h.states.at(-1)}));
    """)
    assert out["delays"] == [1000, 2000, 4000, 8000, 16000, 30000, 30000]
    # 마지막 재접속 타이머까지 발화했으므로 세션은 다시 연결 시도 중이다.
    assert out["state"] == "CONNECTING"


def test_successful_reopen_resets_backoff():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    for (let i = 0; i < 3; i++) {
      const socket = h.sockets.at(-1);
      socket.open = true; socket.onopen?.();
      socket.open = false; socket.onclose?.({code: 1006});
      fireTimers(h.timers);
    }
    connect(h.sockets.at(-1));
    h.sockets.at(-1).open = false;
    h.sockets.at(-1).onclose?.({code: 1006});
    console.log(JSON.stringify({nextDelay: h.timers[0].ms}));
    """)
    assert out["nextDelay"] == 1000


def test_close_4401_rechecks_whoami_and_reconnects_or_stops():
    out = _run_js(_harness() + """
    const ok = makeSession();
    ok.session.open();
    connect(ok.sockets[0]);
    ok.sockets[0].open = false; ok.sockets[0].onclose?.({code: 4401});
    for (let i = 0; i < 5; i++) await Promise.resolve();
    const refused = makeSession({whoami: async () => { throw new Error('401'); }});
    refused.session.open();
    connect(refused.sockets[0]);
    refused.sockets[0].open = false; refused.sockets[0].onclose?.({code: 4401});
    for (let i = 0; i < 5; i++) await Promise.resolve();
    console.log(JSON.stringify({
      okReconnectScheduled: ok.timers.length === 1,
      okWhoami: ok.whoamiCalls.length === 1,
      refusedState: refused.states.at(-1),
      refusedTimers: refused.timers.length,
    }));
    """)
    assert out == {"okReconnectScheduled": True, "okWhoami": 1,
                   "refusedState": "OFFLINE", "refusedTimers": 0}


def test_command_posts_teleop_throttled_and_hidden_posts_zero_and_blocks():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    connect(h.sockets[0]);
    await h.session.command({linear: 0.1, angular: 0});
    await h.session.command({linear: 0.12, angular: 0});
    h.session.hidden();
    await h.session.command({linear: 0.1, angular: 0});
    console.log(JSON.stringify({
      posts: h.posts.map(p => ({path: p.path, linear: p.body.linear})),
    }));
    """)
    assert out["posts"] == [
        {"path": "/api/v1/teleop", "linear": 0.1},
        {"path": "/api/v1/teleop", "linear": 0},
    ]


def test_conflict_409_halts_commands_and_reports_reason():
    out = _run_js(_harness() + """
    const seen = [];
    const h = makeSession({postJson: (path, body) => {
      seen.push({path, body});
      return Promise.resolve({status: 409, body: {detail: {code: 'CAPABILITY_WITHHELD', message: 'no motion'}}});
    }});
    h.session.open();
    connect(h.sockets[0]);
    await h.session.command({linear: 0.1, angular: 0});
    await h.session.command({linear: 0.2, angular: 0});
    console.log(JSON.stringify({
      posts: seen.length,
      conflicts: h.conflicts.map(c => c.code),
      state: h.states.at(-1),
    }));
    """)
    assert out == {"posts": 1, "conflicts": ["CAPABILITY_WITHHELD"], "state": "BLOCKED"}


def test_unexpected_socket_loss_zeroes_last_command():
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    connect(h.sockets[0]);
    await h.session.command({linear: 0.1, angular: 0});
    h.posts.length = 0;
    h.sockets[0].open = false; h.sockets[0].onclose?.({code: 1006});
    await Promise.resolve();
    console.log(JSON.stringify({
      zeroed: h.posts.length === 1 && h.posts[0].body.linear === 0 && h.posts[0].body.angular === 0,
    }));
    """)
    assert out == {"zeroed": True}
