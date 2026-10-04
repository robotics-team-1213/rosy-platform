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


def _timed_session():
    """시계·타이머·지연 응답을 손으로 돌리는 세션(송신 타이밍 시험용)."""
    return """
let clock = 0;
const timers = [];
const posts = [];
const inflight = [];
const latencies = [];
function make(opts = {}) {
  return link.createDeviceSession({
    token: 'T',
    openSocket: () => ({send() {}, close() {}}),
    schedule: (fn, ms) => { const t = {fn, at: clock + ms, live: true}; timers.push(t); return () => { t.live = false; }; },
    now: () => clock,
    postJson: (path, body, options) => {
      posts.push({body, at: clock, options});
      if (opts.fail) return Promise.reject(new Error('AbortError'));
      if (opts.hold) return new Promise(resolve => inflight.push(resolve));
      return Promise.resolve({status: 200});
    },
    whoami: async () => ({}),
    onLatency: (ms, failed) => latencies.push({ms, failed}),
  });
}
async function advance(ms) {
  const end = clock + ms;
  for (;;) {
    const due = timers.filter(t => t.live && t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    clock = due.at; due.live = false; due.fn();
    await Promise.resolve(); await Promise.resolve();
  }
  clock = end;
}
const flush = async () => { for (let i = 0; i < 4; i += 1) await Promise.resolve(); };
"""


def test_send_interval_is_measured_from_send_start_not_response():
    """응답이 90ms 걸려도 100ms 틱마다 한 번씩 나간다(옛 코드는 응답 시각 기준이라 주기가 두 배로 늘었다)."""
    out = _run_js(_timed_session() + """
    const s = make({hold: true});
    for (let tick = 0; tick < 5; tick += 1) {
      s.command({linear: 0.1, angular: 0});
      clock += 90; inflight.shift()?.({status: 200}); await flush();
      await advance(10);
    }
    console.log(JSON.stringify({sent: posts.length, spacing: posts.map((p, i) => i ? p.at - posts[i - 1].at : 0).slice(1)}));
    """)
    assert out["sent"] == 5
    assert all(gap <= 100 for gap in out["spacing"])


def test_only_one_request_in_flight_and_latest_command_wins():
    out = _run_js(_timed_session() + """
    const s = make({hold: true});
    s.command({linear: 0.1, angular: 0});
    clock += 150;
    s.command({linear: 0.2, angular: 0});
    s.command({linear: 0.3, angular: 0});      // 비행 중 — 최신 것만 남는다
    const whileFlying = posts.length;
    inflight.shift()({status: 200}); await flush();
    await advance(0);                          // 비행이 끝나면 남은 최신 명령을 바로 보낸다
    console.log(JSON.stringify({whileFlying, after: posts.map(p => p.body.linear)}));
    """)
    assert out == {"whileFlying": 1, "after": [0.1, 0.3]}


def test_zero_during_flight_is_sent_now_and_again_after_the_motion_lands():
    """놓는 순간의 0 은 기다리지 않고, 먼저 떠난 움직임이 뒤늦게 도착해도 0 으로 다시 덮는다."""
    out = _run_js(_timed_session() + """
    const s = make({hold: true});
    s.command({linear: 0.1, angular: 0});
    s.zero();
    const immediate = posts.map(p => p.body.linear);
    inflight.shift()({status: 200}); await flush();
    inflight.shift()?.({status: 200}); await flush();
    inflight.shift()?.({status: 200}); await flush();
    console.log(JSON.stringify({immediate, all: posts.map(p => p.body.linear)}));
    """)
    assert out["immediate"] == [0.1, 0]
    assert out["all"][-1] == 0 and out["all"].count(0) >= 2


def test_idle_goes_quiet_after_three_zeros_and_timeout_does_not_throw():
    out = _run_js(_timed_session() + """
    const s = make();
    await s.command({linear: 0.1, angular: 0});
    for (let i = 0; i < 8; i += 1) { await advance(100); await s.command({linear: 0, angular: 0}); }
    const zeros = posts.filter(p => p.body.linear === 0).length;
    const failing = make({fail: true});
    clock += 1000;
    let threw = false;
    try { await failing.command({linear: 0.1, angular: 0}); } catch (e) { threw = true; }
    console.log(JSON.stringify({zeros, threw, timeoutPassed: posts.at(-1).options?.timeoutMs,
                                failedReported: latencies.at(-1).failed}));
    """)
    assert out == {"zeros": 3, "threw": False, "timeoutPassed": 400, "failedReported": True}


def test_resume_after_409_allows_commands_again():
    out = _run_js(_harness() + """
    let status = 409;
    const h = makeSession({postJson: (path, body) => { h.posts.push({body}); return Promise.resolve({status, body: {detail: {code: 'MODE_CONFLICT'}}}); }});
    h.session.open();
    connect(h.sockets[0]);
    await h.session.command({linear: 0.1, angular: 0});
    const blocked = h.session.blocked();
    status = 200;
    h.session.resume();
    await h.session.command({linear: 0.1, angular: 0});
    fireTimers(h.timers); await Promise.resolve(); await Promise.resolve();
    console.log(JSON.stringify({blocked, unblocked: !h.session.blocked(), posts: h.posts.length, state: h.states.at(-1)}));
    """)
    assert out == {"blocked": True, "unblocked": True, "posts": 2, "state": "OPEN"}


def test_close_stops_every_reconnect():
    """나간 주행 화면의 세션이 백오프로 영원히 재접속하지 않는다."""
    out = _run_js(_harness() + """
    const h = makeSession();
    h.session.open();
    connect(h.sockets[0]);
    const socket = h.sockets[0];
    h.session.close();
    socket.onclose?.({code: 1006});            // 브라우저가 늦게 닫힘을 알려도
    fireTimers(h.timers);
    console.log(JSON.stringify({sockets: h.sockets.length, handlerDetached: socket.onclose === null}));
    """)
    assert out == {"sockets": 1, "handlerDetached": True}


def test_visible_does_not_undo_a_409_block():
    out = _run_js(_harness() + """
    const h = makeSession({postJson: (path, body) => { h.posts.push({body}); return Promise.resolve({status: 409, body: {detail: {code: 'MODE_CONFLICT'}}}); }});
    h.session.open();
    connect(h.sockets[0]);
    await h.session.command({linear: 0.1, angular: 0});
    h.session.hidden();
    h.session.visible();
    const before = h.posts.length;
    await h.session.command({linear: 0.1, angular: 0});
    console.log(JSON.stringify({stillBlocked: h.session.blocked(), sent: h.posts.length - before}));
    """)
    assert out == {"stillBlocked": True, "sent": 0}


def test_rezero_waits_for_the_overlapping_motion_to_settle():
    """0 이 움직임보다 먼저 끝나도, 움직임이 끝난 뒤에 0 을 한 번 더 보낸다."""
    out = _run_js(_timed_session() + """
    const s = make({hold: true});
    s.command({linear: 0.1, angular: 0});      // 움직임 비행 중
    s.zero();                                  // 0 이 끼어든다
    inflight[1]({status: 200}); await flush(); // 0 이 먼저 끝남 — 아직 다시 덮으면 안 된다
    const afterZero = posts.map(p => p.body.linear);
    inflight[0]({status: 200}); await flush(); // 움직임이 늦게 끝남 — 이제 0 을 덮는다
    console.log(JSON.stringify({afterZero, final: posts.map(p => p.body.linear)}));
    """)
    assert out == {"afterZero": [0.1, 0], "final": [0.1, 0, 0]}
