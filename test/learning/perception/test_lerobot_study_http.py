"""Uploaded-study HTTP routing preserves existing project write and body fences."""
from types import SimpleNamespace

from test_learning_collaboration import Accounts
from test_omx_center_http import PREFIX, request, running

ID='4b590f02-c958-459d-a64a-c8ea5d183c98'


def wire(center):
    center.studies=SimpleNamespace(
        snapshot=lambda:dict(configured=True,studies=[]),
        get=lambda uid:dict(id=uid),
        create=lambda body,actor=None:center.record('study',dict(body=body,actor=actor)),
        upload=lambda body:center.record('study-upload',body),
        inspect=lambda body:center.record('study-inspect',body),
        split=lambda body:center.record('study-split',body),
        start=lambda body:center.record('study-run',body))


def test_study_routes_keep_token_and_authenticated_creator(tmp_path):
    with running(tmp_path) as (base,center):
        wire(center)
        assert request(base,PREFIX+'/lerobot-studies')[1]['configured'] is True
        assert request(base,PREFIX+'/lerobot-study/'+ID)[1]['id']==ID
        _,state=request(base,'/api/learning/tasks')
        for suffix,method in [('study','study'),('upload','study-upload'),('inspect','study-inspect'),
                              ('split','study-split'),('run','study-run')]:
            assert request(base,PREFIX+'/lerobot-'+suffix,{})[0]==403
            code,answer=request(base,PREFIX+'/lerobot-'+suffix,{},token=state['token'])
            assert code==200 and answer['method']==method
        assert center.calls[0][1]['actor'] is None


def test_study_creation_and_learning_require_manage_not_view_or_edit(tmp_path):
    with running(tmp_path,accounts=Accounts()) as (base,center):
        wire(center)
        _,state=request(base,'/api/learning/tasks',session='reader')
        assert request(base,PREFIX+'/lerobot-studies',session='reader')[0]==200
        for session in ('reader','editor'):
            for suffix in ('study','upload','inspect','split','run'):
                assert request(base,PREFIX+'/lerobot-'+suffix,{},token=state['token'],session=session)[0]==403
        assert not center.calls
        assert request(base,PREFIX+'/lerobot-study',{},token=state['token'],session='reviewer')[0]==200
        assert center.calls[0][1]['actor']['user_id']=='reviewer'


def test_unconfigured_center_disables_studies_without_hiding_static_page(tmp_path):
    with running(tmp_path,enabled=False) as (base,_):
        code,state=request(base,PREFIX+'/lerobot-studies')
        assert code==200 and state['configured'] is False and state['studies']==[]
        _,session=request(base,'/api/learning/tasks')
        assert request(base,PREFIX+'/lerobot-study',{},token=session['token'])[0]==400


def test_only_study_manifest_gets_the_larger_bounded_json_budget(tmp_path):
    with running(tmp_path) as (base,center):
        wire(center)
        _,state=request(base,'/api/learning/tasks')
        body=dict(request_id=ID,name='Many sharded files',files=[
            dict(name=f'data/chunk-{i//1000:03d}/file-{i%1000:03d}.parquet',size=1,sha256='a'*64)
            for i in range(9999)])
        body['files'].append(dict(name='meta/info.json',size=1,sha256='b'*64))
        assert request(base,PREFIX+'/lerobot-study',body)[0] == 403
        code,answer=request(base,PREFIX+'/lerobot-study',body,token=state['token'])
        assert code==200 and len(answer['request']['body']['files'])==10000
