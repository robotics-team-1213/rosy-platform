"""Both recording-only and learner workspaces keep explicit static and workflow routes."""
import urllib.error
import urllib.request

import pytest

from test_omx_center_http import running


@pytest.mark.parametrize('enabled', [False, True])
def test_review_static_routes_and_task_editor_survive_center_composition(tmp_path, enabled):
    with running(tmp_path, enabled=enabled) as (base, _):
        for path, marker in [('/learning/tasks', b'/workflow.js'),
                             ('/learning/tasks/manage', b'/tasks.js'),
                             ('/classes', b'/classes.js'), ('/common/tokens.css', b'--')]:
            with urllib.request.urlopen(base+path) as response:
                assert response.status == 200 and marker in response.read()
                assert response.headers['X-Content-Type-Options'] == 'nosniff'
                assert response.headers['Content-Security-Policy'].startswith("default-src 'self'")
        for path, headers, status in [('/common/review_app.py', {}, 404),
                                      ('/classes', {'Host': 'untrusted.example'}, 403)]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base+path, headers=headers))
            assert error.value.code == status
