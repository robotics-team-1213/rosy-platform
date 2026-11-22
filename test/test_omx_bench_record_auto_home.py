from test_omx_bench_record import (
    Path, ROOT, SimpleNamespace, UNITS, bench_record, digest, finished, importlib, json, pytest, sys, time,
    _LeaderProc, _arm_s_live_files, _home_with_stages, _leader_for_match, _leader_popen, _setup,
)
from test_omx_bench_record_ui import _load_leader_home, _skip_setup, _stuck_leader

def test_starting_step_never_goes_back_and_clears_when_the_start_ends(tmp_path):
    import bench_record_step as step
    folder = tmp_path / 'session'
    folder.mkdir()
    state, memory = {'status': 'recording', 'folder': str(folder), 'name': 'x'}, {}
    log = folder / 'bench.log'
    aligning = 'follower: phase=aligning; actual_joint=wrist_roll actual=1 target=2 error_deg=4.00 Present_PWM=0 PWM_Limit=300; command_joint=wrist_roll command=1 target=2 error_deg=4.00\n'
    log.write_text('INFO Recording episode 0\n' + aligning)
    assert step.starting_step(state, memory)['starting_step'] == 'aligning'
    log.write_text('x' * 70000 + '\n')  # the log grew past the tail: neither phrase is visible any more
    got = step.starting_step(state, memory)
    assert got['starting_step'] == 'aligning'  # the furthest step reached is kept
    log.write_text('INFO Recording episode 0\n' + aligning + 'follower: aligned; full-arm tracking\n')
    assert step.starting_step(state, memory)['starting_step'] is None
    log.write_text('x' * 70000 + '\n')
    assert step.starting_step(state, memory)['starting_step'] is None  # done stays done
    assert step.starting_step({'status': 'sealed'}, memory) == {'starting_step': None, 'starting_deg_left': None, 'starting_arm': None}
    assert memory == {}
    # arm_ab home: the step shown is the arm that is moving now
    one = step.starting_step({'status': 'homing', 'name': 'home-arm_ab', 'step': 'leader_align', 'step_arm': 'arm_a'}, memory)
    two = step.starting_step({'status': 'homing', 'name': 'home-arm_ab', 'step': 'follower_home', 'step_arm': 'arm_b'}, memory)
    assert (one['starting_step'], one['starting_arm'], two['starting_step'], two['starting_arm']) == ('leader_align', 'arm_a', 'follower_home', 'arm_b')


def test_a_leader_move_over_100_degrees_is_refused_including_a_roll_that_wraps_the_range(tmp_path):
    leader_home, leader = _leader_for_match(tmp_path)  # roll: mount -2048, range 0..4095
    present = {'shoulder_pan': 0, 'shoulder_lift': 1000, 'elbow_flex': 2000, 'wrist_flex': 2000, 'wrist_roll': 4090}
    target = leader_home._match_target([2048, 1000, 2000, 2000, 2049], present, leader)  # follower roll 2049 maps to leader 1, 4089 ticks away
    assert target['wrist_roll'] == 1
    with pytest.raises(ValueError, match=r'wrist_roll이\(가\) 359도'):
        leader_home.check_travel(present, target)
    near = leader_home._match_target([2048, 1000, 2000, 2000, 3000], dict(present, wrist_roll=1123), leader)
    leader_home.check_travel(dict(present, wrist_roll=1123), near)  # 15 degrees: fine
    with pytest.raises(ValueError, match='shoulder_pan'):
        leader_home.check_travel(dict(present, shoulder_pan=0), dict(near, shoulder_pan=1200))  # 105 degrees


def test_bench_v4_sidebar_single_notice_surface_history_and_starting_step():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')

    # 1) Sidebar sections in order and collapsible persistence
    sb_ids = ('sec-goal', 'sec-guide', 'sec-status', 'sec-params', 'sec-notice-history')
    assert 'id="bench-sidebar"' in html
    positions = [html.index(f'id="{sid}"') for sid in sb_ids]
    assert positions == sorted(positions)
    assert 'omx_sb_sec_' in ui_js
    assert 'grid-template-columns:minmax(0,1fr) 376px' in css
    assert 'grid-template-columns:minmax(0,1fr) 500px' in css
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)

    # 2) Single notice surface (#start-reason-bar) and old surfaces no longer write separate messages
    assert 'id="reason-close-btn"' in html
    assert 'function setNotice(' in ui_js and 'function dismissTopNotice(' in ui_js
    assert "$('request-error').textContent" not in ui_js
    assert "$('conn-error')" not in app_js
    assert "$('cam-drift-note')" not in cam_js
    assert 'alert(' not in cam_js

    # 3) Notice history (max 20) and error_kind prefixes
    assert 'id="notice-history"' in html and 'id="notice-history-list"' in html
    assert 'noticeHistory.length>20' in ui_js
    for kind_txt in ('거절됨', '사람 확인 필요', '자동 복구됨'):
        assert kind_txt in ui_js

    # 4) starting_step display
    assert 'id="starting-step-box"' in html
    for step_key in ('follower_home', 'leader_align', 'starting_recorder', 'connecting_cameras', 'aligning'):
        assert step_key in ui_js
    assert 'starting_deg_left' in cam_js


def test_bench_v5_fixed_goal_single_params_table_status_kv_and_1366_collapse():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))

    # 1) Goal fixed at top of sidebar, guide first inside #bench-sidebar-scroll, scroll reset on task select
    assert html.index('id="sec-goal"') < html.index('id="bench-sidebar-scroll"') < html.index('id="sec-guide"') < html.index('id="sec-status"')
    assert re.search(r'\.bench-sidebar\{[^}]*overflow:hidden\}', css)
    assert re.search(r'\.bench-sidebar-scroll\{[^}]*overflow-y:auto', css)
    assert 'sbScroll.scrollTop=0' in app_js

    # 2) Single parameter table without duplicate summary rows, clear timing label
    assert 'id="goal-meta-rows"' not in html
    assert 'id="sb-params-kv"' in html
    assert "'회차 길이 '+epTime+' · 사이 대기 '+rstTime" in ui_js

    # 3) Status kv rows without placeholder message
    assert '모터 관측 대기 (미확인)' not in html and '모터 관측 대기 (미확인)' not in ui_js
    for st_id in ('sb-st-follower', 'sb-st-leader', 'sb-st-torque', 'sb-st-hold', 'sb-st-phase'):
        assert f'id="{st_id}"' in html, st_id
    assert 'function renderStatusKv()' in ui_js

    # 4) Guide stays open at <= 1366px while preserving user toggle persistence
    assert "el.id==='sec-guide'&&narrow1366" not in ui_js and 'omx_sb_sec_' in ui_js

    # 5) Notice strip (+N건) button expands and scrolls to notice history
    assert 'id="reason-more-btn"' in html
    assert "hist.open=true;hist.scrollIntoView({block:'start'})" in app_js


def test_bench_v6_two_row_header_red_record_shortcuts_and_arm_cam_filter():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')

    # 1) 2-row header structure and red rounded record button
    for marker in ('id="hdr-row-ops"', 'id="hdr-row-menu"', 'id="hdr-next-ep-btn"',
                   'id="hdr-rerecord-btn"', 'id="hdr-help-btn"', 'id="hdr-refresh-btn"'):
        assert marker in html, marker
    assert html.index('id="hdr-row-menu"') < html.index('id="hdr-row-ops"')
    assert 'class="btn-rec topbar-rec-btn"' in html
    assert '.btn-rec{background:var(--crit);' in css
    assert "record.classList.toggle('is-recording',stopping)" in cam_js
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)

    # 2) Shortcut help section, key bindings, editable-focus guard, and repeat guard
    assert 'id="sec-shortcuts"' in html and 'id="shortcut-help-list"' in html
    for key_marker in ('isEditableTarget', 'if(e.repeat)return;', "e.code==='Space'",
                       "e.key==='ArrowRight'", "e.key==='ArrowLeft'", 'DRAWER_KEYS',
                       "e.key==='?'", "low==='h'", "low==='c'", "low==='x'", "e.shiftKey&&low==='r'"):
        assert key_marker in app_js, key_marker

    # 3) Camera preview filtered by ARM_PREVIEW_CAMS
    assert 'function previewCamsForArm(' in app_js
    assert 'previewCamsForArm(Object.keys(lastCamState),curArm)' in app_js


