"""Opt-in capture of actual Fleet HTTP responses from passing backend contracts."""
import base64
from collections import defaultdict
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
OBSERVED = defaultdict(lambda: defaultdict(set))
PASSED = set()


@lru_cache(maxsize=1)
def routes():
    matrix = json.loads(Path(__file__).with_name('feature_matrix.json').read_text(encoding='utf-8'))
    found = []
    for feature in matrix['features']:
        for item in feature['requests']:
            parts = re.split(r'(\{[^}]+\})', item['path'])
            pattern = ''.join('[^/]+' if part.startswith('{') else re.escape(part) for part in parts)
            found.append((item['method'], re.compile(pattern + '$'), item['id']))
    return found


def matching(method, path):
    return [identifier for verb, pattern, identifier in routes() if verb == method and pattern.fullmatch(path)]


@pytest.fixture(autouse=True)
def fleet_contract_probe(monkeypatch, request):
    import httpx
    from starlette.testclient import TestClient
    original = TestClient.request
    original_async = httpx.AsyncClient.send

    def record(method, response):
        for identifier in matching(method.upper(), urlsplit(str(response.request.url)).path):
            OBSERVED[identifier][response.status_code].add(request.node.nodeid)

    def observe(client, method, url, *args, **kwargs):
        response = original(client, method, url, *args, **kwargs)
        record(method, response)
        return response

    async def observe_async(client, request, *args, **kwargs):
        response = await original_async(client, request, *args, **kwargs)
        record(request.method, response)
        return response

    monkeypatch.setattr(TestClient, 'request', observe)
    monkeypatch.setattr(httpx.AsyncClient, 'send', observe_async)


def pytest_runtest_logreport(report):
    if report.when == 'call' and report.passed:
        PASSED.add(report.nodeid)


def pytest_terminal_summary(terminalreporter):
    evidence = {identifier: {str(status): sorted(nodes & PASSED)[0]
                            for status, nodes in statuses.items() if nodes & PASSED}
                for identifier, statuses in sorted(OBSERVED.items())}
    result = {'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'pytest_root': terminalreporter.config.rootpath.resolve().relative_to(ROOT).as_posix(),
              'requests': evidence}
    terminalreporter.write_line('FLEET_APP_HTTP_EVIDENCE=' + base64.b64encode(json.dumps(result).encode()).decode())
