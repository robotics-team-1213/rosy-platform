from test_omx_bench_record import (
    Path, ROOT, SimpleNamespace, UNITS, bench_record, digest, finished, importlib, json, pytest, sys, time,
    _LeaderProc, _arm_s_live_files, _home_with_stages, _leader_for_match, _leader_popen, _setup,
)

def test_go_home_prevalidates_arm_ab_and_rejects_bad_lerobot_bools(tmp_path, monkeypatch):
    bench, body, _, _ = _setup(tmp_path, monkeypatch)
    for letter in ('a', 'b'):
        (bench.prep / f'cell-arm-{letter}-stack.json').write_text('{}')
        (bench.prep / f'chunks-topdown-guard-arm{letter}-test.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-armb-test.json').unlink()  # arm_b cannot home: refused before arm_a moves (no process is started)
    with pytest.raises(ValueError, match='arm_b'):
        bench.go_home({'arm': 'arm_ab', 'include_leader': True})
    assert bench.status()['status'] == 'idle'
    with pytest.raises(ValueError, match='episode_time_s'):
        bench.start(dict(body, lerobot_params={'episode_time_s': True}))
    with pytest.raises(ValueError):
        bench.start(dict(body, calibrations='not-a-list'))


def test_api_telemetry_reads_live_telemetry_file(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    assert bench.telemetry()['active'] is False
    (bench.prep / 'telemetry-live.json').write_text(json.dumps({
        'active': True,
        'tracking': True,
        'loop_latency_ms': 18.4,
        'motors': [{'name': 'shoulder_pan', 'leader_raw': 2098, 'present_raw': 2097, 'error_deg': 0.09}],
    }), encoding='utf-8')
    tel = bench.telemetry()
    assert tel['active'] is True
    assert tel['tracking'] is True
    assert tel['loop_latency_ms'] == 18.4
    assert tel['motors'][0]['name'] == 'shoulder_pan'


def test_camera_baseline_and_drift_check(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    bdir = bench.prep / 'camera-baselines' / 'arm_a'
    bdir.mkdir(parents=True)
    (bdir / 'baseline.json').write_text(json.dumps({
        'cameras': {'top': {'quality': {'mean_intensity': 100.0, 'spatial_contrast': 40.0}}}
    }), encoding='utf-8')
    import io
    monkeypatch.setattr(
        'bench_record_inspect.urllib.request.urlopen',
        lambda *_a, **_kw: io.BytesIO(json.dumps({
            'top': {'fresh': True, 'quality': {'condition': 'NORMAL', 'usable': True, 'mean_intensity': 140.0, 'spatial_contrast': 42.0}},
            'side': {'fresh': True, 'quality': {'condition': 'NORMAL', 'usable': True, 'mean_intensity': 90.0, 'spatial_contrast': 35.0}},
        }).encode()),
    )
    res = bench.check_camera_drift('arm_a')
    assert res['cameras']['top']['status'] == 'lighting_mismatch'
    assert res['cameras']['side']['status'] == 'no_baseline'
    assert res['cameras']['arm_a_wrist']['status'] == 'missing'
    with pytest.raises(ValueError):
        bench.save_camera_baseline({'arm': '../../evil', 'at_bench': True})
    assert bench.check_camera_drift('../../evil')['arm'] == 'default'


def test_side_reference_is_explicit_and_separate_from_lighting(tmp_path, monkeypatch):
    import hashlib
    import io
    import threading
    import urllib.request
    import bench_camera_alignment as alignment

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    jpeg = b'confirmed side frame'
    receipt = {'jpeg_bytes': jpeg, 'jpeg_sha256': hashlib.sha256(jpeg).hexdigest(),
               'source_seq': 7, 'source_stamp': time.time(), 'camera': 'side'}
    bench._side_references = [receipt]
    with pytest.raises(ValueError):
        alignment.save_confirmed(bench, {})
    with pytest.raises(ValueError):
        alignment.save_confirmed(bench, {'confirmed': True, 'sha256': 'unseen'})
    server = bench_record.make_server(bench, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        request = urllib.request.Request(base + '/api/camera_alignment',
                                         json.dumps({'confirmed': True, 'sha256': receipt['jpeg_sha256']}).encode(),
                                         {'X-Bench': '1', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.load(response)['source_stamp'] == receipt['source_stamp']
        with urllib.request.urlopen(base + '/api/camera_alignment/reference.jpg', timeout=5) as response:
            assert response.headers['Content-Type'] == 'image/jpeg'
            assert response.read() == jpeg
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    monkeypatch.setattr('bench_record_ops.urllib.request.urlopen', lambda *_a, **_kw: io.BytesIO(b'{}'))
    bench.save_camera_baseline({'arm': 'arm_a'})
    assert alignment.reference_image(bench.prep) == jpeg
    assert alignment.check(bench.prep)['status'] == 'manual_comparison'


def test_side_alignment_reports_signed_shift_and_requires_fixed_markers():
    from bench_camera_alignment import compare_markers

    ref = {7: [[10, 20], [12, 20], [12, 22], [10, 22]], 8: [[20, 40], [22, 40], [22, 42], [20, 42]]}
    moved = {key: [[x + 3, y - 12] for x, y in corners] for key, corners in ref.items()}
    assert compare_markers(ref, ref, (7, 8), 6)['status'] == 'aligned'
    result = compare_markers(ref, moved, (7, 8), 6)
    assert (result['status'], result['dx_px'], result['dy_px']) == ('moved', 3, -12)
    assert compare_markers(ref, {7: moved[7]}, (7, 8), 6)['status'] == 'markers_missing'


def test_replay_teacher_mode_in_choices_and_start(tmp_path, monkeypatch):
    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    rdir = bench.prep / 'replays'
    rdir.mkdir()
    (rdir / 'sim-pick.json').write_text('{"schema": "rosy.omx-replay-trajectory.v1"}', encoding='utf-8')
    assert bench.choices()['replays'] == ['replays/sim-pick.json']
    bench.start(dict(body, replay='replays/sim-pick.json'))
    finished(bench)
    assert '--replay' in commands[0]
    rs_src = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/record_session.py').read_text(encoding='utf-8')
    assert 'self.replay is not None' in rs_src
    assert 'id="replay"' in (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record.html').read_text(encoding='utf-8')


def test_reverse_replay_modes_and_task_override():
    import bench_record_replay as brr
    traj = {
        'schema': 'rosy.omx-replay-trajectory.v1',
        'fps': 30,
        'frames': [[1, 0, 0, 0, 0, -50], [2, 0, 0, 0, 0, 50], [2, 0, 0, 0, 0, 50], [3, 0, 0, 0, 0, 50], [4, 0, 0, 0, 0, -50]],
        'segments': {'A': [0, 2], 'reset': [2, 3], 'B': [3, 5]},
    }
    raw = json.dumps(traj).encode('utf-8')
    sw = json.loads(brr.transform_replay(raw, mode='swap_ab').decode('utf-8'))
    assert sw['frames'][:2] == [[3, 0, 0, 0, 0, 50], [4, 0, 0, 0, 0, -50]]
    assert sw['frames'][3:] == [[1, 0, 0, 0, 0, -50], [2, 0, 0, 0, 0, 50]]
    rev = json.loads(brr.transform_replay(raw, mode='reverse_motion', invert_gripper=True).decode('utf-8'))
    assert rev['frames'][0][:5] == [2, 0, 0, 0, 0]
    assert rev['frames'][0][5] == -50.0  # inverted from 50
    with pytest.raises(ValueError):
        brr.transform_replay(raw, mode='bad_mode')

    tc = {'task_id': 'h1-belt-ship', 'layout': {'origin': 'belt', 'target_slot': 'ship-h1r0-l0'},
          'record': {'single_task': 'Move belt to ship-h1r0-l0'}}
    out = brr.apply_task_override(tc, {'swap_pick_place': True})
    assert out['layout']['origin'] == 'ship-h1r0-l0'
    assert out['layout']['target_slot'] == 'belt'
    assert out['record']['single_task'] == 'Move ship-h1r0-l0 to belt'
    assert 'ship-h1r0-l0-to-belt' in out['task_id']
    with pytest.raises(ValueError):
        brr.apply_task_override(tc, {'origin': 'belt', 'target_slot': 'belt'})


def test_recording_progress_and_shell_elements(tmp_path):
    import bench_record_replay as brr
    ds = tmp_path / 'h1-belt-r1-20261121-010101'
    (ds / 'meta').mkdir(parents=True)
    (ds / 'data' / 'chunk-000').mkdir(parents=True)
    (ds / 'meta' / 'info.json').write_text('{"total_episodes": 3}', encoding='utf-8')
    (ds / 'data' / 'chunk-000' / 'file-000.parquet').write_bytes(b'1')
    p = brr.recording_progress({
        'status': 'recording', 'recording_started': 100.0, 'started': 99.0,
        'target_episodes': 10, 'task_id': 'h1-belt', 'dataset_root_prefix': str(tmp_path),
    }, lambda: 112.5)
    assert p['recording_elapsed_s'] == 12.5
    assert p['episodes_done'] == 3
    assert p['episodes_remaining'] == 7
    html_src = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record.html').read_text(encoding='utf-8')
    for marker in ('id="hdr-estop-btn"', 'id="slim-prog"', 'id="sp-timer"', 'id="toggle-reverse-btn"', 'bench_record.css'):
        assert marker in html_src
    ui_js = ((Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_ui.js').read_text(encoding='utf-8')
             + (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_map.js').read_text(encoding='utf-8')
             + (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_status.js').read_text(encoding='utf-8'))
    assert "arm_a:new Set(['top','side','arm_a_wrist'])" in ui_js
    assert "arm_b:new Set(['top','side','arm_b_wrist'])" in ui_js


def test_ship_address_names_follow_the_site_map():
    ui = ((Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_ui.js').read_text(encoding='utf-8')
          + (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_map.js').read_text(encoding='utf-8'))
    site = json.loads((Path(__file__).resolve().parent.parent / 'shared/web/cell-site-map.json').read_text(encoding='utf-8'))
    # both holds are drawn, the grid follows the selected hold, no 0-based symbols next to the 1-based floor names
    for marker in ("data-spot=\"ship-h'+k+'\"", "for(const [k,y] of [[2,8],[1,46]])", "ship-h(\\d)r(\\d)-l(\\d)", "과제 카드 없음 (칸을 눌러도 연결되지 않음)", "'화물칸 h'+m[1]"):
        assert marker in ui, marker
    for gone in ("[[1,108],[2,182]]", "ship-grids", "ship-grid-head", "(r'+row+')", "r'+row+'·l'+lv", "중앙 선박 h1"):
        assert gone not in ui, gone
    # the map draws h2 above h1 between the stands (h2 x_mm 197 -> fixture x -.042 is farther from the arms and belt at +x than h1 x_mm 99 -> +.056), and only the selected hold gets a grid
    assert ui.index("[[2,8],[1,46]]") < ui.index('data-spot="pinky"') and ui.count("class=\"ship-grid'") == 1
    assert 'function resolveActiveZone(' in ui and 'window.shipHold' in ui and 'if(hold){' in ui
    css = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record.css').read_text(encoding='utf-8')
    assert "ship-grids" not in css
    assert "ROW_LABELS=['A쪽 줄','가운데 줄','B쪽 줄']" in ui and "HOLD_COLUMNS={1:'4~6열',2:'1~3열'}" in ui
    # HOLD_COLUMNS and the layer names come from the site map: h<k> items sit in yard slots whose columns are the ones named here
    cols = {}
    for slot in next(z for z in site['zones'] if z['id'] == 'yard')['slots']:
        for tier in slot['tiers']:
            cols[int(tier['item'][6])] = f"{slot['columns'][0]}~{slot['columns'][1]}열"
            assert tier['item'].endswith(f"-l{tier['tier'] - 1}")  # layer lN is tier N+1, shown as (N+1)층
    assert cols == {1: '4~6열', 2: '1~3열'}
    slots = json.loads((Path(__file__).resolve().parent.parent / 'learning/envs/isaac/assets/ship_r08_berth/slots.json').read_text(encoding='utf-8'))['tier_records']
    x_mm = {h: sum(r['x_mm'] for r in slots if r['module_index'] == h) / sum(1 for r in slots if r['module_index'] == h) for h in (1, 2)}
    assert x_mm[1] < x_mm[2]  # h1 is nearer the stern, where the arms and belt (+x, bottom of the map) are: bottom row; h2 top row (listed first)


def test_closed_loop_pipeline_api_and_guards(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    res = bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'source_ref': 'isaac://h1', 'arm': 'arm_a'})
    assert res['ok'] is True
    assert res['replay_id'] == 'replays/pipe-isaac-sim-arm_a.json'
    assert (bench.prep / res['replay_id']).is_file()
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'source_ref': '../../etc/passwd'})
    with pytest.raises(ValueError):
        bench.pipeline_run({'dataset_folder': 'not-sealed', 'trigger': 'auto_after_seal'})
    st = bench.pipeline_run({'dataset_folder': 'h1-demo-01', 'trigger': 'manual'})
    assert st['last_dataset'] == 'h1-demo-01'
    import time as _t
    for _ in range(30):
        cur = bench.pipeline_status()
        if cur['state'] in ('done', 'blocked', 'failed'):
            break
        _t.sleep(0.05)
    assert cur['state'] == 'failed' and cur['stages']['seal'] == 'failed'
    assert cur['loop_count'] == 0 and 'next_checkpoint' not in cur


def test_audit_hardening_replay_validation_and_collection_name(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    # 1. arm path traversal and missing replays/ ref must fail
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'arm': '../../evil'})
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'teacher_traj', 'source_ref': 'replays/missing.json', 'arm': 'arm_a'})
    # 2. out-of-range joint value in replay must fail
    rdir = bench.prep / 'replays'
    rdir.mkdir(exist_ok=True)
    (rdir / 'bad.json').write_text(json.dumps({
        'schema': 'rosy.omx-replay-trajectory.v1', 'fps': 15, 'frames': [[999, 0, 0, 0, 0, 0]],
    }), encoding='utf-8')
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'teacher_traj', 'source_ref': 'replays/bad.json', 'arm': 'arm_a'})
    # 3. apply_task_override updates top-level single_task
    import bench_record_replay as brr
    tc = {'task_id': 'h1-01', 'single_task': 'Move belt to ship-h1r1-l0',
          'layout': {'origin': 'belt', 'target_slot': 'ship-h1r1-l0'}}
    ov = brr.apply_task_override(tc, {'swap_pick_place': True})
    assert ov['single_task'] == 'Move ship-h1r1-l0 to belt'
    # 4. session folder -> state['name'] resolution
    bench.state = {'status': 'sealed', 'name': 'h1-seal-01', 'folder': str(tmp_path / 'sessions' / '20261121-000001-h1-seal-01')}
    st2 = bench.pipeline_run({'dataset_folder': bench.state['folder'], 'trigger': 'auto_after_seal'})
    assert st2['last_dataset'] == 'h1-seal-01'
    # 5. HTTP routes for CSS, pipeline JS, and /api/pipeline/status
    import threading, urllib.request
    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f'http://127.0.0.1:{srv.server_port}'
        for path in ('/bench_record.css', '/bench_record_map.js', '/bench_record_pipeline.js', '/api/pipeline/status', '/api/hf/status'):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_hf_async_upload_and_do_not_train_guard(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    fake_home = tmp_path / 'home'
    (fake_home / '.cache' / 'huggingface').mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, 'home', lambda: fake_home)
    ds_dir = fake_home / 'rosy-data' / 'omx-leader' / 'h1-demo-01'
    (ds_dir / 'meta').mkdir(parents=True)
    (ds_dir / 'data' / 'chunk-000').mkdir(parents=True)
    (ds_dir / 'meta' / 'info.json').write_text('{"codebase_version": "v3.0", "total_episodes": 1}', encoding='utf-8')
    (ds_dir / 'data' / 'chunk-000' / 'ep0.parquet').write_bytes(b'pq')
    # 1. Refuses without HF token
    with pytest.raises(ValueError):
        bench.hf_upload_start({'dataset': 'h1-demo-01'})
    (fake_home / '.cache' / 'huggingface' / 'token').write_text('hf_dummy', encoding='utf-8')
    # 2. Refuses DO_NOT_TRAIN dataset
    (ds_dir / 'DO_NOT_TRAIN.txt').write_text('static', encoding='utf-8')
    with pytest.raises(ValueError):
        bench.hf_upload_start({'dataset': 'h1-demo-01'})
    (ds_dir / 'DO_NOT_TRAIN.txt').unlink()
    # 3. Personal HF account without robotteam org membership is refused
    import sys, types, time as _t
    calls = []
    class FakePersonalHfApi:
        def whoami(self): return {'name': 'livsb3', 'orgs': []}
        def create_repo(self, **kw): calls.append(('create', kw['repo_id']))
        def upload_folder(self, **kw): calls.append(('upload', kw['repo_id'], kw.get('path_in_repo')))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(HfApi=FakePersonalHfApi))
    bench.hf_upload_start({'dataset': 'h1-demo-01'})
    for _ in range(40):
        st = bench.hf_upload_status()
        if st['state'] in ('done', 'failed'):
            break
        _t.sleep(0.05)
    assert st['state'] == 'failed' and 'robotteam' in st['error'] and not calls
    # 4. robotteam member uploads privately to robotteam/rosy-omx-data under dataset subpath
    class FakeTeamHfApi(FakePersonalHfApi):
        def whoami(self): return {'name': 'livsb3', 'orgs': [{'name': 'robotteam'}]}
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(HfApi=FakeTeamHfApi))
    res = bench.hf_upload_start({'dataset': 'h1-demo-01'})
    assert res['hf_upload']['state'] in ('encoding', 'uploading', 'done')
    for _ in range(40):
        st = bench.hf_upload_status()
        if st['state'] in ('done', 'failed'):
            break
        _t.sleep(0.05)
    assert st['state'] == 'done'
    assert st['repo_id'] == 'robotteam/rosy-omx-data'
    assert ('upload', 'robotteam/rosy-omx-data', 'h1-demo-01') in calls
    ds_rows = bench.lerobot_datasets()
    assert ds_rows[0]['hf_uploaded'] is True and ds_rows[0]['hf_repo_id'] == 'robotteam/rosy-omx-data'


def test_ik_planner_belt_in_to_pinky_arm_s(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    wd = bench.prep / 'cell-auto-1028'
    wd.mkdir()
    (wd / 'surface-belt.json').write_text(json.dumps({'steps': [
        {'command': 'load lib', 'state': [0.8, -62.0, 53.0, 51.5, 45.0, 48.0]},
        {'command': 'goto above_probe', 'state': [0.3, -11.2, 11.5, 50.4, 8.5, 48.0]},
        {'command': 'run descend_probe', 'state': [0.3, -8.7, 19.8, 40.8, 8.5, 48.0]},
    ]}), encoding='utf-8')
    (wd / 'surface-pinky.json').write_text(json.dumps({'steps': [
        {'command': 'goto above_probe', 'state': [42.8, 7.0, -10.3, 53.7, -18.7, 48.0]},
        {'command': 'run descend_probe', 'state': [43.2, 7.3, -1.1, 45.3, -18.8, 48.0]},
    ]}), encoding='utf-8')
    res = bench.pipeline_generate_replay({
        'source_type': 'ik_planner', 'arm': 'arm_s', 'origin': 'belt-in', 'target_slot': 'pinky',
    })
    assert res['replay_id'] == 'replays/pipe-ik-planner-arm_s.json'
    traj = json.loads((bench.prep / res['replay_id']).read_text(encoding='utf-8'))
    assert traj['ik_origin'] == 'belt-in' and traj['ik_target'] == 'pinky'
    assert len(traj['frames']) > 50


def test_arm_s_ik_full_pipeline_e2e(tmp_path, monkeypatch):
    import types

    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    wd = bench.prep / 'cell-auto-1028'
    wd.mkdir()
    (wd / 'surface-belt.json').write_text(json.dumps({'steps': [
        {'command': 'load lib', 'state': [0.8, -62.0, 53.0, 51.5, 45.0, 48.0]},
        {'command': 'goto above_probe', 'state': [0.3, -11.2, 11.5, 50.4, 8.5, 48.0]},
        {'command': 'run descend_probe', 'state': [0.3, -8.7, 19.8, 40.8, 8.5, 48.0]},
    ]}), encoding='utf-8')
    (wd / 'surface-pinky.json').write_text(json.dumps({'steps': [
        {'command': 'goto above_probe', 'state': [42.8, 7.0, -10.3, 53.7, -18.7, 48.0]},
        {'command': 'run descend_probe', 'state': [43.2, 7.3, -1.1, 45.3, -18.8, 48.0]},
    ]}), encoding='utf-8')

    robot_s = {'type': 'omx_follower', 'id': 'arm_s_follower', 'port': '/dev/ttyS'}
    (bench.prep / 'caps-arm-s-tune.json').write_text('{}', encoding='utf-8')
    (bench.prep / 'record-config-arm-s.json').write_text(json.dumps({'robot': robot_s}), encoding='utf-8')
    (bench.prep / 'arm-s-robot-profile.json').write_text(json.dumps({
        'schema': 'rosy.omx-cell-robot-profile.v1',
        'device_id': 'arm_s',
        'instance_id': 'arm_s_follower',
        'robot_config_sha256': digest(robot_s),
        'operating_envelope_path': 'envelope.json',
        'work_dir': str(wd),
    }), encoding='utf-8')
    cal_s = tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower/arm_s_follower.json'
    cal_s.write_text('{}', encoding='utf-8')

    res = bench.pipeline_generate_replay({
        'source_type': 'ik_planner', 'arm': 'arm_s', 'origin': 'belt-in', 'target_slot': 'pinky',
    })
    assert res['ok'] is True
    replay_file = bench.prep / res['replay_id']
    assert replay_file.is_file()

    traj = json.loads(replay_file.read_text(encoding='utf-8'))
    assert traj['schema'] == 'rosy.omx-replay-trajectory.v1' and traj['fps'] == 30
    frames, segs = traj['frames'], traj['segments']
    assert max(abs(a - b) for p, q in zip(frames, frames[1:]) for a, b in zip(p, q)) <= 5.0 / 30 + 1e-3
    (a0, a1), (r0, r1), (b0, b1) = (segs[k] for k in ('A', 'reset', 'B'))
    assert a0 == 0 < a1 == r0 < r1 == b0 < b1 == len(frames) and a1 - a0 == b1 - b0

    adapter_dir = ROOT / 'middleware/devices/omx/adapter'
    tt_path = ROOT / 'deploy/robot/omx/teach_trajectory.py'
    if adapter_dir.is_dir() and tt_path.is_file():
        monkeypatch.syspath_prepend(str(adapter_dir))
        tt_spec = importlib.util.spec_from_file_location('teach_trajectory', tt_path)
        teach_trajectory = importlib.util.module_from_spec(tt_spec)
        tt_spec.loader.exec_module(teach_trajectory)
        assert teach_trajectory.load(replay_file, fps=30)['sha256']

    arm_s_body = dict(
        body, name='arm-s-ik-e2e', arm='arm_s',
        config='record-config-arm-s.json', caps='caps-arm-s-tune.json',
        calibrations=[str(cal_s)], replay=res['replay_id'],
    )
    assert bench.start(arm_s_body)['target_episodes'] == 2
    state = finished(bench)
    assert state['status'] == 'sealed' and state['target_episodes'] == 2
    assert '--replay' in commands[0] and commands[0][commands[0].index('--arm') + 1] == 'arm_s'

    pipe = bench.pipeline_run({'dataset_folder': state['folder'], 'trigger': 'auto_after_seal'})
    assert pipe['last_dataset'] == 'arm-s-ik-e2e'
    for _ in range(40):
        pipe_cur = bench.pipeline_status()
        if pipe_cur['state'] in ('done', 'blocked', 'failed'):
            break
        time.sleep(0.05)
    assert pipe_cur['state'] == 'failed' and 'next_checkpoint' not in pipe_cur

    hf_cache = tmp_path / 'home' / '.cache' / 'huggingface'
    hf_cache.mkdir(parents=True, exist_ok=True)
    (hf_cache / 'token').write_text('hf_dummy', encoding='utf-8')
    ds_dir = tmp_path / 'home' / 'rosy-data' / 'omx-leader' / 'arm-s-ik-e2e'
    (ds_dir / 'meta').mkdir(parents=True)
    (ds_dir / 'data' / 'chunk-000').mkdir(parents=True)
    (ds_dir / 'meta' / 'info.json').write_text('{"codebase_version": "v3.0", "total_episodes": 1}', encoding='utf-8')
    (ds_dir / 'data' / 'chunk-000' / 'episode_000000.parquet').write_bytes(b'PAR1')

    hf_calls = []
    class FakeHfApi:
        def whoami(self): return {'name': 'tester', 'orgs': [{'name': 'robotteam'}]}
        def create_repo(self, **kw): hf_calls.append(('create', kw['repo_id']))
        def upload_folder(self, **kw): hf_calls.append(('upload', kw['repo_id'], kw.get('path_in_repo')))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(HfApi=FakeHfApi))
    bench.hf_upload_start({'dataset': 'arm-s-ik-e2e'})
    for _ in range(40):
        hf_st = bench.hf_upload_status()
        if hf_st['state'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert hf_st['state'] == 'done' and hf_st['repo_id'] == 'robotteam/rosy-omx-data'
    assert ('upload', 'robotteam/rosy-omx-data', 'arm-s-ik-e2e') in hf_calls
    assert (Path(state['folder']) / 'hf-upload.json').is_file()


def test_active_handover_units_includes_cameras_bind_timer_first():
    import types
    import bench_record_inspect as bri
    fake_out = "\n".join([
        "rosy-omx-camera@arm_s_top.service loaded active running top",
        "rosy-omx-camera-view.service loaded active running view",
        "rosy-omx-cameras-bind.timer loaded active waiting bind",
        "rosy-omx-bench-record.service loaded active running bench",
    ])
    fake_run = lambda *a, **kw: types.SimpleNamespace(stdout=fake_out, returncode=0)
    units = bri.active_handover_units(fake_run)
    assert units[0] == "rosy-omx-cameras-bind.timer"
    assert "rosy-omx-camera@arm_s_top.service" in units
    assert "rosy-omx-bench-record.service" not in units


def test_dataset_size_and_delete_empty_only(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    ds_root = tmp_path / "home" / "rosy-data" / "omx-leader"
    empty_ds = ds_root / "empty-ds-1"
    (empty_ds / "meta").mkdir(parents=True)
    (empty_ds / "meta" / "info.json").write_text("{}", encoding="utf-8")
    full_ds = ds_root / "full-ds-1"
    (full_ds / "data" / "chunk-000").mkdir(parents=True)
    (full_ds / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"PAR1")

    rows = {r["name"]: r for r in bench.lerobot_datasets()}
    assert rows["empty-ds-1"]["empty"] is True and rows["empty-ds-1"]["size_bytes"] == 2
    assert rows["full-ds-1"]["empty"] is False and rows["full-ds-1"]["size_bytes"] == 4

    with pytest.raises(ValueError, match="삭제할 수 없습니다"):
        bench.dataset_delete({"dataset": "full-ds-1"})
    res = bench.dataset_delete({"dataset": "empty-ds-1"})
    assert res["ok"] is True and not empty_ds.exists() and full_ds.exists()


def test_leader_home_stops_when_the_leader_lags_its_command_by_more_than_5_degrees(tmp_path, monkeypatch):
    lh_spec = importlib.util.spec_from_file_location('leader_home', ROOT / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)
    names = leader_home.BODY + ('gripper',)

    class StuckBus:  # a held Leader: goals are accepted, the position never follows
        motors = {n: SimpleNamespace(id=i + 1) for i, n in enumerate(names)}
        calibration = {n: SimpleNamespace(range_min=0, range_max=4095) for n in names}
        regs = {'Torque_Enable': dict.fromkeys(names, 0), 'PWM_Limit': dict.fromkeys(names, 150),
                'Current_Limit': dict.fromkeys(names, 100), 'Profile_Velocity': dict.fromkeys(names, 0),
                'Profile_Acceleration': dict.fromkeys(names, 0), 'Position_P_Gain': dict.fromkeys(names, 400),
                'Position_I_Gain': dict.fromkeys(names, 0), 'Present_PWM': dict.fromkeys(names, 0),
                'Present_Position': dict.fromkeys(names, 2000), 'Hardware_Error_Status': dict.fromkeys(names, 0),
                'Operating_Mode': dict.fromkeys(names, 4)}
        goals = []

        def read(self, reg, name, normalize=False, num_retry=0):
            return self.regs[reg][name]

        def write(self, reg, name, val, normalize=False):
            self.regs[reg][name] = val

        def sync_write(self, reg, values, normalize=False):
            self.goals.append(dict(values))

        def enable_torque(self, names=None, num_retry=0):
            for n in (names or self.motors):
                self.regs['Torque_Enable'][n] = 1

        def disable_torque(self, names=None, num_retry=0):
            for n in ([names] if isinstance(names, str) else (names or self.motors)):
                self.regs['Torque_Enable'][n] = 0

    bus = StuckBus()
    leader = SimpleNamespace(bus=bus, calibration=bus.calibration, disconnect=lambda: None)
    cfg = tmp_path / 'rcfg.json'
    cfg.write_text(json.dumps({'teleop': {'type': 'omx_leader', 'id': 'x', 'port': '/dev/null'}}), encoding='utf-8')
    pose = tmp_path / 'pose.json'
    pose.write_text(json.dumps({'ticks': dict.fromkeys(leader_home.BODY, 3000)}), encoding='utf-8')
    monkeypatch.setattr(leader_home, '_connect_leader', lambda _cfg: leader)
    monkeypatch.setattr(leader_home, 'close_device', lambda _dev: bus.disable_torque())
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)
    clock = [0.0]
    monkeypatch.setattr(leader_home.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(leader_home.time, 'sleep', lambda s: clock.__setitem__(0, clock[0] + s))
    with pytest.raises(RuntimeError, match='추종 오차'):
        leader_home.move_leader_home(cfg, 'arm_a', pose, 'hands-off:test:now', timeout_s=5.0)
    lag_ticks = leader_home.MAX_TRACK_DEG * leader_home.TICKS_PER_DEGREE
    assert bus.goals and max(g['shoulder_pan'] for g in bus.goals) - 2000 <= lag_ticks + leader_home.TICKS_PER_DEGREE
    assert all(v == 0 for v in bus.regs['Torque_Enable'].values())


def _load_leader_home():
    lh_spec = importlib.util.spec_from_file_location('leader_home', ROOT / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)
    return leader_home


def test_leader_home_attest_needs_who_and_stamp():
    leader_home = _load_leader_home()
    for bad in ('', 'hands-off', 'hands-off:', 'hands-off:bench', 'hands-off:bench:', 'hands-off::now', 'hands-on:bench:1'):
        with pytest.raises(ValueError, match='attest'):
            leader_home.check_attest(bad)
    leader_home.check_attest('hands-off:bench:1763700000')


def _stuck_leader(leader_home, monkeypatch, tmp_path, torque_off_fails):
    """A held Leader (goals accepted, position never follows) so the 5 degree stop fires; torque OFF may fail like a lost USB link."""
    names = leader_home.BODY + ('gripper',)

    class Bus:
        motors = {n: SimpleNamespace(id=i + 1) for i, n in enumerate(names)}
        calibration = {n: SimpleNamespace(range_min=0, range_max=4095) for n in names}
        regs = {'Torque_Enable': dict.fromkeys(names, 0), 'PWM_Limit': dict.fromkeys(names, 150),
                'Current_Limit': dict.fromkeys(names, 100), 'Profile_Velocity': dict.fromkeys(names, 0),
                'Profile_Acceleration': dict.fromkeys(names, 0), 'Position_P_Gain': dict.fromkeys(names, 400),
                'Position_I_Gain': dict.fromkeys(names, 0), 'Present_PWM': dict.fromkeys(names, 0),
                'Present_Position': dict.fromkeys(names, 2000), 'Hardware_Error_Status': dict.fromkeys(names, 0),
                'Operating_Mode': dict.fromkeys(names, 4)}

        def read(self, reg, name, normalize=False, num_retry=0):
            return self.regs[reg][name]

        def write(self, reg, name, val, normalize=False):
            self.regs[reg][name] = val

        def sync_write(self, reg, values, normalize=False):
            self.moving = True

        moving = False  # the link drops once the Leader is being driven, not while the actuator is being admitted

        def enable_torque(self, names=None, num_retry=0):
            for n in (names or self.motors):
                self.regs['Torque_Enable'][n] = 1

        def disable_torque(self, names=None, num_retry=0):
            if torque_off_fails and self.moving:
                raise OSError('usb link lost')
            for n in ([names] if isinstance(names, str) else (names or self.motors)):
                self.regs['Torque_Enable'][n] = 0

    bus = Bus()
    leader = SimpleNamespace(bus=bus, calibration=bus.calibration, disconnect=lambda: None)
    cfg = tmp_path / 'rcfg.json'
    cfg.write_text(json.dumps({'teleop': {'type': 'omx_leader', 'id': 'x', 'port': '/dev/null'}}), encoding='utf-8')
    pose = tmp_path / 'pose.json'
    pose.write_text(json.dumps({'ticks': dict.fromkeys(leader_home.BODY, 3000)}), encoding='utf-8')
    monkeypatch.setattr(leader_home, '_connect_leader', lambda _cfg: leader)
    monkeypatch.setattr(leader_home, 'close_device', lambda _dev: None)
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)
    clock = [0.0]
    monkeypatch.setattr(leader_home.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(leader_home.time, 'sleep', lambda s: clock.__setitem__(0, clock[0] + s))
    return ['--config', str(cfg), '--arm', 'arm_a', '--pose', str(pose), '--attest', 'hands-off:test:now', '--timeout-s', '5']


@pytest.mark.parametrize('torque_off_fails', [False, True])
def test_leader_home_cli_ends_with_a_json_verdict_that_shows_a_failed_cleanup(tmp_path, monkeypatch, capsys, torque_off_fails):
    leader_home = _load_leader_home()
    argv = _stuck_leader(leader_home, monkeypatch, tmp_path, torque_off_fails)
    assert leader_home.cli(argv) == 1
    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert verdict['ok'] is False and '추종 오차' in verdict['error']
    assert verdict['torque_off_confirmed'] is (not torque_off_fails)
    assert bool(verdict['restore_failures']) is torque_off_fails and (not torque_off_fails or 'torque OFF' in verdict['restore_failures'][0])


def test_leader_home_cli_reports_an_attest_refusal_as_untouched_torque(monkeypatch, capsys):
    leader_home = _load_leader_home()
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)
    assert leader_home.cli(['--config', 'x.json', '--arm', 'arm_a', '--match-follower', '--attest', 'hands-off:x']) == 1
    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert verdict['ok'] is False and verdict['torque_off_confirmed'] is True and 'attest' in verdict['error']


_CONFIRMED = '{"ok": false, "torque_off_confirmed": true, "restore_failures": []}'


@pytest.mark.parametrize('rc, out, status', [
    (1, 'boom\n' + _CONFIRMED, 'idle'),                                                    # torque OFF confirmed: an ordinary error
    (-15, '', 'leader_manual_check'),                                                      # ended by a signal: nothing confirmed
    (1, 'boom', 'leader_manual_check'),                                                    # no verdict line
    (1, '{"ok": false, "torque_off_confirmed": false, "restore_failures": ["torque OFF: usb"]}', 'leader_manual_check'),
    (1, '{"ok": false, "torque_off_confirmed": true, "restore_failures": ["restore x"]}', 'leader_manual_check'),
])
def test_a_failed_leader_child_goes_idle_only_with_a_confirmed_torque_off(tmp_path, monkeypatch, rc, out, status):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    _leader_popen(bench, _LeaderProc(rc=rc, out=out), monkeypatch)
    with pytest.raises(ValueError, match='리더'):
        bench.start(dict(body, align_leader=True, hands_off_leader=True))
    assert bench.status()['status'] == status and not commands
    if status != 'idle':
        with pytest.raises(ValueError, match='manual check|사람 확인'):  # the marker on disk is checked first, the in-memory hold second
            bench.start(body)


def test_alignment_reads_the_config_snapshot_and_a_stop_before_handover_blocks_the_recording(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text('{}')
    ran = _leader_popen(bench, _LeaderProc(), monkeypatch)
    original, seen = bench.align_leader, []

    def aligned_then_stop(*args, **kwargs):
        original(*args, **kwargs)
        seen.append(bench.status()['status'])  # the request still holds the bench: no idle window for other work
        with pytest.raises(ValueError, match='already running|이미|진행'):
            bench.go_home({'arm': 'arm_a', 'at_bench': True})
        assert bench.stop()['status'] == 'homing'  # the stop latches the same abort flag
    bench.align_leader = aligned_then_stop
    with pytest.raises(ValueError, match='정지 요청'):
        bench.start(dict(body, align_leader=True, hands_off_leader=True))
    assert seen == ['homing'] and not commands and bench.status()['status'] == 'idle'
    snapshot = Path(ran[0][ran[0].index('--config') + 1])
    assert '.bench-runs' in snapshot.parts and snapshot.read_bytes() == (bench.prep / body['config']).read_bytes()


def test_go_home_stop_before_the_home_stage_starts_no_motion(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    ran = _home_with_stages(bench, monkeypatch, tmp_path, [('home', None)])
    pressed = []

    def poll():  # the person presses Stop once, while the recorder starts (stop() itself polls the child: no recursion)
        if not pressed:
            pressed.append(1)
            bench.stop()
        return 0
    bench.popen = lambda command, cwd, **kw: SimpleNamespace(poll=poll, wait=lambda timeout=None: 0, returncode=0, send_signal=lambda s: None)
    with pytest.raises(ValueError, match='정지 요청'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert ran == [] and bench.status()['status'] == 'idle' and not bench.manual.exists()


def test_ik_live_pose_read_needs_the_arm_session_lock(tmp_path, monkeypatch):
    import bench_record_replay as brr
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    (tmp_path / 'record-config-arm-a.json').write_text('{}')
    ran, closed = [], []
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: (ran.append(a), SimpleNamespace(returncode=1, stdout='', stderr=''))[1])
    checks = []
    monkeypatch.setattr('bench_record_guard.arm_free', lambda arm, manual=None: checks.append(arm))  # the lease/hold check has its own test
    assert brr._read_live_norm_pose(tmp_path, 'arm_a', '/py') is None and ran == []  # no way to hold the lock: no read
    assert brr._read_live_norm_pose(tmp_path, 'arm_a', '/py', lambda: ([], 'session-arm_a.lock busy')) is None and ran == []
    assert brr._read_live_norm_pose(tmp_path, 'arm_a', '/py', lambda: ([SimpleNamespace(close=lambda: closed.append(1))], None)) is None
    assert len(ran) == 1 and closed == [1]  # read while held, released afterwards
    assert checks == ['arm_a'] * 3  # no hold(): none; busy lock: once, before; lock held: before it and again with it held


def test_match_follower_refuses_a_bad_mount_declaration_before_any_motion(tmp_path):
    leader_home, leader = _leader_for_match(tmp_path)
    (tmp_path / 'arm_s_leader.mount.json').write_text(json.dumps({'shoulder_pan': -1024}), encoding='utf-8')
    present = {'shoulder_pan': 0, 'shoulder_lift': 1000, 'elbow_flex': 1000, 'wrist_flex': 2000, 'wrist_roll': 0}
    with pytest.raises(ValueError, match='half a turn'):
        leader_home._match_target([2048, 1000, 1000, 2000, 2048], present, leader)


def test_match_follower_range_check_is_pinned_to_the_mapped_target_in_the_leader_range(tmp_path):
    """arm_s Leader pan rests at raw 4100..4180, past its calibrated range 0..4095; with mount -2048 the Follower pose
    2103 maps to one turn down (55), which is inside the range. The check places the mapped target in the Leader range
    (a window of the same width moved to the front); re-measuring the Leader range is follow-up work."""
    leader_home, leader = _leader_for_match(tmp_path)
    present = {'shoulder_pan': 4151, 'shoulder_lift': 1000, 'elbow_flex': 2000, 'wrist_flex': 2000, 'wrist_roll': 0}
    target = leader_home._match_target([2103, 1000, 2000, 2000, 2048], present, leader)
    assert target['shoulder_pan'] == 55
    narrow_home, narrow = _leader_for_match(tmp_path, ranges={'shoulder_pan': (100, 3000)})
    with pytest.raises(ValueError, match='shoulder_pan'):  # different ranges, different verdict: 55 and 4151 are both outside
        narrow_home._match_target([2103, 1000, 2000, 2000, 2048], present, narrow)


def test_leader_home_reports_torque_unconfirmed_when_the_connect_is_interrupted(tmp_path, monkeypatch):
    lh_spec = importlib.util.spec_from_file_location('leader_home', ROOT / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)
    cfg = tmp_path / 'rcfg.json'
    cfg.write_text(json.dumps({'teleop': {'type': 'omx_leader', 'id': 'arm_s_leader', 'port': '/dev/null'}}), encoding='utf-8')
    pose = tmp_path / 'pose.json'
    pose.write_text(json.dumps({'ticks': {n: 2048 for n in leader_home.BODY}}), encoding='utf-8')
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)

    def interrupted(_cfg):
        raise KeyboardInterrupt()

    monkeypatch.setattr(leader_home, '_connect_leader', interrupted)
    with pytest.raises(KeyboardInterrupt):
        leader_home.move_leader_home(cfg, 'arm_s', pose, 'hands-off:test:now')
    assert leader_home._END['torque_off_confirmed'] is False


def test_home_button_uses_separate_leader_option_and_homing_shows_hands_off_notice():
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    assert "leader_connected===true||" in js and "leader_connected!==false" in js and "$('home-include-leader')?.checked" in js
    assert 'id="home-include-leader" checked' in html and '리더도 함께' in html
    st_js = (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8')
    prm_js = (omx_dir / 'bench_record_params.js').read_text(encoding='utf-8')
    assert "leader_connected!==false" in st_js and "parseTickInput(" in prm_js
    assert '시작 전 리더를 팔로워 자세로 맞춤' in html
    assert '리더에서 손을 뗐습니다' not in html
    assert 'at_bench' not in html
    assert '리더가 움직입니다 — 손을 대지 마세요' in ui_js


def test_bench_phase_tabs_and_section_visibility_contract():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')

    for marker in ('id="phase-tabs"', 'data-phase-tab="setup"', 'data-phase-tab="prepare"',
                   'data-phase-tab="recording"', 'data-phase-tab="result"', 'id="prepare-ticks"', 'id="sp-fill"',
                   'id="ev-dataset"', 'id="ev-safe-end"', 'id="back-to-setup-btn"'):
        assert marker in html, marker

    expected_tabs = {
        'hdr-prepare-btn': {'setup'},
        'hdr-start-now-btn': {'setup'},
        'hdr-live-metrics': {'recording'},
        'hdr-result-actions': {'result'},
        'home-include-leader-group': {'setup'},
        'sec-cameras': {'setup', 'prepare', 'recording'},
        'sec-guide': {'setup'},
        'sec-telemetry': {'prepare', 'recording'},
        'sec-evidence': {'result'},
    }
    for sec_id, tabs in expected_tabs.items():
        m = re.search(rf'id="{sec_id}"[^>]*data-tabs="([^"]+)"', html)
        assert m, f'{sec_id} missing data-tabs'
        assert set(m.group(1).split()) == tabs, (sec_id, m.group(1))

    assert 'function resolveBenchPhase(' in ui_js and 'function applyBenchPhase(' in ui_js
    assert 'setManualBenchPhase' in cam_js
    assert '.app-shell[data-phase="recording"]' in css


def test_start_succeeds_without_at_bench(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    no_bench = {k: v for k, v in body.items() if k != 'at_bench'}
    bench.start(no_bench)
    assert finished(bench)['status'] == 'sealed'


def test_ui_auto_selects_recommended_and_generates_name_without_at_bench():
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))

    assert 'id="hdr-start-reasons"' in html
    assert 'id="ev-auto-home"' in html
    assert '포즈 저장 · 리더 정렬' in html
    assert '작업대 현장 확인 체크' not in ui_js
    assert 'hdr-start-reasons' in ui_js
    assert 'auto_home' in ui_js
    assert 'function autoCollectionName(' in app_js
    assert 'nameManuallyEdited' in app_js
    assert 'rec?.config' in app_js and 'rec?.caps' in app_js and 'rec?.calibrations' in app_js


def test_auto_home_runs_once_after_safe_end_and_never_after_unsafe_end(tmp_path, monkeypatch):
    # 1) Normal sealed completion -> go_home called once with include_leader=False
    bench, body, _, _ = _setup(tmp_path, monkeypatch, safe=True)
    home_calls = []
    bench.go_home = lambda b: (home_calls.append(b), {'home_moved': [b['arm']]})[1]
    bench.start(dict(body, at_bench=False))
    st = finished(bench)
    assert st['status'] == 'sealed'
    assert home_calls == [{'arm': 'arm_a', 'at_bench': True, 'include_leader': False}]
    assert st['auto_home']['ok'] is True

    # 2) Unsafe end -> go_home never called
    bench2, body2, _, _ = _setup(tmp_path / 'u', monkeypatch, safe=False)
    home_calls2 = []
    bench2.go_home = lambda b: (home_calls2.append(b), {'home_moved': [b['arm']]})[1]
    bench2.start(body2)
    st2 = finished(bench2)
    assert st2['status'] == 'unsafe_or_failed'
    assert home_calls2 == []

    # 3) go_home failure -> called once (no retry), error preserved on state
    bench3, body3, _, _ = _setup(tmp_path / 'f', monkeypatch, safe=True)
    home_calls3 = []

    def fail_home(b):
        home_calls3.append(b)
        raise ValueError('home requires an empty, folded arm')

    bench3.go_home = fail_home
    bench3.start(body3)
    st3 = finished(bench3)
    assert st3['status'] == 'sealed'
    assert len(home_calls3) == 1
    assert st3['auto_home']['ok'] is False
    assert 'folded arm' in st3['auto_home']['error']

    # 4) stopped_safe -> go_home called once
    bench4, body4, _, _ = _setup(tmp_path / 's', monkeypatch, record={
        'safe_end': True, 'torque_off_confirmed': True, 'caps_restored': True, 'manual_attention_required': False
    })
    orig_popen = bench4.popen
    bench4.popen = lambda cmd, cwd, **kw: (
        (Path(cwd) / 'session.json').write_text(json.dumps({
            'safe_end': True, 'torque_off_confirmed': True, 'caps_restored': True, 'manual_attention_required': False
        })),
        (Path(cwd) / 'clean-end.json').write_text(json.dumps({'clean': True})),
        SimpleNamespace(wait=lambda timeout=None: 1, poll=lambda: 1, returncode=1, send_signal=lambda s: None)
    )[2] if cmd[1].endswith('record_session.py') else orig_popen(cmd, cwd, **kw)
    monkeypatch.setattr('bench_record_safety._held_reason', lambda _arm: '')
    home_calls4 = []
    bench4.go_home = lambda b: (home_calls4.append(b), {'home_moved': [b['arm']]})[1]
    bench4.start(body4)
    st4 = finished(bench4)
    assert st4['status'] == 'stopped_safe'
    assert home_calls4 == [{'arm': 'arm_a', 'at_bench': True, 'include_leader': False}]
    assert st4['auto_home']['ok'] is True


def test_cargo_hold_grid_only_renders_for_ship_tasks():
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    assert 'id="sec-cameras" data-tabs="setup prepare recording"' in html
    assert "if(p!=='result')renderCamGuide();" in ui_js
    assert 'function taskFitsArm(' in ui_js and 'function resolveActiveZone(' in ui_js
    assert '||1;' not in ui_js
    assert 'ship-grid' in ui_js and 'stand-grid' in ui_js and 'arm-s-table' in ui_js and 'map-zone-tabs' in ui_js
    assert "box.hidden=(currentBenchPhase()==='result')" in ui_js
    assert 'c?.shot_arm' in ui_js and 'explicit===arm' in ui_js
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')
    assert '!st?.link&&(split||total===1)' in cam_js


def test_bench_ribbon_camera_first_drawers_and_no_motion():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')

    # 1) topbar removes duplicate arm pills (single selector stays in #arm-card-bar), keeps start, home, drawers, and estop as last element
    topbar_m = re.search(r'<header class="app-topbar"[^>]*>(.*?)</header>', html, re.S)
    assert topbar_m
    topbar = topbar_m.group(1)
    assert 'id="hdr-arm-pill"' not in topbar and 'id="rail-arm-pills"' not in topbar
    assert 'id="arm-card-bar"' in html
    for marker in ('id="phase-tabs"', 'id="hdr-record-btn"',
                   'aria-describedby="hdr-start-reasons"', 'id="hdr-home-btn"',
                   'data-drawer-btn="setup"', 'data-drawer-btn="bindings"',
                   'data-drawer-btn="start"', 'data-drawer-btn="records"', 'id="hdr-estop-btn"'):
        assert marker in topbar, marker
    ops_m = re.search(r'<section id="hdr-row-ops"[^>]*>(.*?)</section>', topbar, re.S)
    assert ops_m
    last_btn_m = list(re.finditer(r'<button\b[^>]*\bid="([^"]+)"', ops_m.group(1)))
    assert last_btn_m and last_btn_m[-1].group(1) == 'hdr-estop-btn'

    # 2) camera area is first element in .layout and CSS has no max-width cap on .layout
    layout_m = re.search(r'<div class="layout">(.*)', html, re.S)
    assert layout_m
    first_sec_m = re.search(r'<section\b[^>]*\bid="([^"]+)"', layout_m.group(1))
    assert first_sec_m and first_sec_m.group(1) == 'sec-cameras'
    assert html.count('id="cam-grid"') == 1
    assert not re.search(r'\.layout\{[^}]*max-width\s*:\s*\d', css)

    # 3) goal panel precedes guide in DOM, keeps swap/note IDs, and has large pick/place elements
    assert html.index('id="sec-goal"') < html.index('id="sec-guide"')
    for marker in ('id="goal-origin-name"', 'id="goal-target-name"', '집을 곳', '놓을 곳',
                   'id="swap-zones-btn"', 'id="cam-map-note"' if False else 'id="cam-guide"'):
        assert marker in html, marker

    # 4) drawers A~D live outside <main> in #side-drawer-host and are hidden by default
    main_end = html.index('</main>')
    assert re.search(r'<aside\b[^>]*id="side-drawer-host"[^>]*\bhidden\b', html[main_end:])
    for pane in ('setup', 'bindings', 'start', 'records'):
        assert re.search(rf'data-drawer-pane="{pane}"[^>]*\bhidden\b', html[main_end:]), pane
    for drawer_id in ('sec-setup', 'sec-bindings', 'sec-start', 'sec-pipeline', 'sec-recent'):
        assert html.index(f'id="{drawer_id}"') > main_end

    # 5) D-220: no transition, animation, or @keyframes in CSS
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)


def test_bench_v2_camera_pip_goal_lines_and_nonblocking_top_warning():
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))

    # 1) Primary camera + secondary PiP overlay structure and switch function
    for marker in ('.cam-primary', '.cam-pip-stack', '.cam-pip'):
        assert marker in css and marker[1:] in app_js, marker
    assert 'function switchPrimaryCam(' in app_js
    assert 'function defaultPrimaryCam(' in app_js
    assert "arm==='arm_s'?'arm_s_top':'top'" in app_js

    # 2) Goal panel stacked label/name/sub + progress bar
    for marker in ('id="goal-origin-sub"', 'id="goal-target-sub"', 'id="goal-prog-fill"'):
        assert marker in html, marker
    assert 'function splitSpotDisplay(' in ui_js
    assert '.goal-line{display:flex;flex-direction:column;' in css

    # 3) Missing top preview warns without blocking start; arm_s checks arm_s_top
    assert "box.dataset.blocking=issues.length?'1':'0'" in ui_js
    assert "biEl.dataset.blocking!=='0'" in ui_js
    assert "const topName=arm==='arm_s'?'arm_s_top':'top';" in ui_js
    assert '.reason-strip.muted' in css
    assert "setNotice('start-reasons','muted',warnText)" in ui_js  # v4: the one notice surface carries the muted warning


def test_bench_v3_always_visible_goal_records_live_map_note_and_topbar_menu():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = ((omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')
             + (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8'))
    app_js = ((omx_dir / 'bench_record_app.js').read_text(encoding='utf-8') + (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8'))

    # The goal stays visible in every phase and gives a task picker when empty.
    assert re.search(r'<section\b[^>]*id="sec-goal"(?![^>]*data-tabs)', html)
    empty_m = re.search(r'<div id="goal-empty"[^>]*>(.*?)</div>\s*<div id="goal-active"', html, re.S)
    assert empty_m and '집을 곳' in empty_m.group(1) and '놓을 곳' in empty_m.group(1) and 'id="goal-pick-btn"' in empty_m.group(1)
    for marker in ('id="goal-name-btn"', 'id="sb-param-config"', 'id="sb-param-caps"', 'id="sb-param-episodes"', 'id="sb-param-timing"', 'id="goal-result-line"'):
        assert marker in html, marker

    # The records drawer is allowed read-only during live.
    assert 'id="records-fieldset"' in html
    assert "b.dataset.drawerBtn!=='records'" in ui_js
    assert "name!=='records'" in app_js
    assert "activeDrawerName?.()!=='records'" in ui_js

    # 3) cam-map-note is actually unhidden when set and reports missing cards
    assert '이 조합의 과제 카드 없음' in ui_js
    assert 'nEl.hidden=!lastMapNote' in ui_js

    # 4) Topbar nowrap, single arm-card-bar selector, and collapsible drawer menu
    assert 'id="btn-drawer-menu"' in html and 'id="drawer-menu-pop"' in html
    assert '.drawer-menu-wrap.open .drawer-menu-pop' in css
    assert '.arm-card-grid{' in css and 'id="rail-arm-pills"' not in html
    assert 'white-space:nowrap' in css
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)


def test_a_leader_roll_15_degrees_off_is_moved_onto_the_follower_but_a_resting_lift_is_kept(tmp_path):
    leader_home, leader = _leader_for_match(tmp_path)
    present = {'shoulder_pan': 0, 'shoulder_lift': 1000, 'elbow_flex': 2000, 'wrist_flex': 2000, 'wrist_roll': 952 + 171}  # roll 15 degrees off
    target = leader_home._match_target([2048, 1150, 2000, 2000, 3000], present, leader)
    assert target['wrist_roll'] == 952 and target['shoulder_lift'] == 1000  # follower roll 3000 - mount(-2048) = 5048, one turn down


def test_starting_step_follows_the_recorder_log(tmp_path):
    import bench_record_step as step
    assert step.starting_step({'status': 'homing', 'step': 'leader_align'})['starting_step'] == 'leader_align'
    assert step.starting_step({'status': 'idle'})['starting_step'] is None
    folder = tmp_path / 'session'
    folder.mkdir()
    state = {'status': 'handing_over', 'folder': str(folder)}
    assert step.starting_step(state)['starting_step'] == 'starting_recorder'  # no log yet
    log = folder / 'bench.log'
    log.write_text('INFO eo_utils.py:106 Using video codec: libsvtav1\n')
    assert step.starting_step(state)['starting_step'] == 'connecting_cameras'
    aligning = ('follower: phase=aligning; actual_joint=wrist_roll actual=1948 target=2119 error_deg=15.03 Present_PWM=0 PWM_Limit=300; '
                'command_joint=wrist_roll command=1948 target=2119 error_deg=15.03\n')
    log.write_text('INFO Recording episode 0\n' + aligning)
    got = step.starting_step({**state, 'status': 'recording'})
    assert got['starting_step'] == 'aligning' and got['starting_deg_left'] == 15.03
    log.write_text('INFO Recording episode 0\n' + aligning + 'follower: aligned; full-arm tracking (body and gripper) limit 25 deg/s\n')
    assert step.starting_step({**state, 'status': 'recording'})['starting_step'] is None


def test_status_json_carries_the_starting_step(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    bench.state = {'status': 'homing', 'name': 'home-arm_a', 'step': 'follower_home'}
    assert bench.status()['starting_step'] == 'follower_home'


def test_at_home_reads_the_live_pose_the_recorder_already_writes(tmp_path):
    import os
    import bench_record_step as step
    library, live = tmp_path / 'chunks.json', tmp_path / 'live.json'
    library.write_text(json.dumps({'chunks': {'home': [[9.0, 9.0, 9.0, 9.0, 9.0, 9.0], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]]}}))  # the last frame is the home
    live.write_text(json.dumps({'state': [1.4, 2.0, 3.0, 4.0, 5.0, 40.0]}))  # the gripper does not matter
    mtime = live.stat().st_mtime
    assert step.at_home(live, library, mtime - 1.0, now=lambda: mtime + 1.0)
    assert not step.at_home(live, library, mtime + 0.5, now=lambda: mtime + 1.0)  # written before this home request began
    live.write_text(json.dumps({'state': [9.0, 9.0, 9.0, 9.0, 9.0, 9.0]}))  # the first frame is not the home
    assert not step.at_home(live, library, 0, now=lambda: live.stat().st_mtime + 1.0)
    live.write_text(json.dumps({'state': [1.0, 2.0, 3.0, 4.0, 6.5, 6.0]}))  # one body joint 1.5 units off
    assert not step.at_home(live, library, 0, now=lambda: live.stat().st_mtime + 1.0)
    live.write_text(json.dumps({'state': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}))
    stamp = live.stat().st_mtime
    assert not step.at_home(live, library, 0, now=lambda: stamp + 60)  # a stale file proves nothing
    assert not step.at_home(tmp_path / 'missing.json', library, 0)


def _skip_setup(tmp_path, monkeypatch, live_state, child_exited=False):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    (bench.prep / 'chunks-arm-s-inplace-live.json').write_text(json.dumps({'chunks': {'home': [[0.0] * 6, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]]}}))
    (bench.prep / 'chunk-io-s').mkdir()
    live = bench.prep / 'chunk-io-s' / 'live.json'
    ran = _home_with_stages(bench, monkeypatch, tmp_path, [('home', None)])

    def poll():  # the recorder this request started writes its live pose
        if not child_exited:
            live.write_text(json.dumps({'state': live_state}))
        return 0 if child_exited else None
    bench.popen = lambda command, cwd, **kw: SimpleNamespace(
        poll=poll, wait=lambda timeout=None: 0, returncode=0, send_signal=lambda s: None)
    return bench, ran, live


def test_go_home_skips_the_pipeline_only_for_the_live_pose_of_the_recorder_it_started(tmp_path, monkeypatch):
    bench, ran, live = _skip_setup(tmp_path, monkeypatch, [1.2, 2.0, 3.0, 4.0, 5.0, 9.0])
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s'] and ran == []
    bench, ran, live = _skip_setup(tmp_path / 'b', monkeypatch, [1.2, 2.0, 3.0, 4.0, 7.0, 6.0])  # roll 2 units off: the home stage runs
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s'] and ran == ['home']
    bench, ran, live = _skip_setup(tmp_path / 'c', monkeypatch, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], child_exited=True)
    live.write_text(json.dumps({'state': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}))  # the recorder already exited: the file proves nothing
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s'] and ran == ['home']


def test_the_leader_aligns_and_the_caps_come_back_before_the_observers_are_restored(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    _home_with_stages(bench, monkeypatch, tmp_path, [('home', None), ('home', None)])  # one answer per go_home below
    ran = _leader_popen(bench, _LeaderProc(), monkeypatch)
    inner = bench.popen

    def popen(command, cwd, **kw):
        if command[1].endswith('leader_home.py'):
            calls.append(('leader_home',))
        return inner(command, cwd, **kw)
    bench.popen = popen
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True, 'include_leader': True})['home_moved'] == ['arm_s']
    names = [c[0] for c in calls]
    assert 'stop' in names and names.index('leader_home') < names.index('start') and ran
    calls.clear()
    bench.popen = lambda command, cwd, **kw: (_ for _ in ()).throw(ValueError('boom')) if command[1].endswith('leader_home.py') else inner(command, cwd, **kw)
    with pytest.raises(ValueError, match='boom'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True, 'include_leader': True})
    assert 'start' in [c[0] for c in calls]  # a failed alignment still brings the units back


def test_bench_ui_shows_outbound_stand_and_filters_arm_b():
    root = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    map_js = (root / 'bench_record_map.js').read_text(encoding='utf-8')
    app = (root / 'bench_record_app.js').read_text(encoding='utf-8')
    for marker in ('data-spot="stand"', '반출대', 'describeSpot', "'stand:r1-s1'", "'stand:r1-s1-t1'", r'\bstand\b', "arm==='arm_b'"):
        assert marker in map_js, marker
    assert 'taskFitsArm' in app


def test_bench_ui_activity_log_smooth_camera_polling_and_pre_start_home_contract():
    import re
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = (omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
    st_js = (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8')
    app_js = (omx_dir / 'bench_record_app.js').read_text(encoding='utf-8')
    dr_js = (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8')
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')

    footer = html.split('<footer id="status-bar"', 1)[1].split('</footer>', 1)[0]
    assert 'id="activity-log-bar"' in footer and 'id="activity-log-text"' in footer
    assert 'id="activity-log-bar" class="activity-log-bar"' in footer
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)
    assert '.status-bar{position:fixed' in css and '@media(max-width:1366px)' in css and '.activity-log-bar{' in css
    assert 'function setActivity(' in ui_js and 'noticeHistory.length>20' in ui_js
    assert 'f.arm.value!==st.arm' in st_js and 'setActivity(' in st_js
    assert 'setInterval(pollCameras,1500)' in app_js and 'setInterval(tickCameraFrames,150)' in app_js
    assert 'new Image()' in app_js and 'emptyCamPolls>=3' in app_js
    assert "img.style.display='none'" not in app_js.split('function pollCameras', 1)[1].split('async function pollStatus', 1)[0].split('applyCameraLayout()', 1)[1]
    assert "querySelector('.btn-lbl')" in dr_js and 'home_before_start:Boolean(' in dr_js and 'setActivity(' in dr_js
    assert 'if(typeof benchSessionActive===\'function\'&&benchSessionActive())return;' in cam_js
    assert "episodeAction('/record_episode')" in cam_js and "episodeAction('/finish','/stop')" in cam_js and "episodeAction('/api/episode/rerecord')" in cam_js


def test_ui_connected_arm_cards_zoomed_map_and_inline_params_panel(tmp_path, monkeypatch):
    import re, threading, urllib.request
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    app_js = (omx_dir / 'bench_record_app.js').read_text(encoding='utf-8')
    params_js = (omx_dir / 'bench_record_params.js').read_text(encoding='utf-8')
    map_js = (omx_dir / 'bench_record_map.js').read_text(encoding='utf-8')

    for marker in ('id="arm-card-bar"', 'id="sb-speed-pills"', 'id="sb-joint-caps-table"',
                   'id="sb-caps-save-btn"', 'id="map-modal-host"', '/bench_record_params.js',
                   'id="sb-grip-map"', 'id="sb-grip-save-btn"'):
        assert marker in html, marker
    assert html.index('id="arm-card-bar"') < html.index('id="sec-goal"')
    assert 'max-height:108px' not in css and 'min-height:176px' in css
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)
    for fn in ('function renderArmCards(', 'function renderParamsPanel(', 'function submitCaps(', '/api/teleop_speed',
               'function loadGripMaps(', 'function submitGripMap(', '/api/grip_map', '180,240'):
        assert fn in params_js, fn
    assert 'arm_connectivity' in app_js and 'pollArms()' in app_js and 'loadGripMaps()' in app_js
    assert 'function renderArmSMapSvg(' in map_js and 'id="map-expand-btn"' in map_js and 'function openMapModal(' in map_js
    assert 'renderArmSMapSvg(zoneBg,zoneCol,validArm,cards)' in map_js

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f'http://127.0.0.1:{srv.server_port}'
        with urllib.request.urlopen(base + '/bench_record_params.js', timeout=5) as r:
            assert r.status == 200 and b'renderArmCards' in r.read()
        req = urllib.request.Request(base + '/api/teleop_speed', data=b'{"arm":"arm_s","stage":90}',
                                     headers={'Content-Type': 'application/json', 'X-Bench': '1'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200 and json.loads(r.read())['teleop_speed_declared']['arm_s']['stage'] == 90
        with urllib.request.urlopen(base + '/api/grip_map', timeout=5) as r:
            assert r.status == 200 and 'arm_s' in json.loads(r.read())['arms']
        greq = urllib.request.Request(
            base + '/api/grip_map',
            data=json.dumps({'arm': 'arm_s', 'leader_closed': 1930, 'leader_open': 2850,
                             'follower_closed': 2000, 'follower_open': 2800}).encode(),
            headers={'Content-Type': 'application/json', 'X-Bench': '1'}, method='POST',
        )
        with urllib.request.urlopen(greq, timeout=5) as r:
            assert r.status == 200 and json.loads(r.read())['gripper']['follower_open'] == 2800
    finally:
        srv.shutdown()
        srv.server_close()


def test_ui_audio_cues_and_quick_restart_after_result_contract():
    import re
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    ui_js = (omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')
    st_js = (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8')
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')
    dr_js = (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8')

    assert 'id="hdr-sound-btn"' in html and 'id="hdr-quick-restart-btn"' in html
    ops_m = re.search(r'<section id="hdr-row-ops"[^>]*>(.*?)</section>', html, re.S)
    assert ops_m
    last_btn = list(re.finditer(r'<button\b[^>]*\bid="([^"]+)"', ops_m.group(1)))
    assert last_btn and last_btn[-1].group(1) == 'hdr-estop-btn'
    context = re.search(r'<div id="hdr-row-menu"[^>]*>(.*?)<section id="hdr-row-ops"', html, re.S).group(1)
    assert 'id="rail-arm-pills"' not in context
    context_order = ('h1', 'hdr-task-summary', 'goal-name-btn', 'ftr-server',
                     'hdr-cam-health', 'hdr-help-btn', 'btn-drawer-menu', 'hdr-refresh-btn')
    positions = [context.index('<h1>' if m == 'h1' else f'id="{m}"') for m in context_order]
    assert positions == sorted(positions)

    for marker in ('function benchBeep(', 'omx_bench_sound', 'BEEP_PATTERNS', 'setSoundEnabled'):
        assert marker in ui_js, marker
    for cue in ("benchBeep('ready')", "benchBeep('rec_start')", "benchBeep('saved')",
                "benchBeep('done')", "benchBeep('warn')"):
        assert cue in st_js, cue
    for marker in ("benchBeep('countdown')", "benchBeep('rerecord')",
                   'function quickRestartAfterResult(', 'hdr-quick-restart-btn'):
        assert marker in cam_js, marker
    assert 'function bumpCollectionName(' in dr_js and 'skipHome' in dr_js
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)


def test_result_home_button_auto_home_view_and_arm_connectivity_resilience(tmp_path):
    import bench_record_guard as guard
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    st_js = (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8')
    dr_js = (omx_dir / 'bench_record_drawers.js').read_text(encoding='utf-8')
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')

    assert 'id="hdr-result-home-btn"' in html
    assert html.index('id="hdr-result-home-btn"') < html.index('id="hdr-quick-restart-btn"')
    assert 'function autoHomeView(' in st_js and 'st.stop_cause' in st_js
    assert 'function triggerHomePose(' in dr_js and 'fold_unfolded:' in dr_js
    assert 'hdr-result-home-btn' in cam_js and "rhBlocked" in cam_js
    (tmp_path / 'record-config-arm-s.json').write_text(json.dumps({'robot': None, 'teleop': 'bad'}))
    assert guard.arm_connectivity(tmp_path, 'arm_s') == {'connected': None, 'follower_connected': None, 'leader_connected': None}


def test_arm_ab_ui_priority_layout_no_wrap_and_camera_health_contract():
    import re
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    app_js = (omx_dir / 'bench_record_app.js').read_text(encoding='utf-8')
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')
    st_js = (omx_dir / 'bench_record_status.js').read_text(encoding='utf-8')

    assert 'input.jc-inp{' in css and '.jc-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))' in css
    assert '.app-shell[data-phase="setup"] #sec-params{order:-1}' in css
    assert '.app-topbar:has(.drawer-menu-wrap.open){padding-bottom:44px}' in css
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)
    assert '<details class="card acc-card sb-sec" id="sec-status"' in html and 'id="sec-status" open' not in html
    assert '<details id="sb-joint-caps-box"' in html
    assert 'class="pill-btn active" data-tfilter="arm" aria-pressed="true"' in html
    assert 'id="cleanup-empty-ds-btn"' in html and 'id="ev-delete-empty-btn"' in html
    assert "OPTIONAL_CAMS=new Set(['arm_s_top'])" in cam_js and 'function expectedCamsForArm(' in cam_js
    assert "if(role==='left_wrist')return ['arm_a_wrist'];" in cam_js and "if(role==='right_wrist')return ['arm_b_wrist'];" in cam_js
    assert 'function syncMissingCamPlaceholders(' in cam_js and "LAST_ARM_KEY='omx_bench_last_arm'" in app_js
    assert "$('hdr-cam-health').hidden=false;" in st_js


def test_camera_badges_tell_standby_from_active_recording():
    """D-omx-bench-rec-ui: setup/prepare/result/idle must never look like '● 녹화'.
    Only phase 'recording' AND server status 'recording' is an active take."""
    omx_dir = ROOT / 'deploy/robot/omx'
    html = (omx_dir / 'bench_record.html').read_text(encoding='utf-8')
    css = (omx_dir / 'bench_record.css').read_text(encoding='utf-8')
    app_js = (omx_dir / 'bench_record_app.js').read_text(encoding='utf-8')
    cam_js = (omx_dir / 'bench_record_cam.js').read_text(encoding='utf-8')
    ui_js = (omx_dir / 'bench_record_ui.js').read_text(encoding='utf-8')

    # 1) one truth source: standby phases (setup/prepare/result/idle) are never an active take
    assert 'function isActivelyRecording()' in ui_js
    assert "return currentBenchPhase()==='recording'&&lastStatus?.status==='recording';" in ui_js
    # phase transitions re-render the badges through applyBenchPhase
    assert "if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();" in ui_js

    # 2) camera boxes are created neutral (armed '녹화 대상'), never 'on' with '● 녹화'
    assert "rec.className='cam-rec-badge armed';rec.textContent='녹화 대상';" in app_js
    assert '● 녹화' not in app_js  # no badge or note may hardcode the old active-recording claim

    # 3) the mask branches on the live state: only live shows '● 녹화 중', standby shows '녹화 대상'
    assert "badge.textContent=isRec?'● 녹화 중':'미포함';" in cam_js
    assert "badge.className='cam-rec-badge '+(isRec?'live':'off');" in cam_js
    assert "badge.textContent=isRec?'녹화 대상':'미포함';" in cam_js
    assert "badge.className='cam-rec-badge '+(isRec?'armed':'off');" in cam_js
    assert "badge.title=isRec?'녹화 시작 시 이 카메라가 포함됩니다 (현재 미리보기 대기)':'';" in cam_js
    assert "badge.title=isRec?'현재 에피소드 녹화 중':'';" in cam_js
    # cam-note: standby prefix differs from the recording prefix and names the rec targets as '녹화 대상:'
    assert "?'녹화 중 — '+(arm||'선택 암')" in cam_js
    assert ":(currentBenchPhase()==='prepare'?'텔레옵 연동 (녹화 대기)':'실시간 미리보기 (녹화 대기)')+' — '+(arm||'선택 암')" in cam_js
    assert "parts.push((live?'녹화: ':'녹화 대상: ')" in cam_js
    # the pre-mask note text in pollCameras also stays standby-honest while no recording is live
    assert "const recNow=typeof isActivelyRecording==='function'&&isActivelyRecording();" in app_js
    assert "(recNow?'녹화 중 — ':'실시간 미리보기 (녹화 대기) — ')" in app_js

    # 4) missing camera placeholders warn, never borrow the active classes
    assert "rec.className='cam-rec-badge missing';rec.textContent='미수신';" in cam_js

    # 5) the header action button is a verb: ready offers '● 녹화 시작', recording offers '■ 녹화 끝'
    assert "recording?'■ 녹화 끝':legacyStarting?'■ 준비 취소':ready?'● 녹화 시작':'● 녹화'" in cam_js
    assert '<span class="btn-lbl">● 녹화 시작</span>' in html

    # 6) CSS carries the semantic badge classes; the old green 'on' rule and its writers are gone
    for rule in ('.cam-rec-badge.live{border:1px solid var(--crit);color:#ff9497}',
                 '.cam-rec-badge.armed{border:1px solid var(--bd);color:var(--ink)}',
                 '.cam-rec-badge.off{border:1px solid var(--bd);color:var(--ink-q)}',
                 '.cam-rec-badge.missing{border:1px solid var(--warn);color:var(--warn)}'):
        assert rule in css, rule
    assert '.cam-rec-badge.on{' not in css
    for src in (app_js, cam_js, html):
        assert 'cam-rec-badge on' not in src
    assert "isRec?'● 녹화'" not in cam_js and "'미녹화'" not in cam_js


def test_camera_badges_follow_phase_and_status_in_the_dom(tmp_path):
    """Behavior: run the real ui.js/cam.js against a stub DOM and read the rendered badges."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is unavailable; the source contract test above still runs')
    harness = tmp_path / 'cam_badge_contract.js'
    harness.write_text(_CAM_BADGE_HARNESS, encoding='utf-8')
    run = subprocess.run([node, str(harness), str(ROOT / 'deploy/robot/omx')], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


_CAM_BADGE_HARNESS = r'''
const fs=require('fs'),path=require('path'),vm=require('vm');
const dir=process.argv[2];
const fails=[];
const ok=(c,m)=>{if(!c)fails.push(m);};
const makeEl=()=>({className:'',textContent:'',title:'',hidden:false,dataset:{},style:{},open:false,
  classList:{add(){},remove(){},toggle(){},contains(){return false}},
  append(){},addEventListener(){},setAttribute(){},removeAttribute(){},
  querySelector(){return null},querySelectorAll(){return []}});
const form={arm:{value:'arm_a'},config:{value:'cfg'},caps:{value:''},name:{value:''},task:{value:''}};
const note=makeEl();
const boxes=['top','side','arm_a_wrist','front'].map(lbl=>{
  const badge=makeEl();
  return {lbl,badge,dataset:{camBox:lbl},classList:{toggle(){},contains(){return false}},
    querySelector:sel=>sel==='.cam-rec-badge'?badge:null};
});
const grid=makeEl();
grid.querySelectorAll=sel=>sel.indexOf('cam-box')>=0?boxes:[];
const byId={'bench-form':form,'cam-grid':grid,'cam-note':note},generic={};
const getEl=id=>byId[id]||(generic[id]||(generic[id]=makeEl()));
const ctx={console,
  document:{getElementById:getEl,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>makeEl(),addEventListener(){}},
  localStorage:{getItem(){return null},setItem(){}},
  setTimeout,clearTimeout,setInterval:()=>0,clearInterval,
  ResizeObserver:class{observe(){}}};
ctx.window=ctx;
ctx.globalThis=ctx;
vm.createContext(ctx);
const load=f=>vm.runInContext(fs.readFileSync(path.join(dir,f),'utf8'),ctx,{filename:f});
load('bench_record_ui.js');
ctx.ARM_PREVIEW_CAMS={arm_a:['top','side','arm_a_wrist']};
ctx.camLabels=['top','side','arm_a_wrist','front'];
ctx.renderCamGuide=()=>{};
ctx.updateGoalSummaryRows=()=>{};
ctx.init=()=>{};
ctx.pollArms=()=>{};
load('bench_record_cam.js');
const run=st=>vm.runInContext('lastStatus='+JSON.stringify(st)+';syncBenchPhase();',ctx);
const badge=lbl=>boxes.find(b=>b.lbl===lbl).badge;
const INCLUDED=['top','side','arm_a_wrist'];

for(const [phase,st,prefix,live] of [
  ['setup',{status:'idle',phase:'setup'},'실시간 미리보기 (녹화 대기) — arm_a · 녹화 대상: top, side, arm_a_wrist',false],
  ['prepare',{status:'idle',phase:'prepare'},'텔레옵 연동 (녹화 대기) — arm_a · 녹화 대상: top, side, arm_a_wrist',false],
  ['result',{status:'sealed',phase:'result'},'실시간 미리보기 (녹화 대기) — arm_a · 녹화 대상: top, side, arm_a_wrist',false],
  ['recording',{status:'recording',phase:'recording'},'녹화 중 — arm_a · 녹화: top, side, arm_a_wrist',true],
]){
  run(st);
  ok(vm.runInContext('isActivelyRecording()',ctx)===live,phase+': isActivelyRecording');
  for(const lbl of INCLUDED){
    const wantText=live?'● 녹화 중':'녹화 대상';
    const wantClass='cam-rec-badge '+(live?'live':'armed');
    ok(badge(lbl).textContent===wantText,phase+': '+lbl+' text='+badge(lbl).textContent);
    ok(badge(lbl).className===wantClass,phase+': '+lbl+' class='+badge(lbl).className);
    ok(badge(lbl).title===(live?'현재 에피소드 녹화 중':'녹화 시작 시 이 카메라가 포함됩니다 (현재 미리보기 대기)'),
      phase+': '+lbl+' title='+badge(lbl).title);
  }
  ok(badge('front').textContent==='미포함',phase+': excluded text='+badge('front').textContent);
  ok(badge('front').className==='cam-rec-badge off',phase+': excluded class='+badge('front').className);
  ok(note.textContent===prefix+' · 미포함: front',phase+': note='+note.textContent);
}

run({status:'sealing',phase:'recording'});
ok(vm.runInContext('isActivelyRecording()',ctx)===false,'recording phase + sealing status must be standby');
ok(badge('top').textContent==='녹화 대상','sealing: text='+badge('top').textContent);
ok(badge('top').className==='cam-rec-badge armed','sealing: class='+badge('top').className);

if(fails.length){console.error('FAIL\n'+fails.join('\n'));process.exit(1);}
console.log('PASS');
'''


def test_leader_check_renders_on_arm_cards_and_notice(tmp_path):
    import shutil, subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is unavailable')
    harness = tmp_path / 'leader_check_ui.js'
    harness.write_text(r'''
const fs=require('fs'),path=require('path'),vm=require('vm');
const dir=process.argv[2];
const mk=(tag)=>({tagName:tag||'div',className:'',textContent:'',title:'',hidden:false,disabled:false,dataset:{},style:{},children:[],
  classList:{add(){},remove(){},toggle(){},contains(){return false}},
  setAttribute(){},append(...xs){this.children.push(...xs);},addEventListener(){},
  querySelector(){return null},querySelectorAll(){return []},closest(){return {parentElement:{hidden:false}};}});
const bar=mk('div'), notices=[];
const byId={'arm-card-bar':bar,'bench-form':{arm:{value:'arm_a'},config:{value:'c',selectedOptions:[{}]},caps:{value:'k',selectedOptions:[{}]},name:{value:'live-a'},rig_revision:{value:'r1'},task:{value:''}},'cal-robot-list':mk(),'cal-leader-list':mk(),'binding-issues':Object.assign(mk(),{hidden:true}),'start-guard-note':mk(),'stop-note':mk()};
const ctx={console,document:{getElementById:id=>byId[id]||(byId[id]=mk()),createElement:t=>mk(t),querySelectorAll:()=>[]},
  choices:{arms:['arm_a','arm_s'],arm_connectivity:{arm_a:{connected:true,follower_connected:true,leader_connected:true},arm_s:{connected:true,follower_connected:true,leader_connected:true}},instances:{arm_a:'f1',arm_s:'f2'},arm_bindings:{arm_a:{},arm_s:{}}},
  armContractValid:()=>true,armVerifiedBindings:()=>({}),lastStatus:{status:'idle',active_locks:[]},statusLoaded:true,benchSessionActive:()=>false,poseInFlight:false,startInFlight:false,stopInFlight:false,cameraRestartInFlight:false,NAME_RE:/^[a-z0-9-]+$/,poseFeedbackUntil:0,poseFeedbackMsg:'',
  lastArmsStatus:{arm_a:{connected:true,follower_connected:true,leader_connected:true},arm_s:{connected:true,follower_connected:true,leader_connected:true}},
  lastLeaderCheck:{arm_a:{over_limit:false,max_deg:2.8},arm_s:{over_limit:true,max_deg:347.9,message:'손으로 가깝게 옮기세요'}},
  f:byId['bench-form'],$:id=>byId[id]||(byId[id]=mk()),
  setTimeout,clearTimeout,setInterval:()=>0,clearInterval,cueInit:false,prevCueFault:false,lastTelemetry:null,lastCamState:null,
  setNotice:(id,tone,msg)=>notices.push([id,tone,msg]),clearNotice:(id)=>notices.push([id,'clear','']),
  updateCameraRecordingMaskHook(){},updateCameraRecordingMask(){},updateGoalSummaryRows(){},renderCapsEditor(){},renderParamsPanel(){}};
ctx.window=ctx;ctx.globalThis=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(dir,'bench_record_params.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(path.join(dir,'bench_record_status.js'),'utf8'),ctx);
ctx.renderParamsPanel=()=>{};
ctx.renderArmCards();
const txt=(n)=>n.textContent+(n.children||[]).map(txt).join('|');
const out=txt(bar);
if(!out.includes('LΔ2.8°')||!out.includes('리더 348° 초과')||!out.includes('LΔ348°!')){console.error('BAD CARDS:',out);process.exit(1);}
byId['bench-form'].arm.value='arm_s';
ctx.validateStart();
const w=notices.find(x=>x[0]==='leader-check'&&x[1]==='warn');
if(!w||!w[2].includes('손으로 가깝게')){console.error('BAD NOTICE:',notices);process.exit(1);}
console.log('PASS');
''', encoding='utf-8')
    run = subprocess.run([node, str(harness), str(ROOT / 'deploy/robot/omx')], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_bench_tones_keep_normal_and_idle_quiet_and_disconnect_warn():
    import re
    omx = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    src = {n: (omx / n).read_text(encoding='utf-8') for n in (
        'bench_record.html', 'bench_record_cam.js', 'bench_record_app.js', 'bench_record_ui.js', 'bench_record_pipeline.js',
        'bench_record_status.js', 'bench_record_review.js', 'bench_camera_alignment.js', 'bench_record.css')}
    html, cam, app, st, rv = (src[n] for n in ('bench_record.html', 'bench_record_cam.js', 'bench_record_app.js',
                                                'bench_record_status.js', 'bench_record_review.js'))
    assert "dataset.tone=ok?'':'warn'" in cam and "setNotice('conn-error','warn'," in app
    for n in ('bench_record_ui.js', 'bench_record_pipeline.js', 'bench_record_cam.js'):
        assert "idle:['대기','']" in src[n], n
    assert 'id="hdr-cam-health">' in html and 'id="mh-torque-badge" class="badge mono">' in html
    assert 'id="manual-hold-card" aria-labelledby="h-manual-hold" hidden' in html and 'id="mh-reason" class="mh-reason" role="alert"' in html
    assert re.search(r'id="hdr-start-now-btn"[^>]*aria-describedby="hdr-start-reasons"', html)
    assert "stale: '조명 판정 지연'" in src['bench_camera_alignment.js'] and "missing: '조명 정보 없음'" in src['bench_camera_alignment.js']
    assert "||'최신')" in app and "'마지막 확인 · '+nowText()+' · 브라우저 수신'" in st and '원인 미상' not in st
    assert "setReqError('자동 복구 보류" not in rv and 'setReqError(guide)' not in rv and 'qa.replaceChildren(...qaOld)' in rv
    assert not re.search(r'font-size:\.(6\d|7[0-4])rem', src['bench_record.css'])
