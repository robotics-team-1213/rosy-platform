"""Opt-in real browser → saved review → pinned CPU learner → verified ZIP, synthetic only."""
import io
import hashlib
import json
import os
from pathlib import Path
import threading
import subprocess
import uuid
import zipfile

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server
from learning_workspace import Workspace

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_synthetic_task_completes_review_training_evaluation_and_download(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root/'learning/training/omx'))
    from experiment_center import Center
    from native_cycle import native
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner required; no installation in this test'
    fixture_script = '''
import pathlib, sys
root, tmp = map(pathlib.Path,sys.argv[1:])
sys.path[:0]=[str(root/'learning/curation/omx/test'),str(root/'learning/curation/omx'),str(root/'learning/training/omx')]
import teacher_fixture as fixture, collection_intake
collections=[fixture.seal_teacher(tmp/'collections','synthetic-session-'+str(i),fixture.teacher_dataset(tmp/'recordings'/str(i))) for i in range(2)]
collection_intake.prepare_native(collections,tmp/'prepared','local/synthetic-browser-pipeline',**fixture.OPERATOR)
'''
    env = {key:os.environ[key] for key in ('HOME','PATH','USER','LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='2')
    fixture_run = subprocess.run([str(python),'-I','-B','-c',fixture_script,str(root),str(tmp_path)],
        capture_output=True,text=True,env=env,timeout=120)
    assert fixture_run.returncode == 0, fixture_run.stdout[-1000:]+fixture_run.stderr[-3000:]
    prepared = tmp_path/'prepared'
    original = (prepared/'decisions.json').read_bytes()
    store = ReviewStore(tmp_path/'review', empty_training=True)
    host = os.getenv('ROSY_TEST_COMPUTE_HOST','model')
    center = Center(dict(schema='rosy.omx.center-config/1', root=str(tmp_path/'center'), host_id=host,
        python=dict(act=str(python), hilserl=str(python))))
    server = make_server(store, free_port(), omx_center=center)
    row = Workspace(store.db).register(dict(kind='omx', name='SYNTHETIC BROWSER TEST ONLY', path=str(prepared)))
    height, width, _ = json.loads((prepared/'meta/info.json').read_bytes())['features']['observation.images.top']['shape']
    actor = {'user_id':'synthetic-fixture'}
    profile = center.profiles.save(dict(request_id=str(uuid.uuid4()), profile=dict(
        schema='rosy.omx.learning-profile/1', name='SYNTHETIC SETUP', mode='independent', task='Synthetic transfer',
        arms=[dict(id='follower_1', joint_names=native.JOINTS[:], units='normalized_-100_100')],
        cameras=[dict(id='top', input_key='observation.images.top', arm_id=None, role='top',
            source_identity='synthetic-top', placement='synthetic-overhead', shape=[3,height,width],
            purposes=['policy','record'])])), actor)
    robot = center.tasks.robot(dict(request_id=str(uuid.uuid4()), name='SYNTHETIC ROBOT', kind='omx',
        model_revision='synthetic-r1', device_id='synthetic-device'), actor)
    task = center.tasks.task(dict(request_id=str(uuid.uuid4()), name='SYNTHETIC BROWSER TASK',
        objective='Synthetic transfer', success='Synthetic completion', failure='Synthetic failure',
        reset='Synthetic reset', mode='independent', adapter='omx', profile_id=profile['id'],
        participants=[dict(robot_id=robot['id'], component_id='follower_1', role='transfer')]), actor, profile)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base+'/learning/tasks?task='+task['id'], wait_until='networkidle')
                page.get_by_role('tab', name='녹화', exact=True).click()
                page.locator('#workflow-native-source').select_option(row['id'])
                page.locator('#workflow-attach').click()
                expect(page.locator('#workflow-inputs')).to_contain_text('SYNTHETIC BROWSER TEST ONLY')
                page.get_by_role('tab', name='검수', exact=True).click()
                page.locator('#workflow-review-link').click()
                page.locator('#review-open').click()
                expect(page.locator('#review-decisions [data-episode]')).to_have_count(4)
                expect(page.locator('#review-image')).to_be_visible(timeout=30000)
                page.wait_for_function('() => document.getElementById("review-image").naturalWidth > 0', timeout=30000)
                for index, split in ((0,'train'),(3,'eval')):
                    page.locator(f'[data-episode="{index}"] [data-field="outcome"]').select_option('success')
                    page.locator(f'[data-episode="{index}"] [data-field="split"]').select_option(split)
                    page.locator(f'[data-episode="{index}"] [data-field="reason"]').fill('SYNTHETIC TEST LABEL ONLY')
                page.locator('#reviewer').fill('SYNTHETIC TEST ONLY')
                page.locator('#review-confirmed').check()
                page.locator('#review-save').click()
                expect(page.locator('#review-status')).to_contain_text('검수 스냅샷 저장됨')
                page.locator('#workflow-return').click()
                page.get_by_role('tab', name='학습', exact=True).click()
                page.locator('#workflow-review-selection').select_option('episodes')
                page.get_by_text('학습 설정·다른 학습 방법', exact=True).click()
                page.locator('#workflow-steps').fill('100')
                page.locator('#workflow-batch').fill('1')
                page.locator('#workflow-train-start').click()
                expect(page.get_by_role('tab', name='결과', exact=True)).to_have_attribute('aria-selected','true')
                expect(page.locator('#workflow-runs')).to_contain_text('학습 완료', timeout=240000)
                expect(page.locator('[data-evidence="offline_evaluation_complete"]')).to_have_text('완료 근거 있음')
                expect(page.locator('[data-evidence="physical_evaluation_complete"]')).to_have_text('미확인')
                with page.expect_download() as downloaded:
                    page.get_by_role('link', name='모델·입력·평가 내려받기').click()
                evidence = Path(os.getenv('ROSY_LEARNING_PIPELINE_EVIDENCE',str(tmp_path)))
                evidence.mkdir(parents=True,exist_ok=True)
                artifact = evidence/'download.zip'
                downloaded.value.save_as(artifact)
                with zipfile.ZipFile(io.BytesIO(artifact.read_bytes())) as archive:
                    result = json.loads(archive.read('result.json'))
                    request = json.loads(archive.read('source-request.json'))
                    assert result['learning_task'] == request['learning_task']
                    assert result['learning_task']['task_id'] == task['id']
                    assert result['learning_task']['compute_host'] == host
                    assert request['steps'] == 100
                    assert result['evaluation']['model_reloaded_in_new_process'] is True
                    assert result['evaluation']['samples'] == 3
                    assert result['physical_learning_verified'] is False
                    for name,digest in result['artifact_files'].items():
                        assert hashlib.sha256(archive.read('model/'+name)).hexdigest() == digest
                assert (prepared/'decisions.json').read_bytes() == original
                assert not errors
                proof = dict(source='synthetic_browser_pipeline', task_id=task['id'], steps=100,
                    learning_task=result['learning_task'], evaluation=result['evaluation'],
                    artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), physical_learning_verified=False)
                (evidence/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
                page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0,0); }')
                page.screenshot(path=str(evidence/'result-desktop.png'),full_page=True)
                print(json.dumps(proof))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
