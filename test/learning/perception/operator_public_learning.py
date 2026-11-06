"""Explicit opt-in operator smoke of the task-owned public study preview, no API mocking.

Run this file explicitly with ROSY_RUN_PUBLIC_STUDY=1 against the operator-owned service.
It intentionally remains outside hermetic browser discovery.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest
from browser_harness import browser_tests_enabled

pytestmark=pytest.mark.skipif(not browser_tests_enabled() or os.getenv('ROSY_RUN_PUBLIC_STUDY')!='1',
    reason='explicit task-owned public study preview required')


def test_start_or_resume_the_real_public_study():
    from playwright.sync_api import sync_playwright,expect
    base='http://127.0.0.1:38773'
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            page.goto(base+'/learning/public',wait_until='networkidle')
            expect(page.locator('#public-source-facts')).to_contain_text('lerobot/svla_so100_pickplace',timeout=60000)
            snapshot=page.evaluate("async()=> (await fetch('/api/learning/omx/center')).json()")
            runs=[run for run in snapshot['runs'] if run.get('execution_mode')=='public_train']
            if not runs:
                page.locator('#public-confirm').check()
                page.locator('#public-start').click()
                expect(page.locator('#public-runs')).to_contain_text('실행 중',timeout=30000)
                snapshot=page.evaluate("async()=> (await fetch('/api/learning/omx/center')).json()")
                runs=[run for run in snapshot['runs'] if run.get('execution_mode')=='public_train']
            assert len(runs)==1
            run=runs[0]
            assert run['status'] in ('launching','running','succeeded'),run.get('error')
            assert run['steps']==1000 and run['batch_size']==4
            assert run['source']['repo_id']=='lerobot/svla_so100_pickplace'
            assert run['physical_learning_verified'] is False
            artifact_verified=False
            if run['status']=='succeeded':
                expect(page.locator('#public-runs')).to_contain_text('학습 완료')
                with page.expect_download() as download:
                    page.locator('#public-runs a[href*="/artifact/"]').click()
                with zipfile.ZipFile(download.value.path()) as archive:
                    result=json.loads(archive.read('result.json'))
                    assert result['steps']==1000
                    assert result['evaluation']['model_reloaded_in_new_process'] is True
                    for name,digest in result['artifact_files'].items():
                        assert hashlib.sha256(archive.read('model/'+name)).hexdigest()==digest
                artifact_verified=True
            if folder:=os.getenv('ROSY_PUBLIC_STUDY_EVIDENCE'):
                target=Path(folder)
                target.mkdir(parents=True,exist_ok=True)
                (target/'ui-accepted-run.json').write_text(json.dumps(dict(id=run['id'],status=run['status'],
                    source=run['source'],steps=run['steps'],source_commit='663ccdfc89'),indent=2),encoding='utf-8')
                page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0,0); }')
                page.screenshot(path=str(target/'accepted-study.png'),full_page=True)
            print(json.dumps(dict(id=run['id'],status=run['status'],steps=run['steps'],
                source=run['source']['repo_id'],artifact_verified=artifact_verified)))
        finally:
            browser.close()