def test_bench_context_precedes_phase_controls_and_sidebar_has_no_duplicate_summaries():
    import re
    html = (ROOT / 'deploy/robot/omx/bench_record.html').read_text(encoding='utf-8')
    css = (ROOT / 'deploy/robot/omx/bench_record.css').read_text(encoding='utf-8')
    context = re.search(r'<div id="hdr-row-menu"[^>]*>(.*?)<section id="hdr-row-ops"', html, re.S).group(1)
    ops = re.search(r'<section id="hdr-row-ops"[^>]*>(.*?)</section>', html, re.S).group(1)
    context_order = ('h1', 'rail-arm-pills', 'hdr-task-summary', 'goal-name-btn', 'ftr-server',
                     'hdr-cam-health', 'hdr-help-btn', 'btn-drawer-menu', 'hdr-refresh-btn')
    positions = [context.index('<h1>' if marker == 'h1' else f'id="{marker}"') for marker in context_order]
    assert positions == sorted(positions)
    for marker in ('phase-tabs', 'hdr-record-btn', 'hdr-home-btn', 'hdr-next-ep-btn',
                   'hdr-rerecord-btn', 'hdr-live-metrics', 'goal-result-line', 'back-to-setup-btn'):
        assert f'id="{marker}"' in ops
    assert 'role="tab' not in ops
    assert re.search(r'<div class="stop-group">\s*<button[^>]*id="hdr-estop-btn"[^>]*>[^<]+</button>\s*</div>\s*$', ops)
    assert re.search(r'\.topbar-row\{[^}]*flex-wrap:nowrap', css)
    assert re.search(r'\.context-btn\{[^}]*text-overflow:ellipsis', css)

    sidebar = html.split('id="bench-sidebar"', 1)[1].split('</aside>', 1)[0]
    sections = ('sec-goal', 'sec-guide', 'sec-status', 'sec-params',
                'sec-notice-history', 'sec-shortcuts')
    positions = [sidebar.index(f'id="{section}"') for section in sections]
    assert positions == sorted(positions)
    assert 'id="sec-progress"' not in sidebar and 'id="sb-st-phase"' not in sidebar
    for marker in ('btn-sum-setup', 'btn-sum-bindings', 'sb-goal-sum', 'goal-task-id',
                   'sb-params-sum', 'sb-cam-health'):
        assert f'id="{marker}"' not in html


def _early_exit_popen(bench, code, log_line):
    def popen(command, cwd, **kw):
        kw['stdout'].write(log_line.encode())
        kw['stdout'].flush()
        return SimpleNamespace(poll=lambda: code, wait=lambda timeout=None: code, returncode=code, send_signal=lambda s: None)
    bench.popen = popen


def test_a_home_child_that_was_refused_before_any_runner_recovers_by_itself(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    _early_exit_popen(bench, 1, 'REFUSED: arm lease: arm arm_s lease held by robttt@x: runner HOLD (cell_arm_lease.py release-hold)\n')
    with pytest.raises(ValueError, match='REFUSED: arm lease'):  # the child's own reason is shown
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert not bench.manual.exists() and bench.status()['status'] == 'idle'  # no marker, no hold: torque was never on
    assert any(c[0] == 'start' for c in calls) and not bench.pending.exists()  # the stopped units came back
    status = bench.status()
    assert status['error_kind'] == 'recovered' and 'REFUSED' in status['last_issue']['message']
    with pytest.raises(ValueError):
        bench.go_home({'arm': 'arm_x', 'at_bench': True})
    assert bench.status()['error_kind'] == 'refused'


@pytest.mark.parametrize('log', ['', '{"step": "run", "command": ["x"]}\nTraceback (most recent call last):\nREFUSED: x\n'])
def test_without_positive_proof_that_no_runner_started_the_home_still_waits_for_a_person(tmp_path, monkeypatch, log):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    _early_exit_popen(bench, 1, log)
    with pytest.raises(ValueError, match='사람이 팔 상태를 확인'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert bench.manual.exists() and bench.status()['error_kind'] == 'needs_person'


def _held_lease(tmp_path, monkeypatch, pid):
    import cell_arm_lease
    monkeypatch.setenv('ROSY_ARM_LEASES', str(tmp_path / 'leases'))
    cell_arm_lease.claim('arm_s', 'robttt@cell', 'record_session', pid=pid)
    assert cell_arm_lease.hold('arm_s', 'runner HOLD', pid=pid, owner='robttt@cell')
    return cell_arm_lease


def test_a_dead_runners_held_lease_is_cleared_only_with_the_operator_release_proof(tmp_path, monkeypatch):
    import os
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    dead = 4194000
    lease = _held_lease(tmp_path, monkeypatch, dead)
    with pytest.raises(ValueError, match='승인 기록'):  # no proof the runner was released by a person
        bench.release_lease({'arm': 'arm_s'})
    proof = bench.prep / 'chunk-io-s' / 'released.json'
    proof.parent.mkdir()
    proof.write_text(json.dumps({'pid': dead + 1, 'reason': 'operator release (SIGUSR2)', 't': time.time() + 5}))  # another runner's proof
    with pytest.raises(ValueError, match='승인 기록'):
        bench.release_lease({'arm': 'arm_s'})
    proof.write_text(json.dumps({'pid': dead, 'reason': 'operator release (SIGUSR2)', 't': time.time() + 5}))  # no torque-off readback in it
    with pytest.raises(ValueError, match='승인 기록'):
        bench.release_lease({'arm': 'arm_s'})
    proof.write_text(json.dumps({'pid': dead, 'reason': 'operator release (SIGUSR2)', 't': time.time() + 5, 'torque_off_confirmed': True}))
    bench.release_lease({'arm': 'arm_s'})
    assert lease.status('arm_s') == {} and not proof.exists()
    lease = _held_lease(tmp_path, monkeypatch, os.getpid())  # a live runner is never cleared
    with pytest.raises(ValueError, match='살아 있'):
        bench.release_lease({'arm': 'arm_s'})
    lease.release_hold('arm_s', 'robttt@cell')
    _held_lease(tmp_path, monkeypatch, None)  # killed/unconfirmed: no pid, no proof possible
    with pytest.raises(ValueError, match='알 수 없'):
        bench.release_lease({'arm': 'arm_s'})


def test_the_release_proof_is_written_only_after_the_torque_off_readback_succeeded(tmp_path):
    import chunk_runner_interrupt as interrupt

    def run(reason, close):
        runner = SimpleNamespace(hold_file=tmp_path / 'hold.json', _off_approved=reason)
        try:
            interrupt.gated_close(runner, [], tmp_path / 'hold.json', close)
        except RuntimeError:
            pass
    run('folded and still', lambda: None)
    assert not (tmp_path / 'released.json').exists()  # not an operator release
    def failing():
        raise RuntimeError('torque OFF not confirmed')
    run('operator release (SIGUSR2)', failing)
    assert not (tmp_path / 'released.json').exists()  # close_device raised: the readback failed
    run('operator release (SIGUSR2)', lambda: None)
    proof = json.loads((tmp_path / 'released.json').read_text())
    assert proof['torque_off_confirmed'] is True and isinstance(proof['pid'], int)


def test_a_lease_is_deleted_only_if_it_is_still_the_exact_one_that_was_validated(tmp_path, monkeypatch):
    lease = _held_lease(tmp_path, monkeypatch, 4194000)
    validated = lease.status('arm_s')['arm_s']
    lease.release_hold('arm_s', 'robttt@cell')
    lease.claim('arm_s', 'robttt@cell', 'record_session', pid=4194001)  # a newer hold of the same owner appears
    assert lease.hold('arm_s', 'runner HOLD', pid=4194001, owner='robttt@cell')
    assert lease.release_exact('arm_s', validated) is False and lease.status('arm_s')  # a different lease: untouched
    assert lease.release_exact('arm_s', lease.status('arm_s')['arm_s']) is True and lease.status('arm_s') == {}


@pytest.mark.parametrize('log, recovers', [
    ('{"step": "cap", "motor": 11, "value": 8}\nTraceback (most recent call last):\n', False),  # a cap was written and never restored
    ('{"step": "cap", "motor": 11, "value": 8}\nTraceback (most recent call last):\n{"step": "session", "caps_restored": true}\n', True),
    ('Traceback (most recent call last):\n', True),
    ('{"step": "cap_attempt", "motor": 11, "name": "pwm_limit", "value": 300}\nTraceback (most recent call last):\n', False),  # attempted, not confirmed
])
def test_never_started_a_runner_also_needs_no_unrestored_cap(tmp_path, monkeypatch, log, recovers):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    _early_exit_popen(bench, 1, log)
    with pytest.raises(ValueError):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert bench.manual.exists() is not recovers and (bench.status()['error_kind'] == 'recovered') is recovers

_BASELINE_REFUSAL = ("follower 11 caps {'pwm_limit': 300} are not the baseline: an earlier session did not restore them - "
                     "commissioning_limits.py --baseline (torque OFF) before recording\n")


def _baseline_bench(tmp_path, monkeypatch, restore_ok=True, refusals=1, hook=None):
    monkeypatch.setenv('ROSY_ARM_LEASES', str(tmp_path / 'leases'))
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    inner, seen, ran = bench.popen, [], []

    def popen(command, cwd, **kw):
        seen.append(command)
        if len(seen) <= refusals:
            kw['stdout'].write(_BASELINE_REFUSAL.encode())
            kw['stdout'].flush()
            return SimpleNamespace(poll=lambda: 1, wait=lambda timeout=None: 1, returncode=1, send_signal=lambda s: None)
        return inner(command, cwd, **kw)
    bench.popen = popen

    def run(cmd, **kw):
        if cmd[1].endswith('commissioning_limits.py'):
            ran.append(cmd)
            if hook:
                hook()
            return SimpleNamespace(returncode=0 if restore_ok else 2, stderr='',
                                   stdout=json.dumps({'configuration_verified': restore_ok, 'error': None if restore_ok else 'x'}))
        stage = cmd[cmd.index('--stage') + 1]
        receipt = tmp_path / 'receipt.json'
        receipt.write_text(json.dumps({'stage': stage, 'result': 'home'}))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'receipt': str(receipt), 'result': 'home'}) + '\n', stderr='')
    monkeypatch.setattr(bench_record.subprocess, 'run', run)
    return bench, seen, ran


