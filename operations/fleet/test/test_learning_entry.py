"""Fleet documents only launch configured Learning origins; targets own authentication."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.static_routes import WEB_ROOT, install_static_routes


def client(monkeypatch, tmp_path, config=None):
    monkeypatch.delenv('ROSY_LEARNING_APPS_CONFIG', raising=False)
    if config is not None:
        path = tmp_path / 'learning.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        monkeypatch.setenv('ROSY_LEARNING_APPS_CONFIG', str(path))
    app = FastAPI()
    app.state.web_common = None
    install_static_routes(app)
    return TestClient(app)


@pytest.mark.parametrize('config', [None, {}])
def test_unconfigured_documents_explain_preparation(monkeypatch, tmp_path, config):
    http = client(monkeypatch, tmp_path, config)
    for path in ['/console/learning', '/console/learning/model', '/console/learning/ai']:
        response = http.get(path, follow_redirects=False)
        assert response.status_code == 503
        assert 'text/html' in response.headers['content-type']
        assert 'Rosy Account' in response.text
        assert '/console?view=work' in response.text
        assert 'Location' not in response.headers
        assert "script-src 'self'" in response.headers['content-security-policy']
        assert 'no-store' in response.headers['cache-control']


def test_constant_redirects_do_not_forward_credentials_or_queries(monkeypatch, tmp_path):
    http = client(monkeypatch, tmp_path, {'model': 'https://model.example', 'ai': 'https://ai.example:8443'})
    assert http.get('/console/learning').status_code == 200
    for host, origin in [('model', 'https://model.example'), ('ai', 'https://ai.example:8443')]:
        response = http.get('/console/learning/' + host, follow_redirects=False,
                            headers={'Authorization': 'Bearer fleet-secret', 'Cookie': 'session=fleet-cookie'})
        assert response.status_code == 303
        assert response.headers['location'] == origin + '/learning'
        assert 'set-cookie' not in response.headers
        assert 'fleet-secret' not in response.text and 'fleet-cookie' not in response.text
    for query in ['url=https://evil.example', 'target=ai', 'token=fleet-secret', 'next=//evil.example']:
        response = http.get('/console/learning/model?' + query, follow_redirects=False)
        assert response.status_code == 400
        assert 'location' not in response.headers
    assert http.get('/console/learning/other', follow_redirects=False).status_code == 404


def test_partial_config_and_startup_snapshot(monkeypatch, tmp_path):
    http = client(monkeypatch, tmp_path, {'model': 'https://model.example'})
    assert http.get('/console/learning').status_code == 200
    assert http.get('/console/learning/ai').status_code == 503
    (tmp_path / 'learning.json').write_text('{"model":"https://changed.example"}')
    assert http.get('/console/learning/model', follow_redirects=False).headers['location'] == (
        'https://model.example/learning')


@pytest.mark.parametrize('config', [[], None, {'other': 'https://model.example'}, {'model': None},
    {'model': ''}, {'model': {}}, {'model': 'http://model.example'},
    {'model': 'https://user:password@model.example'}, {'model': 'https://model.example/'},
    {'model': 'https://model.example/path'}, {'model': 'https://model.example?token=x'},
    {'model': 'https://model.example#x'}, {'model': 'https://localhost'},
    {'model': 'https://localhost.localdomain'}, {'model': 'https://127.0.0.2'},
    {'model': 'https://[::1]'}, {'model': 'https://0.0.0.0'}, {'model': 'https://*.example'},
    {'model': 'https://model.example:bad'}, {'model': 'https://model.example\\@evil.example'},
    {'model': 'https://model.example\n'}, {'model': 'https://model.example?'},
    {'model': 'https://model.example#'}, {'model': 'https://app.localhost'},
    {'model': 'https://localdomain'}, {'model': 'https://[::]'},
    {'model': 'https://[::ffff:127.0.0.1]'}, {'model': 'https://127.1'},
    {'model': 'https://0177.0.0.1'}, {'model': 'https://2130706433'},
    {'model': 'https://0x7f000001'}])
def test_invalid_config_fails_before_serving(monkeypatch, tmp_path, config):
    # Explicit null differs from the absent environment variable.
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setenv('ROSY_LEARNING_APPS_CONFIG', str(path))
    app = FastAPI()
    app.state.web_common = None
    with pytest.raises(ValueError):
        install_static_routes(app)


@pytest.mark.parametrize('content', ['{broken', '{"model":"https://one.example","model":"https://two.example"}'])
def test_missing_or_malformed_config_fails_startup(monkeypatch, tmp_path, content):
    path = tmp_path / 'missing.json'
    monkeypatch.setenv('ROSY_LEARNING_APPS_CONFIG', str(path))
    app = FastAPI()
    app.state.web_common = None
    with pytest.raises(ValueError):
        install_static_routes(app)
    path.write_text(content)
    with pytest.raises(ValueError):
        install_static_routes(app)


def test_launch_uses_house_components_without_inline_code_and_work_navigation():
    html = (WEB_ROOT / 'learning.html').read_text(encoding='utf-8')
    assert '/common/tokens.css' in html and '/common/components.css' in html
    assert '<ui-shell' in html and '<ui-section' in html
    assert 'style=' not in html and '<style' not in html
    assert '<script>' not in html
    assert '/console/learning/model' in html and '/console/learning/ai' in html
    index = (WEB_ROOT / 'index.html').read_text(encoding='utf-8')
    work = index.split('data-area="work"', 1)[1].split('</nav>', 1)[0]
    assert 'href="/console/learning"' in work
    root = Path(__file__).resolve().parents[3]
    compose = (root / 'deploy/site/compose.yaml').read_text(encoding='utf-8')
    assert 'ROSY_LEARNING_APPS_CONFIG:' in compose
    assert '/etc/rosy/fleet-learning:/run/rosy-fleet-learning:ro' in compose
    assert json.loads((root / 'deploy/site/learning-apps.example.json').read_text()) == {}
