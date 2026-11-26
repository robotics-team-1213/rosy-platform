"""Bench recording screen decisions (2026-11-26 panel, bench-r2): stop label, recovery order, record fill, shared-value parity."""
import re

from test_omx_bench_record import ROOT

OMX = ROOT / 'deploy/robot/omx'
WEB = ROOT / 'shared/web'


def _read(path):
    return path.read_text(encoding='utf-8')


def test_stop_button_says_what_it_sends():
    html, cam_js, css = _read(OMX / 'bench_record.html'), _read(OMX / 'bench_record_cam.js'), _read(OMX / 'bench_record.css')
    btn = re.search(r'<button[^>]*id="hdr-estop-btn"[^>]*>([^<]*)</button>', html)
    assert btn.group(1) == '녹화 중지'
    assert '비상정지' not in btn.group(0) and 'E-Stop' not in btn.group(0)  # /stop is a normal end, not a power cut
    note_id = re.search(r'aria-describedby="([^"]+)"', btn.group(0)).group(1)
    assert re.search(rf'id="{note_id}"[^>]*>전원 차단은 작업대 전원 스위치<', html)
    handler = cam_js.split("$('hdr-estop-btn').addEventListener", 1)[1].split('finally{', 1)[0]
    assert "api('/stop',{})" in handler
    assert '비상정지' not in handler and 'E-Stop' not in handler
    assert re.search(r'\.btn-estop\{[^}]*background:var\(--crit\)', css)  # danger fill stays


def test_manual_hold_puts_system_recovery_first_with_one_primary():
    html, review_js = _read(OMX / 'bench_record.html'), _read(OMX / 'bench_record_review.js')
    card = html.split('id="manual-hold-card"', 1)[1].split('id="mh-log-btn"', 1)[0]
    assert card.index('id="mh-quick-actions"') < card.index('id="mh-clear-btn"')
    assert 'btn-primary' not in card  # the only primary is the JS-built auto-recover button
    quick = review_js.split("const qa=$('mh-quick-actions');", 1)[1].split('\n  }\n', 1)[0]
    assert re.findall(r"className='(btn-[a-z]+)", quick).count('btn-primary') == 1
    assert "arBtn.id='mh-auto-recover-btn';arBtn.className='btn-primary btn-xs'" in quick


def test_record_button_is_neutral_with_a_red_dot():
    css = _read(OMX / 'bench_record.css')
    rule = re.search(r'\.btn-rec\{([^}]*)\}', css).group(1)
    assert 'var(--crit)' not in rule and 'background:var(--ink)' in rule
    assert '.btn-rec .btn-lbl::first-letter{color:var(--crit)}' in css


# bench copy name -> shared/web/tokens.css name; the bench page is standalone (decision 2-b), so values must match.
TOKEN_PAIRS = {
    'ground': 'ground', 'ground-deep': 'ground-deep', 'ground-raise': 'ground-raise', 'ground-soft': 'ground-soft',
    'ground-card': 'ground-card', 'ink': 'ink', 'ink-q': 'ink-quiet', 'crit': 'status-crit', 'warn': 'status-warn',
    'good': 'status-good', 'pri': 'series-primary', 'rose': 'brand-rose',
}


def _vars(block):
    return {m.group(1): m.group(2).strip().lower() for m in re.finditer(r'--([\w-]+):\s*([^;]+);', block)}


def test_bench_colour_copies_match_shared_tokens():
    bench = _vars(re.search(r':root\{(.*?)\}', _read(OMX / 'bench_record.css'), re.S).group(1))
    shared = _vars(re.search(r':root, \[data-theme="dark"\] \{(.*?)\}', _read(WEB / 'tokens.css'), re.S).group(1))
    diff = {k: (bench.get(k), shared.get(v)) for k, v in TOKEN_PAIRS.items() if bench.get(k) != shared.get(v)}
    assert not diff, diff
    assert bench['rose-wash'] == f"color-mix(in oklab,{bench['rose']} 12.7%,{bench['ground-deep']})"


def test_bench_evidence_words_match_shared_labels():
    core = _read(WEB / 'core_ui_logic.js')
    labels = dict(re.findall(r'(\w+): "([^"]+)"', core.split('EVIDENCE_LABEL = Object.freeze({', 1)[1].split('});', 1)[0]))
    app_js, cam_js = _read(OMX / 'bench_record_app.js'), _read(OMX / 'bench_record_cam.js')
    assert f"info?.fresh===false?'{labels['delayed']}':(info?.quality?.condition||'{labels['fresh']}')" in app_js
    assert f"ok?'서버 정상':'{labels['disconnected']}'" in cam_js
