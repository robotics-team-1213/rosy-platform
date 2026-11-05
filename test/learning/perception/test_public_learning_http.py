"""Public study stays under the existing center's identity and write fences."""
from test_omx_center_http import PREFIX, request, running
from test_learning_collaboration import Accounts


def wire(center):
    center.public_source=lambda: {'available':True,'repo_id':'lerobot/svla_so100_pickplace','license':'apache-2.0'}
    center.start_public=lambda body: center.record('public',body)


def test_public_routes_and_styles_reuse_the_center_write_boundary(tmp_path):
    with running(tmp_path) as (base,center):
        wire(center)
        code,source=request(base,PREFIX+'/public-source')
        assert code == 200 and source['available'] is True
        _,state=request(base,'/api/learning/tasks')
        body={'request_id':'fixture','confirmed_source':True}
        assert request(base,PREFIX+'/public-run',body)[0] == 403
        code,answer=request(base,PREFIX+'/public-run',body,token=state['token'])
        assert code == 200 and answer['method'] == 'public'
        assert center.calls == [('public',body)]


def test_public_training_requires_project_manage_not_view_or_edit(tmp_path):
    with running(tmp_path,accounts=Accounts()) as (base,center):
        wire(center)
        _,state=request(base,'/api/learning/tasks',session='reader')
        assert request(base,PREFIX+'/public-source',session='reader')[0] == 200
        for session in ('reader','editor'):
            assert request(base,PREFIX+'/public-run',{},token=state['token'],session=session)[0] == 403
        assert not center.calls
        assert request(base,PREFIX+'/public-run',{},token=state['token'],session='reviewer')[0] == 200


def test_public_training_without_a_host_center_is_unavailable(tmp_path):
    with running(tmp_path,enabled=False) as (base,_):
        _,state=request(base,'/api/learning/tasks')
        assert request(base,PREFIX+'/public-source')[0] == 400
        assert request(base,PREFIX+'/public-run',{},token=state['token'])[0] == 400