def test_a_baseline_refusal_before_any_runner_is_restored_and_the_home_is_retried_once(tmp_path, monkeypatch):
    bench, seen, ran = _baseline_bench(tmp_path, monkeypatch)
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s']
    assert len(ran) == 1 and '--baseline' in ran[0] and ran[0][ran[0].index('--device') + 1] == '/dev/ttyS'
    assert len(seen) == 2 and not bench.manual.exists()  # refused once, restored, retried


def test_the_baseline_restore_is_not_retried_when_it_fails_the_home_repeats_or_the_lease_is_live(tmp_path, monkeypatch):
    bench, seen, ran = _baseline_bench(tmp_path / 'a', monkeypatch, restore_ok=False)
    started = []
    original_run = bench.run
    bench.run = lambda *args: (started.append(args[0]), original_run(*args))[1]
    with pytest.raises(ValueError, match='baseline 복구가 확인되지 않았습니다'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    # the tool ran and did not verify: it may have written caps, so a person checks them; no retry, the observers stay stopped
    assert len(ran) == 1 and len(seen) == 1 and bench.manual.exists() and 'start' not in started and bench.status()['error_kind'] == 'needs_person'
    bench, seen, ran = _baseline_bench(tmp_path / 'b', monkeypatch, refusals=2)
    with pytest.raises(ValueError, match='are not the baseline'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert len(ran) == 1 and len(seen) == 2  # restored once, refused again: no second restore
    import os
    import cell_arm_lease
    bench, seen, ran = _baseline_bench(tmp_path / 'c', monkeypatch)
    cell_arm_lease.claim('arm_s', 'someone@else', 'calibration', pid=os.getpid())  # a live foreign lease on the arm
    with pytest.raises(ValueError, match='임대가 사용 중'):  # refused even earlier now: before any child runs, so no baseline either
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert ran == [] and seen == []


def test_a_deferred_restore_that_succeeds_clears_the_stale_hold_error(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    bench.pending.write_text(json.dumps(['rosy-omx-camera@top.service']))
    bench.state = {'status': 'idle', 'error': '복원 보류: record_session 또는 chunk_runner가 실행 중이거나 확인할 수 없습니다'}
    bench.restore_leftovers()
    status = bench.status()
    assert 'error' not in status and status['error_kind'] == 'recovered' and status['restore_errors'] == []
    bench.state = {'status': 'idle', 'error': 'something else'}  # only the restore errors are cleared
    bench.pending.write_text(json.dumps(['rosy-omx-camera@top.service']))
    bench.restore_leftovers()
    assert bench.status()['error'] == 'something else'


def test_the_cap_attempt_is_logged_before_the_first_eeprom_write():
    source = (ROOT / 'deploy/robot/omx/record_session.py').read_text(encoding='utf-8')
    body = source[source.index('def write_caps'):]
    assert body.index('step="cap_attempt"') < body.index('bus.write(name, value)')


def test_the_bench_stays_reserved_through_the_baseline_recovery_and_a_stop_cancels_the_retry(tmp_path, monkeypatch):
    from bench_record_guard import hold_arm_lock
    hook = []
    bench, seen, ran = _baseline_bench(tmp_path, monkeypatch, hook=lambda: hook[0]())
    inside = {}

    def during():
        inside['state'] = (bench.status()['status'], bench.state.get('step'))
        inside['units_started'] = any(c[0] == 'start' for c in bench_calls)
        inside['lock'] = hold_arm_lock('arm_s')  # the arm's session lock is the bench's during the recovery
        bench.stop()  # a stop during the recovery
    bench_calls = []
    hook.append(during)
    original_run = bench.run
    bench.run = lambda *args: (bench_calls.append(args), original_run(*args))[1]
    with pytest.raises(ValueError, match='정지 요청'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert inside['state'] == ('homing', 'baseline_restore') and inside['units_started'] is False
    assert len(seen) == 1 and bench.status()['status'] == 'idle'  # no retry
    assert inside['lock'][0] is None and bench._arm_lock is None  # it was held then, and is released with the reservation
    mine, why = hold_arm_lock('arm_s')
    assert mine is not None
    mine.close()
    assert any(c[0] == 'start' for c in bench_calls)  # the observers come back only when the reservation ends


def test_the_auto_home_never_overwrites_a_state_another_request_set(tmp_path, monkeypatch, capsys):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _sealed(bench)
    bench.go_home = lambda body: (setattr(bench, 'state', {'status': 'handing_over', 'name': 'next'}), {'home_moved': ['arm_s']})[1]
    bench._auto_home_after_session()
    assert bench.state == {'status': 'handing_over', 'name': 'next'} and 'not shown' in capsys.readouterr().out
    _sealed(bench)
    bench.go_home = lambda body: (setattr(bench, 'state', {'status': 'idle'}), {'home_moved': ['arm_s']})[1]
    bench._auto_home_after_session()
    assert bench.state['status'] == 'sealed' and bench.state['auto_home']['ok'] is True


def _lease_hold(arm, owner='robttt@cell'):
    import cell_arm_lease
    cell_arm_lease.claim(arm, owner, 'record_session', pid=4194000)
    assert cell_arm_lease.hold(arm, 'runner HOLD', pid=4194000, owner=owner)


def test_a_held_lease_refuses_the_start_and_the_home_before_any_device_is_touched(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    _lease_hold('arm_a')
    ran = _leader_popen(bench, _LeaderProc(), monkeypatch)
    with pytest.raises(ValueError, match='임대가 사용 중'):
        bench.start(dict(body, align_leader=True))
    assert not ran and not commands and not calls  # no alignment child, no recorder, no unit touched
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text('{}')
    with pytest.raises(ValueError, match='임대가 사용 중'):
        bench.go_home({'arm': 'arm_a', 'at_bench': True})
    assert not calls


def test_a_live_lease_of_another_owner_refuses_but_the_benchs_own_live_lease_does_not(tmp_path, monkeypatch):
    import os
    import cell_arm_lease
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    cell_arm_lease.claim('arm_a', 'someone@else', 'calibration', pid=os.getpid())
    with pytest.raises(ValueError, match='someone@else'):
        bench._check_lease('arm_a')
    cell_arm_lease.release('arm_a', 'someone@else')
    cell_arm_lease.claim('arm_a', cell_arm_lease.default_owner(), 'record_session', pid=os.getpid())
    bench._check_lease('arm_a')


def test_the_cell_code_digest_covers_the_split_out_guard_modules():
    source = (ROOT / 'deploy/robot/omx/cell_envelope.py').read_text(encoding='utf-8')
    assert '"guarded_native_track.py"' in source and '"guarded_native_mount.py"' in source
    assert '"guarded_native_lag.py"' in source and '"guarded_native_link.py"' in source


def test_the_auto_home_is_recorded_only_for_the_request_that_owns_the_bench(tmp_path, monkeypatch):
    import threading
    bench, _, _, _ = _setup(tmp_path, monkeypatch)

    def other_request():  # another thread takes the bench and gives it back
        def run():
            with bench.lock:
                bench._claim_bench()
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(5)
        bench.state = {'status': 'idle'}
    _sealed(bench)
    bench.go_home = lambda body: (other_request(), {'home_moved': ['arm_s']})[1]
    bench._auto_home_after_session()
    assert bench.state == {'status': 'idle'}  # back at idle, yet not overwritten with the old session state
    _sealed(bench)

    def refused(body):
        raise ValueError('arm_s 임대가 사용 중입니다')
    bench.go_home = refused  # refused before it reserved the bench: the page shows it on the ended session
    bench._auto_home_after_session()
    assert bench.state['status'] == 'sealed' and bench.state['auto_home']['ok'] is False and '임대' in bench.state['auto_home']['error']

    def reserving(body):
        with bench.lock:
            bench._claim_bench()
        bench.state = {'status': 'idle'}
        return {'home_moved': ['arm_s']}
    _sealed(bench)
    bench.go_home = reserving
    bench._auto_home_after_session()
    assert bench.state['auto_home']['ok'] is True


def test_a_stop_during_the_home_stage_ends_the_runner_through_its_own_safe_path(tmp_path, monkeypatch):
    import signal
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    (bench.prep / 'chunk-io-s').mkdir()
    live, signals, inside = bench.prep / 'chunk-io-s' / 'live.json', [], {}

    def poll():  # the recorder this request started writes its live pose, and keeps running
        live.write_text(json.dumps({'state': [0.0] * 6}))
        return None
    child = SimpleNamespace(poll=poll, wait=lambda timeout=None: 0, returncode=0, send_signal=signals.append)
    bench.popen = lambda command, cwd, **kw: child

    def stage(cmd, **kw):
        bench.stop()  # the person presses Stop while the home stage runs
        inside['signals'] = list(signals)
        receipt = tmp_path / 'receipt.json'
        receipt.write_text(json.dumps({'stage': 'home', 'result': 'stopped', 'error': 'initial live state refused'}))
        return SimpleNamespace(returncode=1, stdout=json.dumps({'receipt': str(receipt), 'result': 'stopped'}) + '\n', stderr='')
    monkeypatch.setattr(bench_record.subprocess, 'run', stage)
    with pytest.raises(ValueError, match='홈 이동 실패'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True, 'include_leader': True})
    assert inside['signals'] == [signal.SIGTERM] and bench.abort is True  # the runner got its own SIGTERM at once, no kill, no torque write
    assert any(c[0] == 'start' for c in calls) and bench.status()['status'] == 'idle'  # nothing later ran (no Leader step), units back


def test_the_baseline_recovery_leaves_a_durable_marker_until_the_result_is_verified(tmp_path, monkeypatch):
    hook, seen_marker = [], {}
    bench, seen, ran = _baseline_bench(tmp_path, monkeypatch, hook=lambda: hook[0]())

    def during():
        seen_marker['reason'] = json.loads(bench.manual.read_text(encoding='utf-8'))['reason'] if bench.manual.exists() else None
        restarted = bench_record.Bench({'python': '/py', 'prep_root': str(bench.prep)}, run=lambda *a: SimpleNamespace(stdout='', returncode=0),
                                       popen=None, procs=lambda: [], mounts=lambda: 'proc /proc proc rw,nosuid 0 0\n')
        restarted.restore_leftovers()  # a service start in the middle of the recovery
        seen_marker['restart'] = restarted.state.get('error')
    hook.append(during)
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s']
    assert '복구 진행 중' in seen_marker['reason'] and '복원 보류' in seen_marker['restart']  # no observer restart without a person
    assert not bench.manual.exists()  # a verified result removed it


def test_a_stale_auto_home_never_moves_the_arm(tmp_path, monkeypatch):
    import threading
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    bench._publish_end(status='sealed', seal_exit=0)

    def another_request(arm):  # between the auto home's pre-checks and its reservation another request takes the bench and gives it back
        def run():
            with bench.lock:
                bench._claim_bench()
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(5)
        bench.state = {'status': 'idle'}
    bench._check_lease = another_request
    bench._auto_home_after_session()
    assert spawned == [] and calls == [] and bench.state == {'status': 'idle'}  # no recorder, no unit touched, nothing overwritten


def test_a_stop_right_after_the_session_ends_cancels_the_auto_home_before_it_moves_anything(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    bench._publish_end(status='sealed', seal_exit=0)  # the ended state and the cancel flag in one lock acquisition
    snapshot = bench.stop()  # the person presses Stop before the auto home reserved
    assert snapshot['auto_home']['message'] == '자동 홈 취소됨' and [r['cancelled'] for r in bench._auto_homes.values()] == [True]
    bench._auto_home_after_session()
    assert spawned == [] and calls == [] and bench._auto_homes == {}  # nothing stopped, nothing spawned, its own record removed
    assert bench.state['status'] == 'sealed' and bench.state['auto_home']['message'] == '자동 홈 취소됨'
    assert bench.stop()['stop_result'] == {'stopped': False, 'message': '정지할 것이 없습니다 — 대기 중입니다'}  # once the auto home is over: a plain 200


def test_the_auto_home_compares_the_claim_taken_when_the_session_ended(tmp_path, monkeypatch):
    import threading
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    bench._publish_end(status='sealed', seal_exit=0)

    def another():  # a request takes the bench (and is gone again) between the session's end and the auto home's start
        with bench.lock:
            bench._claim_bench()
    thread = threading.Thread(target=another)
    thread.start()
    thread.join(5)
    bench._auto_home_after_session()
    assert spawned == [] and calls == []  # the claim taken at the session's end no longer matches at the reservation
    assert bench.state['status'] == 'sealed' and 'auto_home' not in bench.state


def _fake_lerobot(monkeypatch, leader_home, torque=0, connect_error=None):
    import sys
    import types
    events = []

    def read(register, name, normalize=False, num_retry=0):
        return 2048 if register == 'Present_Position' else torque

    def connect():
        if connect_error:
            raise connect_error
    bus = SimpleNamespace(read=read, connect=connect, disconnect=lambda disable_torque=True: events.append(('disconnect', disable_torque)),
                          write=lambda *a, **k: events.append(('write',)), sync_write=lambda *a, **k: events.append(('write',)))
    follower = SimpleNamespace(bus=bus)
    modules = {name: types.ModuleType(name) for name in ('lerobot', 'lerobot.robots', 'lerobot.robots.omx_follower',
                                                         'lerobot.robots.omx_follower.config_omx_follower')}
    modules['lerobot.robots'].make_robot_from_config = lambda cfg: follower
    modules['lerobot.robots.omx_follower.config_omx_follower'].OmxFollowerConfig = lambda **kw: SimpleNamespace(**kw)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    def forbidden(*a, **k):
        raise AssertionError('connect_passive writes the Follower torque OFF: the pose read must not use it')
    monkeypatch.setattr(leader_home.guarded_device, 'connect_passive', forbidden)
    return events


def test_the_follower_pose_read_is_read_only_and_refuses_an_arm_with_torque_on(tmp_path, monkeypatch):
    leader_home = _load_leader_home()
    cfg = tmp_path / 'rcfg.json'
    cfg.write_text(json.dumps({'robot': {'type': 'omx_follower', 'id': 'x', 'port': '/dev/null'}}), encoding='utf-8')
    events = _fake_lerobot(monkeypatch, leader_home)
    assert leader_home.read_follower_pose(cfg, 'arm_a') == [2048] * 6
    assert events == [('disconnect', False)]  # no write of any kind; the port closes without the default torque write
    events = _fake_lerobot(monkeypatch, leader_home, torque=1)
    with pytest.raises(leader_home.FollowerTorqueOn, match='팔로워 토크가 켜져'):
        leader_home.read_follower_pose(cfg, 'arm_a')
    assert events == [('disconnect', False)] and leader_home._END['follower_torque_on'] is True and leader_home._END['torque_off_confirmed'] is True
    events = _fake_lerobot(monkeypatch, leader_home, connect_error=OSError('usb link lost'))
    with pytest.raises(OSError):
        leader_home.read_follower_pose(cfg, 'arm_a')
    assert not [e for e in events if e[0] == 'write']


def test_a_stop_after_the_recording_child_ended_cancels_the_coming_auto_home(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench.state = {'status': 'recording', 'arm': 'arm_s'}
    bench.child = SimpleNamespace(poll=lambda: 0)  # the child just ended, the state is still 'recording'
    assert bench.stop()['auto_home']['message'] == '자동 홈 취소됨'  # no error, no window
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    assert bench.stop()['auto_home']['message'] == '자동 홈 취소됨'  # restoring and sealing too
    bench._publish_end(status='sealed', seal_exit=0)
    assert bench.state['auto_home']['message'] == '자동 홈 취소됨' and [r['cancelled'] for r in bench._auto_homes.values()] == [True]
    bench._auto_home_after_session()
    assert spawned == [] and calls == []
    bench.state, bench.child = {'status': 'idle'}, None
    assert bench.stop()['stop_result']['stopped'] is False  # outside those states Stop answers plainly
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    bench._claim_bench()  # a new session has its own claim: the old stop intent does not apply to it
    bench._publish_end(status='sealed', seal_exit=0)
    assert 'auto_home' not in bench.state and [r['cancelled'] for r in bench._auto_homes.values()] == [False]


def test_a_stop_that_races_the_recording_end_is_never_turned_into_an_error(tmp_path, monkeypatch):
    # the reproduced order: first state read says recording with a child; poll() runs outside the lock; by then the session thread has
    # moved the bench to restoring
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    bench.state = {'status': 'recording', 'arm': 'arm_s'}

    def poll():
        bench._set(status='restoring')
        return 0
    bench.child = SimpleNamespace(poll=poll)
    snapshot = bench.stop()
    assert snapshot['auto_home']['message'] == '자동 홈 취소됨' and bench._session_claim() in bench._pre_cancel
    bench._publish_end(status='sealed', seal_exit=0)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench._auto_home_after_session()
    assert spawned == [] and bench.state['auto_home']['message'] == '자동 홈 취소됨'


def test_a_stop_always_stops_something_or_records_a_cancel_except_for_plain_idle(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    signals = []
    bench.state, bench.child = {'status': 'recording', 'arm': 'arm_s'}, SimpleNamespace(poll=lambda: None, send_signal=signals.append)
    bench.stop()  # a live recording: SIGTERM
    assert len(signals) == 1
    for status in ('restoring', 'sealing'):
        bench.state = {'status': status, 'arm': 'arm_s'}
        bench._pre_cancel.clear()
        bench.stop()
        assert bench._session_claim() in bench._pre_cancel
    bench.state, bench.abort = {'status': 'handing_over'}, False
    bench.stop()
    assert bench.abort is True  # the abort is recorded
    bench.state = {'status': 'idle'}
    assert bench.stop()['stop_result']['stopped'] is False and 'no recording' not in str(bench.stop()['stop_result'])


def test_the_published_end_status_is_decided_under_the_lock_and_returned(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    bench.state = {'status': 'recording', 'arm': 'arm_s'}
    seen = []
    status = bench._publish_end(verdict=lambda state: (seen.append(bench.lock.locked()), {'status': 'stopped_safe'})[1])
    assert status == 'stopped_safe' and seen == [True] and bench.state['status'] == 'stopped_safe'  # judged while the lock is held
    assert list(bench._auto_homes.values()) == [{'cancelled': False, 'reserved': False}]  # its own record


def test_a_stop_accepted_while_recording_cancels_the_auto_home_even_if_the_child_then_exits_by_itself(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    bench.state = {'status': 'recording', 'arm': 'arm_s'}
    bench.child = SimpleNamespace(poll=lambda: None, send_signal=lambda sig: None)  # looked alive; the signal then reaches nobody
    bench.stop()
    assert bench._session_claim() in bench._pre_cancel  # recorded when the stop was accepted
    bench._publish_end(status='stopped_safe')  # the child had just exited normally
    assert bench.state['auto_home']['message'] == '자동 홈 취소됨'
    bench._auto_home_after_session()
    assert spawned == [] and calls == []


def test_an_incident_hold_refuses_every_bench_path_that_opens_a_bus_before_any_child(tmp_path, monkeypatch):
    import omx_incident
    bench, body, calls, _ = _setup(tmp_path, monkeypatch)

    def held(arm, *a, **k):
        raise SystemExit(f'{arm} held for a person: incident open')
    monkeypatch.setattr(omx_incident, 'refuse_if_held', held)  # the function record_session applies, asked by the bench first
    spawned = []
    bench.popen = lambda *a, **kw: spawned.append(a)
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: spawned.append(a))
    for call in (lambda: bench.start(dict(body, align_leader=True)), lambda: bench.go_home({'arm': 'arm_a', 'at_bench': True}),
                 lambda: bench._match_leader('arm_a', 'cfg.json'), lambda: bench.save_leader_pose({'arm': 'arm_a'}),
                 lambda: bench.save_initial_pose({'arm': 'arm_a'})):
        with pytest.raises(ValueError, match='held for a person'):
            call()
    assert spawned == [] and bench.status()['status'] == 'idle'  # no child, no bus touched
    assert bench._baseline_in_place('arm_a', tmp_path / 'none.json', 1, tmp_path / 'none.log') is False


def test_a_hold_recorded_after_the_alignment_checks_but_before_its_lock_stops_the_child(tmp_path, monkeypatch):
    import omx_incident
    import bench_record_leader
    bench, body, calls, _ = _setup(tmp_path, monkeypatch)
    spawned = []
    bench.popen = lambda *a, **kw: spawned.append(a)
    state = {'held': False}

    def refuse(arm, *a, **k):
        if state['held']:
            raise SystemExit(f'{arm} held for a person: late incident')
    monkeypatch.setattr(omx_incident, 'refuse_if_held', refuse)

    def hold(arm, arms, procs, mounts, own=False):
        state['held'] = True  # the other session records its hold and releases the lock just before we get it
        return [], None
    monkeypatch.setattr(bench_record_leader, 'hold_other_arm_locks', hold)
    with pytest.raises(ValueError, match='late incident'):
        bench._match_leader('arm_a', 'cfg.json')
    assert spawned == []


def test_a_person_check_marker_on_disk_blocks_the_pose_saves_after_a_restart(tmp_path, monkeypatch):
    bench, body, calls, _ = _setup(tmp_path, monkeypatch)
    spawned = []
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: spawned.append(a))
    bench.manual.write_text(json.dumps({'reason': 'home end not confirmed'}), encoding='utf-8')  # left by the previous service run
    for call in (lambda: bench.save_initial_pose({'arm': 'arm_a'}), lambda: bench.save_leader_pose({'arm': 'arm_a'})):
        with pytest.raises(ValueError, match='사람 확인'):
            call()
    assert spawned == [] and bench.status()['status'] == 'idle'


def test_the_pose_saves_keep_the_bench_reserved_while_their_child_runs(tmp_path, monkeypatch):
    bench, body, calls, _ = _setup(tmp_path, monkeypatch)
    seen = []

    def run(cmd, **kw):
        seen.append(bench.state['status'])
        try:
            bench.start(body)  # a start meanwhile
        except ValueError as exc:
            seen.append(str(exc)[:6])
        return SimpleNamespace(returncode=1, stdout='', stderr='boom')
    monkeypatch.setattr('subprocess.run', run)
    with pytest.raises(ValueError):
        bench.save_leader_pose({'arm': 'arm_a'})  # the read failed: the error, and the bench is released again
    assert seen[0] == 'homing' and seen[1].startswith('a benc') and bench.status()['status'] == 'idle'


def test_the_declared_teleop_stage_reaches_the_session_command_and_the_status(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    (bench.prep / 'teleop-speed-arm_a.json').write_text('{"stage": 45}')
    assert bench.status()['teleop_speed_declared']['arm_a']['stage'] == 45 and bench.status()['teleop_speed_declared']['arm_b']['stage'] is None
    bench.start(body)
    state = finished(bench)
    command = commands[0]
    assert command[command.index('--teleop-stage') + 1] == '45'
    assert state['teleop_speed'] == {'stage': 45, 'track_deg_s': 45.0, 'profile_vel': 37, 'profile_acc': 16, 'accel_deg_s2': 60.0, 'brake_deg_s2': 690.0, 'tau_s': 0.19, 'align_deg_s': 10.0}


@pytest.mark.parametrize('content', [None, '{"stage": 25}', 'garbage'])
def test_without_a_valid_declaration_the_session_command_and_caps_are_unchanged(tmp_path, monkeypatch, content):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    if content is not None:
        (bench.prep / 'teleop-speed-arm_a.json').write_text(content)
    bench.start(body)
    state = finished(bench)
    assert '--teleop-stage' not in commands[0] and state['teleop_speed'] == {'stage': None, 'track_deg_s': 25.0, 'accel_deg_s2': 10.0, 'brake_deg_s2': 200.0, 'align_deg_s': 1.0}


def _restart_setup(tmp_path, monkeypatch, cameras=('top', 'side')):
    bench, body, calls, _ = _setup(tmp_path, monkeypatch)
    (bench.prep / 'record-config-arm-a.json').write_text(json.dumps({'robot': {'type': 'omx_follower'}, 'cameras': {c: {} for c in cameras}}))
    ran = []

    def run(*args):
        ran.append(args)
        return SimpleNamespace(stdout='active\n' if args[0] == 'is-active' else '', returncode=0)
    bench.run = run
    return bench, ran


def test_restart_cameras_restarts_that_arms_camera_units_then_the_view_and_reports_each(tmp_path, monkeypatch):
    bench, ran = _restart_setup(tmp_path, monkeypatch)
    res = bench.restart_cameras({'arm': 'arm_a'})
    assert [a for a in ran if a[0] == 'restart'] == [('restart', 'rosy-omx-camera@top.service'), ('restart', 'rosy-omx-camera@side.service'),
                                                      ('restart', 'rosy-omx-camera-view.service')]
    assert res['ok'] is True and res['arm'] == 'arm_a' and res['units']['rosy-omx-camera@top.service'] == {'restarted': True, 'active': True}
    assert not any('observer' in a[1] or 'torque' in str(a) for a in ran) and bench.status()['status'] == 'idle'  # no arm unit, bench released again
    bench.run = lambda *a: SimpleNamespace(stdout='failed\n' if a[0] == 'is-active' else '', returncode=0)
    assert bench.restart_cameras({'arm': 'arm_a'})['ok'] is False  # an inactive unit is reported, not hidden
    with pytest.raises(ValueError, match='유효한 팔'):
        bench.restart_cameras({'arm': 'arm_x'})


@pytest.mark.parametrize('status', ['handing_over', 'recording', 'homing', 'restoring', 'sealing', 'leader_manual_check'])
def test_restart_cameras_is_refused_while_anything_owns_the_devices(tmp_path, monkeypatch, status):
    bench, ran = _restart_setup(tmp_path, monkeypatch)
    bench.state = {'status': status}
    with pytest.raises(ValueError, match='재시작할 수 없습니다'):
        bench.restart_cameras({'arm': 'arm_a'})
    assert ran == []


def test_restart_cameras_is_allowed_after_a_session_ended_but_not_with_a_recorder_or_a_pending_restore(tmp_path, monkeypatch):
    bench, ran = _restart_setup(tmp_path, monkeypatch)
    bench.state = {'status': 'sealed', 'name': 'x'}
    assert bench.restart_cameras({'arm': 'arm_a'})['ok'] is True and bench.state == {'status': 'sealed', 'name': 'x'}  # the ended state is kept
    bench.procs = lambda: ['python record_session.py --arm arm_b']
    with pytest.raises(ValueError, match='녹화기'):
        bench.restart_cameras({'arm': 'arm_a'})
    assert bench.state == {'status': 'sealed', 'name': 'x'}
    bench.procs = lambda: []
    bench.pending.write_text('[]')
    with pytest.raises(ValueError, match='복원되지 않아'):
        bench.restart_cameras({'arm': 'arm_a'})


def test_a_leader_child_that_ended_without_a_torque_verdict_also_leaves_the_marker(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    _leader_popen(bench, _LeaderProc(rc=1, out='boom'), monkeypatch)  # no verdict line: torque OFF unconfirmed
    with pytest.raises(ValueError, match='수동'):
        bench.start(dict(body, align_leader=True, hands_off_leader=True))
    assert bench.manual.is_file()


def test_a_pipeline_stage_or_a_pose_read_killed_on_timeout_leaves_the_marker(tmp_path, monkeypatch):
    import subprocess
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired('x', 1)
    monkeypatch.setattr('subprocess.run', timeout)
    with pytest.raises(ValueError, match='시간 초과'):
        bench._pipeline_stage('arm_a', ['cmd'], 'home', {})
    assert bench.manual.is_file()
    bench.manual.unlink()
    with pytest.raises(ValueError, match='시간 초과'):
        bench.save_initial_pose({'arm': 'arm_a'})
    assert bench.manual.is_file()
    bench.manual.unlink()
    import bench_record_replay as brr
    (tmp_path / 'record-config-arm-a.json').write_text('{}')
    assert brr._read_live_norm_pose_held(tmp_path, 'arm_a', '/py') is None
    assert (tmp_path / '.bench-manual-check.json').is_file()


_TORQUE_ON_LINE = '{"ok": false, "torque_off_confirmed": true, "restore_failures": [], "error": "FollowerTorqueOn", "follower_torque_on": true}\n'


def test_an_alignment_child_that_refuses_a_powered_follower_leaves_the_marker_and_the_person_message(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    _leader_popen(bench, _LeaderProc(rc=1, out=_TORQUE_ON_LINE), monkeypatch)
    with pytest.raises(ValueError, match='팔로워 토크가 켜져 있습니다 — 사람이 팔을 받친 뒤 확인'):
        bench.start(dict(body, align_leader=True, hands_off_leader=True))
    assert bench.manual.is_file() and '팔로워 토크가 켜져' in json.loads(bench.manual.read_text(encoding='utf-8'))['reason']
    assert not commands and bench.leader_hold == ''
    with pytest.raises(ValueError, match='사람 확인'):  # a restart or a new request: held for a person until the marker is removed
        bench.start(body)


def test_a_pose_read_that_meets_a_powered_follower_leaves_the_marker_on_every_path(tmp_path, monkeypatch):
    import bench_record_replay as brr
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout=_TORQUE_ON_LINE, stderr=''))
    with pytest.raises(ValueError, match='팔로워 토크가 켜져'):
        bench.save_initial_pose({'arm': 'arm_a'})
    assert bench.manual.is_file()
    bench.manual.unlink()
    (tmp_path / 'record-config-arm-a.json').write_text('{}')
    assert brr._read_live_norm_pose_held(tmp_path, 'arm_a', '/py') is None
    assert '팔로워 토크가 켜져' in json.loads((tmp_path / '.bench-manual-check.json').read_text(encoding='utf-8'))['reason']


def test_the_leader_pose_read_killed_on_timeout_leaves_the_marker(tmp_path, monkeypatch):
    import subprocess
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired('x', 1)
    monkeypatch.setattr('subprocess.run', timeout)
    with pytest.raises(ValueError, match='시간 초과'):
        bench.save_leader_pose({'arm': 'arm_a'})
    assert bench.manual.is_file()


def test_the_baseline_tool_refuses_a_powered_follower_before_any_write():
    import commissioning_limits as cl
    rows = [{'id': motor, 'model_number': 1060 if motor < 14 else 1200, 'torque_enabled': 0, 'hardware_error': 0,
             'operating_mode': 4 if motor < 16 else 5, 'drive_mode': 0, 'velocity_limit_raw': 100, 'pwm_limit_raw': 20,
             'current_limit_raw': None if motor < 14 else 50, 'profile_acceleration_raw': 1, 'profile_velocity_raw': 1} for motor in range(11, 17)]
    cl.validate_motors(rows)  # torque OFF: accepted
    rows[2]['torque_enabled'] = 1
    with pytest.raises(ValueError, match='precondition failed'):  # powered: refused by the planner, which runs before any write
        cl.plan_limits(rows, {'pwm_limit_raw': 20, 'current_limit_raw': 50, 'profile_acceleration_raw': 1, 'profile_velocity_raw': 1})


def test_the_keyboard_stop_always_asks_the_server_and_only_an_open_drawer_takes_the_first_esc():
    js = ((bench_record.HERE / 'bench_record_app.js').read_text(encoding='utf-8') + (bench_record.HERE / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    start = js.index("if(e.key==='Escape'||(e.altKey&&low==='x'))")
    branch = js[start:js.index("if(e.altKey&&low==='r')", start)]
    assert 'BUSY' not in branch and 'lastStatus' not in branch  # no decision from the last-known status
    assert "if(e.key==='Escape'&&$('side-drawer-host')&&!$('side-drawer-host').hidden){e.preventDefault();closeDrawer(true);}" in branch
    assert 'else{e.preventDefault();keyboardStop();}' in branch  # Alt+X, and Esc with no drawer: always the stop request
    fn = js[js.index('async function keyboardStop()'):js.index("document.addEventListener('keydown'")]
    assert "api('/stop',{})" in fn and 'renderStatus(st)' in fn and "setReqError('정지 요청: '" in fn
    ui = ((bench_record.HERE / 'bench_record_ui.js').read_text(encoding='utf-8') + (bench_record.HERE / 'bench_record_status.js').read_text(encoding='utf-8'))
    assert 'st.stop_result?.message' in ui and "setNotice('stop-result'" in ui


def _sealed(bench):
    """The state a finished session publishes (and its auto-home record), as the session thread does."""
    bench.state = {'status': 'sealing', 'arm': 'arm_s'}
    bench._publish_end(status='sealed', seal_exit=0)


def _ended_session(bench, claim_state):
    """A session that ran as its own request (its own claim) and ended safely: its record exists and its thread knows it."""
    with bench.lock:
        bench.state = dict(claim_state, status='sealing', claim=bench._claim_bench())
    bench._publish_end(status='sealed', seal_exit=0)
    return bench.state['claim']


def test_a_later_session_keeps_its_own_auto_home_record_when_an_earlier_one_finishes_and_a_stop_cancels_it(tmp_path, monkeypatch):
    import threading
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    results = {}

    def session_a():
        results['a'] = _ended_session(bench, {'arm': 'arm_s'})  # A sealed and published its record; its auto home now waits in the pre-checks
        waiting.set()
        resume.wait(5)
        bench._auto_home_after_session()

    def session_b():
        claim = _ended_session(bench, {'arm': 'arm_s'})  # B starts, records, ends and publishes its own record while A is waiting
        results['b'] = claim
        b_published.set()
    waiting, resume, b_published = threading.Event(), threading.Event(), threading.Event()
    bench._check_lease = lambda arm: (waiting.wait(5), resume.wait(5)) and None  # A's go_home blocks here, before its reservation
    thread_a = threading.Thread(target=session_a)
    thread_a.start()
    assert waiting.wait(5)
    thread_b = threading.Thread(target=session_b)
    thread_b.start()
    assert b_published.wait(5)
    thread_b.join(5)
    assert set(bench._auto_homes) == {results['a'], results['b']}
    resume.set()  # A resumes: its claim no longer matches (B took the bench), it is refused, its finally removes ONLY its own record
    thread_a.join(5)
    assert set(bench._auto_homes) == {results['b']} and spawned == [] and calls == []
    assert bench._auto_homes[results['b']] == {'cancelled': False, 'reserved': False}  # B's record is intact
    snapshot = bench.stop()  # the person presses Stop: B's pending auto home is cancelled
    assert snapshot['auto_home']['message'] == '자동 홈 취소됨' and bench._auto_homes[results['b']]['cancelled'] is True
    bench._check_lease = lambda arm: None
    import bench_record_manual
    bench_record_manual._TLS.published_claim = results['b']  # B's own thread would carry this
    bench._auto_home_after_session()
    assert spawned == [] and calls == [] and bench._auto_homes == {}  # B's auto home did not start, and removed only its own record


def test_stop_cancels_every_pending_auto_home_record_but_not_one_that_already_reserved(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    first = _ended_session(bench, {'arm': 'arm_s'})
    second = _ended_session(bench, {'arm': 'arm_s'})
    bench._auto_homes[first]['reserved'] = True  # already moving: aborted, not cancelled
    bench.stop()
    assert bench._auto_homes[first]['cancelled'] is False and bench._auto_homes[second]['cancelled'] is True


@pytest.mark.parametrize('reason', ['pause_read_failure', 'pause_saturated', 'pause_over_bound', 'guard_fault: arm_s elbow_flex: hardware error',
                                    'exception: ValueError: shoulder_lift: following error'])
def test_a_session_that_ended_by_a_guard_event_never_starts_the_auto_home(tmp_path, monkeypatch, reason):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    spawned = []
    bench.popen = lambda command, cwd, **kw: spawned.append(command)
    folder = tmp_path / 'session'
    folder.mkdir()
    (folder / 'guard-end.json').write_text(json.dumps({'reason': reason}), encoding='utf-8')
    bench.state = {'status': 'sealing', 'arm': 'arm_s', 'folder': str(folder)}
    for status in ('sealed', 'stopped_safe'):  # sealed after a clean exit 0, or a guard stop that the session record proves safe
        bench.state = {'status': 'sealing', 'arm': 'arm_s', 'folder': str(folder)}
        assert bench._publish_end(status=status) == status
        assert bench.state['auto_home'] == {'ok': False, 'skipped': True, 'reason': reason, 'message': f'skipped: {reason}'} and bench._auto_homes == {}
        bench._auto_home_after_session()
        assert spawned == [] and calls == [] and bench.state['auto_home']['skipped'] is True  # no motion, nothing stopped, the reason stays shown


def test_unreadable_end_evidence_is_a_guard_event_and_a_clean_end_still_starts_the_auto_home(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    folder = tmp_path / 'session'
    folder.mkdir()
    (folder / 'guard-end.json').write_text('{half', encoding='utf-8')
    bench.state = {'status': 'sealing', 'arm': 'arm_s', 'folder': str(folder)}
    bench._publish_end(status='sealed')
    assert bench.state['auto_home']['skipped'] is True and 'unreadable' in bench.state['auto_home']['reason'] and bench._auto_homes == {}
    (folder / 'guard-end.json').unlink()  # fail closed without clean-end.json
    bench.state = {'status': 'sealing', 'arm': 'arm_s', 'folder': str(folder)}
    bench._publish_end(status='sealed')
    assert bench.state['auto_home']['skipped'] is True and 'clean-end' in bench.state['auto_home']['reason'] and bench._auto_homes == {}
    (folder / 'clean-end.json').write_text(json.dumps({'clean': True}), encoding='utf-8')  # explicit clean-end allows auto-home
    bench.state = {'status': 'sealing', 'arm': 'arm_s', 'folder': str(folder)}
    bench._publish_end(status='sealed')
    assert 'auto_home' not in bench.state and len(bench._auto_homes) == 1


def _spied(bench):
    popen, envs = bench.popen, []

    def spy(command, cwd, **kw):
        if command[1].endswith('record_session.py'):
            envs.append(kw.get('env') or {})
        return popen(command, cwd, **kw)
    bench.popen = spy
    return envs


def test_prepare_starts_a_linked_session(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    envs = _spied(bench)
    bench.prepare(body)
    state = finished(bench)
    assert envs[0]['ROSY_LINK_DIR'] == str(Path(state['folder']) / 'link') and state['link'] is True and state['target_episodes'] == 500
    assert state['phase'] == 'result' and state['prepare'] is None  # the session ended (the fake recorder exits at once)


def test_start_stays_the_one_shot_prepare_and_record(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    envs = _spied(bench)
    bench.start(body)
    state = finished(bench)
    assert 'ROSY_LINK_DIR' not in envs[0] and state['link'] is False and state['target_episodes'] != 500


def _linked_state(bench, tmp_path, link_state, status='recording', link=True):
    folder = tmp_path / 'session'
    (folder / 'link').mkdir(parents=True, exist_ok=True)
    if link_state is not None:
        (folder / 'link' / 'state.json').write_text(json.dumps({'state': link_state, 'episode': 3}), encoding='utf-8')
    bench.state = {'status': status, 'arm': 'arm_a', 'folder': str(folder), 'link': link}
    return folder


def test_the_phase_field_and_the_prepare_ready_flag_follow_the_recorders_own_state(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    assert bench.link_fields({'status': 'idle'}) == {'phase': 'setup', 'prepare': None, 'link': False}
    _linked_state(bench, tmp_path, None, status='handing_over')
    prepare = bench.link_fields(dict(bench.state))
    assert prepare['phase'] == 'prepare' and prepare['prepare']['ready'] is False
    for link_state, phase, ready in (('aligning', 'prepare', False), ('waiting', 'prepare', True), ('saving', 'prepare', False), ('recording', 'recording', None)):
        _linked_state(bench, tmp_path, link_state)
        fields = bench.link_fields(dict(bench.state))
        assert fields['phase'] == phase and fields['link'] is True
        assert (fields['prepare'] or {}).get('ready') == ready and (fields['prepare'] or {}).get('link_state', link_state) == link_state
    assert bench.link_fields(dict(bench.state))['prepare'] is None  # recording: no prepare block
    _linked_state(bench, tmp_path, None, status='recording', link=False)  # the one-shot start
    assert bench.link_fields(dict(bench.state))['phase'] == 'recording'
    for status in ('restoring', 'sealing', 'sealed', 'stopped_safe', 'failed', 'leader_manual_check'):
        assert bench.link_fields({'status': status, 'link': True})['phase'] == 'result'
    assert 'phase' in bench.status() and 'prepare' in bench.status()  # status.json carries them


def test_record_next_rerecord_and_finish_write_one_request_each_only_in_the_state_they_belong_to(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    folder = _linked_state(bench, tmp_path, 'waiting')

    def sent():
        return json.loads((folder / 'link' / 'control.json').read_text(encoding='utf-8'))
    bench.record_episode()
    assert sent() == {'seq': 1, 'cmd': 'record'}
    with pytest.raises(ValueError, match='녹화 중에만'):  # waiting: no next, no re-record
        bench.episode_next()
    with pytest.raises(ValueError, match='녹화 중에만'):
        bench.episode_rerecord()
    (folder / 'link' / 'state.json').write_text(json.dumps({'state': 'recording'}), encoding='utf-8')
    bench.episode_next()
    assert sent() == {'seq': 2, 'cmd': 'next'}
    bench.episode_rerecord()
    assert sent() == {'seq': 3, 'cmd': 'rerecord'}
    with pytest.raises(ValueError, match='연동됨'):  # recording: no second record
        bench.record_episode()
    with pytest.raises(ValueError, match='연동을 끝낼 수 없습니다'):  # an episode is not cut off by finish
        bench.finish()
    (folder / 'link' / 'state.json').write_text(json.dumps({'state': 'waiting'}), encoding='utf-8')
    bench.finish()
    assert sent() == {'seq': 4, 'cmd': 'finish'} and bench._pre_cancel == set()  # finish cancels nothing: restore, seal and the auto home follow
    bench.abort = True
    with pytest.raises(ValueError, match='준비되어 있지 않습니다'):  # a stop is under way
        bench.record_episode()
    bench.abort = False
    _linked_state(bench, tmp_path, 'waiting', link=False)
    with pytest.raises(ValueError, match='준비되어 있지 않습니다'):  # not a linked session
        bench.record_episode()
    bench.state = {'status': 'idle'}
    with pytest.raises(ValueError, match='준비되어 있지 않습니다'):
        bench.finish()


def test_stop_still_ends_a_linked_session_and_cancels_its_auto_home(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _linked_state(bench, tmp_path, 'waiting')
    signals = []
    bench.child = SimpleNamespace(poll=lambda: None, send_signal=signals.append)
    bench.stop()
    assert len(signals) == 1 and bench._session_claim() in bench._pre_cancel  # /stop is unchanged: SIGTERM, the auto home cancelled


def test_the_link_requests_are_routed_and_the_page_gets_a_prepare_route_per_arm():
    source = (bench_record.HERE / 'bench_record_http.py').read_text(encoding='utf-8')
    for route in ('"/prepare"', '"/record_episode"', '"/finish"', '"/api/episode/next"', '"/api/episode/rerecord"', 'prepare|record_episode|finish'):
        assert route in source
    import bench_live_preview
    assert bench_live_preview.recorder_env(None, Path('/x/link'))['ROSY_LINK_DIR'] == '/x/link' and 'ROSY_LINK_DIR' not in bench_live_preview.recorder_env(None)


def test_bench_status_bar_and_split_recording_controls():
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    cam = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')

    footer = html.split('<footer id="status-bar"', 1)[1].split('</footer>', 1)[0]
    for field in ('top-badge', 'sb-st-follower', 'sb-st-torque', 'sb-st-leader', 'sb-st-phase',
                  'status-speed', 'status-cameras', 'status-camera-source', 'sb-st-hold', 'start-reason-bar'):
        assert f'id="{field}"' in footer
    assert footer.count('<div hidden>') >= 4
    assert "const text=value??''" in ui and ".hidden=text===''" in ui
    assert '.status-bar{position:fixed' in css and '@media(max-width:1366px)' in css
    assert 'id="hdr-camera-restart-btn"' in html
    assert "api('/api/cameras/restart',{arm:f.arm.value})" in app
    assert "e.shiftKey&&low==='c'" in app and '!benchSessionActive()' in app

    for button in ('hdr-prepare-btn', 'hdr-start-now-btn', 'hdr-record-btn', 'hdr-finish-btn',
                   'hdr-rerecord-btn', 'back-to-setup-btn'):
        assert f'id="{button}"' in html
    assert "startBench('/prepare')" in app and "phase==='prepare'&&(st?.prepare?.ready===true||st?.ready===true)" in cam
    assert "record.hidden=!(stopping||ready)" in cam and "'■ 녹화 끝'" in cam
    assert "episodeAction('/record_episode')" in cam and "episodeAction('/finish','/stop')" in cam
    assert "episodeAction('/api/episode/rerecord')" in cam
    assert "saving:'에피소드 저장 중'" in ui and 'st?.prepare?.step??st?.starting_step' in cam


def test_prepare_and_link_only_reject_bimanual_and_replay_and_link_command_checks_arm_and_pending_seq(tmp_path, monkeypatch):
    bench, body, _, _ = _setup(tmp_path, monkeypatch)
    for bad in (dict(body, arm='arm_ab'), dict(body, replay='r.parquet')):
        with pytest.raises(ValueError, match='단일 팔'):
            bench.prepare(bad)
        with pytest.raises(ValueError, match='단일 팔'):
            bench.start(dict(bad, link_only=True))
    folder = _linked_state(bench, tmp_path, 'waiting')
    (folder / 'link' / 'state.json').write_text(json.dumps({'state': 'waiting', 'seq': 0}), encoding='utf-8')
    with pytest.raises(ValueError, match='arm_a'):
        bench.record_episode({'arm': 'arm_b'})
    bench.record_episode({'arm': 'arm_a'})
    with pytest.raises(ValueError, match='아직 처리 중'):
        bench.record_episode({'arm': 'arm_a'})
    (folder / 'link' / 'state.json').write_text(json.dumps({
        'state': 'recording', 'episode': 0, 'seq': 1, 'episode_started': 100.0,
        'last_command': {'seq': 1, 'cmd': 'record', 'applied': True},
    }), encoding='utf-8')
    bench.clock = lambda: 104.5
    st = bench.link_fields({'status': 'recording', 'link': True, 'folder': str(folder)})
    assert st['episode_elapsed_s'] == 4.5 and st['link_last_command']['applied'] is True
    (folder / 'link' / 'state.json').write_text(json.dumps({'state': 'waiting', 'episode': 0, 'seq': 1}), encoding='utf-8')
    bench.finish({'arm': 'arm_a'})
    assert json.loads((folder / 'link' / 'control.json').read_text(encoding='utf-8')) == {'seq': 2, 'cmd': 'finish'}
    (folder / 'link' / 'state.json').write_text(json.dumps({'state': 'recording', 'episode': 1, 'seq': 2}), encoding='utf-8')
    bench.episode_rerecord({'arm': 'arm_a'})
    assert json.loads((folder / 'link' / 'control.json').read_text(encoding='utf-8')) == {'seq': 3, 'cmd': 'rerecord', 'episode': 1}
