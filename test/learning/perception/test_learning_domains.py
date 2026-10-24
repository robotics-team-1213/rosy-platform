"""Home rows per domain (D-857 §3): only data the workspace holds; unknown stays not_available with a reason."""
import json
import sqlite3
import threading
import urllib.request

from learning_domains import STAGES, domains, stored
from review_app import make_server
from test_learning_pipeline import progress
from test_review_app import open_store

EMPTY = dict(counts={'approved': 0, 'pending': 0, 'excluded': 0}, preparation=None, items=[], omx_reviewed=[],
             sim_runs=None, vlm_counts=None)


def by_id(rows):
    return {row['id']: row for row in rows}


def states(row):
    return [stage['state'] for stage in row['stages']]


def test_every_domain_has_the_six_stages_and_unknowns_say_why():
    rows = domains(pipeline=progress(counts=EMPTY['counts']), **EMPTY)
    assert [row['id'] for row in rows] == ['lane', 'object', 'omx', 'sim', 'vlm', 'decision']
    for row in rows:
        assert [stage['stage'] for stage in row['stages']] == [key for key, _ in STAGES]
        assert 'deploy' not in json.dumps(row)
        for stage in row['stages']:
            assert stage['state'] in ('done', 'active', 'blocked', 'waiting', 'not_available')
            assert stage['evidence']  # never blank, also when unknown
            if stage['next']:
                assert set(stage['next']) == {'label', 'href'} and stage['next']['href'].startswith('/')
    decision = by_id(rows)['decision']
    assert set(states(decision)) == {'not_available'} and decision['blocked'] == 'Learning에 연결 전'
    assert decision['next'] is None
    sim = by_id(rows)['sim']['stages']
    assert [sim[i]['state'] for i in (0, 4)] == ['not_available'] * 2
    assert sim[4]['evidence'] == 'SIM 실행 연결이 설정되지 않았습니다.'
    assert by_id(rows)['vlm']['stages'][0]['evidence'] == 'VLM 질문 자료가 없습니다.'
    assert by_id(rows)['object']['next'] == {'label': '자료 등록', 'href': '/catalog'}


def test_lane_maps_the_owner_pipeline_and_marks_one_current_stage():
    lane = by_id(domains(pipeline=progress(), **EMPTY))['lane']
    assert states(lane)[:5] == ['done'] * 5  # the ready owner cycle in test_learning_pipeline
    assert lane['next']['href'] == '/learning#pipeline-evidence'
    held = progress(pixel_counts={'approved': 0, 'pending': 1, 'excluded': 0})
    lane = by_id(domains(pipeline=held, **EMPTY))['lane']
    assert states(lane)[:3] == ['done', 'active', 'waiting']
    assert lane['next'] == {'label': '픽셀 검수 시작', 'href': '/pixels?filter=pending'}
    assert [stage['next'] is not None for stage in lane['stages']].count(True) == 1


def test_object_omx_sim_and_vlm_count_only_what_exists():
    rows = by_id(domains(pipeline=progress(), counts={'approved': 2, 'pending': 1, 'excluded': 0},
                         preparation={'object_frames': 2, 'current_decisions_match': False},
                         items=[{'id': 'a', 'kind': 'omx'}, {'id': 'b', 'kind': 'omx'}, {'id': 'c', 'kind': 'perception'}],
                         omx_reviewed=['a', 'zzz'], sim_runs={'runs': [
                             {'status': 'FAILED', 'updated_at': '2026-10-24T01:00:00'},
                             {'status': 'SUCCEEDED', 'updated_at': '2026-10-23T01:00:00'}]},
                         vlm_counts={'total': 4, 'labelled': 1, 'excluded': 1, 'provisional': 1}, tasks=2))
    assert states(rows['object'])[:4] == ['done', 'active', 'blocked', 'not_available']
    assert rows['object']['stages'][1]['evidence'] == '객체 승인 2 · 대기 1 · 제외 0'
    assert rows['omx']['stages'][1]['evidence'] == '구간 검수 1/2' and states(rows['omx'])[2] == 'not_available'
    assert rows['omx']['stages'][3]['evidence'] == 'OMX 학습 과제 2개'  # the #151 task page is where OMX training starts
    assert rows['omx']['stages'][3]['next'] == {'label': '학습 과제', 'href': '/learning/tasks'}
    assert rows['sim']['stages'][0]['state'] == 'blocked' and '실험 2회 · 최근 FAILED' in rows['sim']['stages'][0]['evidence']
    assert rows['vlm']['stages'][1]['evidence'] == '확정 1 · 미확정 2 (임시 정답 1)'
    assert rows['vlm']['stages'][4]['state'] == 'done'
    failed = by_id(domains(pipeline=progress(), **dict(EMPTY, sim_runs={'error': 'x'})))['sim']
    assert failed['blocked'] == 'SIM 실행 연결을 확인하세요.'


def test_sim_row_shows_the_latest_run_stage_evidence_and_opens_that_run():
    run_id = 'e' * 32
    sim = by_id(domains(pipeline=progress(), **dict(EMPTY, sim_runs={'runs': [
        {'run_id': 'f' * 32, 'status': 'FAILED', 'updated_at': '2026-10-23T01:00:00'},
        {'run_id': run_id, 'status': 'SUCCEEDED', 'updated_at': '2026-10-24T01:00:00',
         'result': {'status': 'passed', 'stage': 'model_import', 'task_success': None}}]})))['sim']
    assert sim['next'] == {'label': 'SIM 결과 확인', 'href': '/learning/sim?run=' + run_id}
    evaluate = sim['stages'][4]
    assert evaluate['evidence'] == '최근 단계 model_import · 과제 성공 기록 없음 · 판정 passed (근거일 뿐 승인 아님)'
    assert evaluate['next']['href'] == '/learning/evaluate?domain=sim'
    assert sim['stages'][5]['state'] == 'not_available'  # a SIM verdict is evidence, never a promotion record
    failed = by_id(domains(pipeline=progress(), **dict(EMPTY, sim_runs={'runs': [
        {'run_id': run_id, 'status': 'SUCCEEDED', 'result': {'status': 'failed', 'task_success': False}}]})))['sim']
    assert failed['stages'][4]['state'] == 'blocked'
    waiting = by_id(domains(pipeline=progress(), **dict(EMPTY, sim_runs={'runs': [{'status': 'RUNNING'}]})))['sim']
    assert waiting['stages'][4]['state'] == 'waiting' and waiting['next']['href'] == '/learning/sim'


def test_stored_reads_without_creating_tables(tmp_path):
    db = sqlite3.connect(tmp_path / 'x.sqlite3')
    assert stored(db) == ([], None, 0)
    assert db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def test_api_learning_adds_domains_and_keeps_its_keys(tmp_path):
    store = open_store(tmp_path)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/learning') as response:
            value = json.load(response)
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert {'workflows', 'items', 'token', 'pipeline', 'preparation', 'control', 'counts', 'object_drafts',
            'pixel_counts', 'domains'} <= set(value)
    rows = by_id(value['domains'])
    assert rows['object']['stages'][0]['evidence'] == '사진 2장'
    assert rows['vlm']['stages'][0]['state'] == 'not_available'
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'vlm_%'").fetchone()[0] == 0
