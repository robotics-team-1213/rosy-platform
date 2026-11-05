"""Explicit operator acceptance: actual folder upload, ACT, fresh evaluation and ZIP.

Run this file explicitly with ROSY_RUN_UPLOADED_STUDY=1 and the task workspace paths.
It requires an operator-owned service and data, outside the hermetic browser tier.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest
from browser_harness import browser_tests_enabled

pytestmark=pytest.mark.skipif(not browser_tests_enabled() or os.getenv('ROSY_RUN_UPLOADED_STUDY')!='1',
    reason='explicit task-owned uploaded-study workspace required')


def test_real_uploaded_study_completes_the_learning_pipeline():
    from playwright.sync_api import sync_playwright,expect
    source=Path(os.environ['ROSY_UPLOADED_STUDY_SOURCE'])
    evidence=Path(os.environ['ROSY_UPLOADED_STUDY_EVIDENCE'])
    evidence.mkdir(parents=True,exist_ok=True)
    base='http://127.0.0.1:38774'
    api='/api/learning/omx/center'
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport=dict(width=1440,height=1000),accept_downloads=True)
            page.goto(base+'/learning/imitate',wait_until='networkidle')
            expect(page.locator('#study-summary')).to_contain_text('새 작업',timeout=60000)
            listing=page.evaluate('async path=>(await fetch(path)).json()',api+'/lerobot-studies')
            studies=[s for s in listing['studies'] if s['name']=='Uploaded SO100 acceptance']
            assert len(studies)<=1
            if studies:
                page.locator('#study-select').select_option(studies[0]['id'])
                expect(page.locator('#study-summary')).to_contain_text('Uploaded SO100 acceptance')
            else:
                page.locator('#study-name').fill('Uploaded SO100 acceptance')
                page.locator('#source-folder').set_input_files(str(source))
                expect(page.locator('#upload-start')).to_be_enabled(timeout=180000)
                page.locator('#upload-start').click()
                expect(page.locator('#upload-status')).to_contain_text('bytes',timeout=180000)
                expect(page.locator('#tab-inspect')).to_have_attribute('aria-selected','true',timeout=600000)
            uid=page.evaluate("new URL(location.href).searchParams.get('study')")
            def snapshot():
                return page.evaluate('async path=>(await fetch(path)).json()',api+'/lerobot-study/'+uid)
            study=snapshot()
            if study['status']=='uploading':
                page.locator('#tab-upload').click()
                page.locator('#source-folder').set_input_files(str(source))
                expect(page.locator('#upload-start')).to_be_enabled(timeout=180000)
                page.locator('#upload-start').click()
                expect(page.locator('#tab-inspect')).to_have_attribute('aria-selected','true',timeout=600000)
            page.locator('#tab-inspect').click()
            if not study['inspection']:
                expect(page.locator('#inspect-start')).to_be_enabled(timeout=60000)
                page.locator('#inspect-start').click()
                expect(page.locator('#split-save')).to_be_enabled(timeout=600000)
            study=snapshot()
            assert study['inspection']['state']['shape']==[6]
            assert study['inspection']['total_episodes']==10
            if not study['split']:
                for index in range(10):
                    page.locator(f'[data-episode="{index}"]').select_option('train' if index<8 else 'validation' if index==8 else 'eval')
                page.locator('#split-save').click()
                expect(page.locator('#split-state')).to_contain_text('분할 저장됨',timeout=60000)
            study=snapshot()
            assert {k:study['split'][k] for k in ('train','validation','eval')}==dict(train=list(range(8)),validation=[8],eval=[9])
            runs=[r for r in study['runs'] if r['execution_mode']=='lerobot_train']
            if not runs:
                page.locator('#tab-learn').click()
                page.locator('#train-steps').fill('1000')
                page.locator('#train-batch').fill('4')
                page.locator('#train-seed').fill('7')
                expect(page.locator('#train-start')).to_be_enabled()
                page.locator('#train-start').click()
                expect(page.locator('#study-results')).to_contain_text('ACT',timeout=60000)
            page.locator('#tab-results').click()
            expect(page.locator('#study-results [data-artifact]')).to_be_visible(timeout=2400000)
            study=snapshot()
            runs=[r for r in study['runs'] if r['execution_mode']=='lerobot_train']
            assert len(runs)==1
            run=runs[0]
            assert run['status']=='succeeded' and run['steps']==1000 and run['batch_size']==4
            assert run['compute_host']=='ai' and run['physical_learning_verified'] is False
            assert run['result']['evaluation']['model_reloaded_in_new_process'] is True
            with page.expect_download(timeout=180000) as download:
                page.locator('#study-results [data-artifact]').click()
            zipped=Path(download.value.path())
            with zipfile.ZipFile(zipped) as archive:
                manifest=json.loads(archive.read('archive-manifest.json'))
                for name,digest in manifest['files'].items():
                    assert hashlib.sha256(archive.read(name)).hexdigest()==digest
            receipt=dict(study_id=uid,run_id=run['id'],status=run['status'],steps=run['steps'],
                source_revision=study['source_revision'],split=study['split'],result=run['result'],
                zip_sha256=hashlib.sha256(zipped.read_bytes()).hexdigest(),browser_download_verified=True)
            (evidence/'accepted-uploaded-study.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
            page.evaluate('document.activeElement?.blur(); window.scrollTo(0,0)')
            page.screenshot(path=str(evidence/'completed-dark-1440.png'),full_page=True)
            page.set_viewport_size(dict(width=360,height=900))
            page.evaluate("document.documentElement.dataset.theme='light'")
            page.evaluate('document.activeElement?.blur(); window.scrollTo(0,0)')
            page.screenshot(path=str(evidence/'completed-light-360.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print(json.dumps(dict(study_id=uid,run_id=run['id'],steps=1000,download_verified=True)))
        finally:
            browser.close()
