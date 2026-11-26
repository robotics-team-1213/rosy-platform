"""Arm cell updater (cell_a_autoupdate.py): cell-only reuse check, oldest-installable pick, API economy."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site import cell_a_autoupdate as cell

SITE = Path(__file__).resolve().parents[1] / "deploy" / "site"
A, B = "a" * 40, "b" * 40


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(cell, "RELEASES_CACHE", tmp_path / "releases-cache.json")
    monkeypatch.setattr(cell, "FORWARD_CACHE", tmp_path / "forward-cache.json")
    return tmp_path


def _manifest(reused):
    return {"images": {s: {"reference": f"rosy-site-{s}:{A}"} for s in ("fleet", "vision", "proxy", "account")},
            "reused_images": reused}


def _docker(present):
    def run(cmd, check=True):
        ref = cmd[-1]
        if ref in present:
            return SimpleNamespace(returncode=0, stdout=f"{present[ref]}|linux|amd64\n")
        return SimpleNamespace(returncode=1, stdout="")
    return run


def test_reuse_check_ignores_services_the_cell_does_not_run(monkeypatch):
    monkeypatch.setattr(cell, "run", _docker({f"rosy-site-vision:{A}": "sha256:v"}))
    assert cell.reused_present(_manifest({"account": ["sha256:x"], "vision": ["sha256:v"]}))
    assert not cell.reused_present(_manifest({"vision": ["sha256:other"]}))
    monkeypatch.setattr(cell, "run", _docker({}))
    assert not cell.reused_present(_manifest({"fleet": ["sha256:f"]}))


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_picks_newest_release_whose_reused_images_are_present(monkeypatch):
    rows = [("site-new", {"release.json": "new"}), ("site-mid", {"release.json": "mid"}),
            ("site-old", {"release.json": "old"})]
    monkeypatch.setattr(cell, "signed_releases", lambda: iter(rows))
    manifests = {"new": {"reused_images": {"vision": ["sha256:mid"]}}, "mid": {"reused_images": {}},
                 "old": {"reused_images": {}}}
    monkeypatch.setattr(cell.urllib.request, "urlopen",
                        lambda url, timeout=0: _Resp(json.dumps(manifests[url]).encode()))
    monkeypatch.setattr(cell, "reused_present", lambda m: not m["reused_images"])
    assert cell.latest_signed_release()[0] == "site-mid"
    monkeypatch.setattr(cell, "reused_present", lambda m: False)
    assert cell.latest_signed_release()[0] == "site-new"  # nothing installable: report the newest


def test_release_list_reuses_cache_on_304(monkeypatch):
    calls = []

    def urlopen(req, timeout=0):
        calls.append(req.get_header("If-none-match"))
        if len(calls) == 1:
            return _Resp(b'[{"tag_name": "site-aaaaaaaaaaaa"}]', {"ETag": 'W/"e1"'})
        raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)

    monkeypatch.setattr(cell.urllib.request, "urlopen", urlopen)
    first = cell.fetch_releases()
    assert cell.fetch_releases() == first == [{"tag_name": "site-aaaaaaaaaaaa"}]
    assert calls == [None, 'W/"e1"']


def test_release_list_error_without_cache_is_raised(monkeypatch):
    def urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "rate limit", {}, None)

    monkeypatch.setattr(cell.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        cell.fetch_releases()


def test_ancestry_comparison_is_asked_once_per_commit_pair(monkeypatch):
    calls = []

    def fetch_json(url):
        calls.append(url)
        return {"status": "ahead", "merge_base_commit": {"sha": A}}

    monkeypatch.setattr(cell, "fetch_json", fetch_json)
    assert cell.forward(A, B) and cell.forward(A, B)
    assert len(calls) == 1
    assert not cell.forward("main", B)
    assert len(calls) == 1


def test_failed_commit_is_skipped_before_the_comparison_call():
    source = (SITE / "cell_a_autoupdate.py").read_text(encoding="utf-8")
    assert source.index("skipped-failed") < source.index("not forward(current, commit)")


def test_units_pin_the_installed_path_gate_and_period():
    service = (SITE / "rosy-cell-autoupdate.service").read_text(encoding="utf-8")
    timer = (SITE / "rosy-cell-autoupdate.timer").read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/python3 -I /usr/local/lib/rosy-cell/cell_a_autoupdate.py" in service
    assert "ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'" in service
    assert "OnUnitActiveSec=15m" in timer and "WantedBy=timers.target" in timer
