"""Chromium verification for /learning/canonical: spec, 2-PC watch, eval ladder, cell_live_check & job runner."""
import json
from pathlib import Path
import sys
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))

import experiment_center  # noqa: E402
from review_app import ReviewStore, make_server  # noqa: E402
from test_canonical_web import _canon_cfg  # noqa: E402
from test_learning_collaboration import Accounts  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="requires explicit Chromium run")


def _seed_watched(watch_dir: Path) -> None:
    (watch_dir / "real_aligned" / "real" / "arm_b").mkdir(parents=True)
    (watch_dir / "real_aligned" / "align.done").write_text("RC=0\n", encoding="utf-8")
    (watch_dir / "real_aligned" / "real" / "arm_b" / "gate-receipt.json").write_text(json.dumps({
        "arm": "arm_b", "source": {"kind": "real"}, "counts": {"pass": 100, "review": 0, "reject": 0},
        "dataset_reject": [], "goals_passing": 100,
    }), encoding="utf-8")
    (watch_dir / "collect" / "dart-5201" / "arm_b" / "meta").mkdir(parents=True)
    (watch_dir / "collect" / "dart-5201" / "arm_b" / "meta" / "info.json").write_text("{}", encoding="utf-8")
    (watch_dir / "eval_l1").mkdir(parents=True)
    (watch_dir / "eval_l1" / "step-5000.json").write_text(json.dumps({
        "verdict": "pass", "task": "ship-h1", "physics_candidate": "canonical-test",
        "profiles": {
            "nominal": {"episodes": 50, "teacher_successes": 48, "policy_successes": 48, "neighbour_disturbed": 0, "arm_link_contacts": 0},
            "delayed": {"episodes": 30, "teacher_successes": 29, "policy_successes": 29, "neighbour_disturbed": 0, "arm_link_contacts": 0},
        },
        "per_layer": {"L0": {"episodes": 16, "successes": 16}, "L1": {"episodes": 17, "successes": 17}},
    }), encoding="utf-8")
    (watch_dir / "arm_b_cell_live_check.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-live-check.v1", "arm_id": "arm_b", "policy_revision": "canon-rev-5000",
        "states": {
            "legacy_home_closed": {"goal_3": {"strict_ok": False, "margin_ok": False, "strict_oor": [{"name": "wrist_roll"}], "margin_oor": [], "wrist_roll_warning": "frame 0 wrist_roll=22.00 lies between trained branches"}},
            "canonical_start_open": {"goal_3": {"strict_ok": True, "margin_ok": True, "strict_oor": [], "margin_oor": [], "wrist_roll_warning": None}},
        },
    }), encoding="utf-8")


def _serve_canonical(tmp_path: Path, *, configured: bool = True, monkeypatch=None):
    center = None
    if configured:
        monkeypatch.setattr(experiment_center.os, "name", "posix")
        monkeypatch.setattr(
            experiment_center.subprocess, "run",
            lambda *a, **k: type("R", (), {"returncode": 0, "stdout": b"True\n"})(),
        )
        cfg = _canon_cfg(tmp_path)
        _seed_watched(tmp_path / "watch_mp")
        import canonical_pipeline as cp
        def _fake_popen(*a, **k):
            if k.get("stdout"):
                k["stdout"].write(b"[mock] align_real started\n")
                k["stdout"].flush()
            return type("P", (), {"pid": 51001, "poll": lambda s: None})()
        monkeypatch.setattr(cp.subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(cp, "process_stamp", lambda pid, req=None: {"pid": pid, "start": "1", "boot": "b"})
        monkeypatch.setattr(cp.os, "killpg", lambda pid, sig: None)
        center = experiment_center.Center({
            "schema": "rosy.omx.center-config/1", "host_id": "model",
            "root": str(tmp_path / "center"), "python": {"act": sys.executable, "hilserl": sys.executable},
            "canonical": cfg,
        })
    srv = make_server(ReviewStore(tmp_path / "state", empty_training=True), free_port(), accounts=Accounts(), omx_center=center)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, th


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("session", ["reader", "reviewer"])
def test_canonical_page_flows(tmp_path, monkeypatch, width, session):
    playwright = pytest.importorskip("playwright.sync_api")
    srv, th = _serve_canonical(tmp_path, configured=True, monkeypatch=monkeypatch)
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            browser.contexts[0].add_cookies([{"name": "rosy_learning_session", "value": session, "url": base}])
            expect = playwright.expect
            try:
                page.goto(base + "/learning/canonical", wait_until="domcontentloaded")
                expect(page.locator("#canon-spec-body tr")).to_have_count(12)
                expect(page.locator("#canon-evidence-badge")).to_contain_text("실물 제어·승인 아님")
                expect(page.locator("#canon-kpis")).to_contain_text("0.274 < 0.35 rad")
                for theme in ("light", "dark"):
                    page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

                page.locator("#canon-unit").select_option("sim_rad")
                expect(page.locator("#canon-spec-body")).to_contain_text("0.5907")
                page.locator("#canon-unit").select_option("raw_ticks")
                expect(page.locator("#canon-spec-body")).to_contain_text("2130")

                expect(page.locator("#canon-hosts")).to_contain_text("align.done: RC=0")
                expect(page.locator("#canon-hosts")).to_contain_text("pass 100/rev 0/rej 0")
                expect(page.locator("#canon-hosts")).to_contain_text("arm_b 1")

                page.locator("#canon-eval-body ui-button").first.click()
                expect(page.locator("#canon-eval-detail")).to_be_visible()
                expect(page.locator("#canon-eval-detail")).to_contain_text("canonical-test")

                expect(page.locator("#canon-live-body")).to_contain_text("legacy_home_closed")
                expect(page.locator("#canon-live-body")).to_contain_text("canonical_start_open")
                warn = page.locator("#canon-wrist-warn")
                expect(warn).to_be_visible()
                expect(warn).to_contain_text("wrist_roll_warning")
                assert warn.evaluate("node => !node.closest('details')")

                if session == "reader":
                    expect(page.locator("#canon-job-submit")).to_be_disabled()
                    expect(page.locator("#canon-job-cause")).to_be_visible()
                    expect(page.locator("#canon-job-cause")).to_contain_text("관리 권한")
                else:
                    expect(page.locator("#canon-job-submit")).to_be_enabled()
                    page.locator("#canon-align-flip").check()
                    page.locator("#canon-job-submit").click()
                    expect(page.locator("#canon-runs .canon-card")).to_have_count(1)
                    expect(page.locator("#canon-run-detail")).to_be_visible()
                    expect(page.locator("#canon-job-log")).to_contain_text("[mock] align_real started")
                    expect(page.locator("#canon-job-cancel")).to_be_enabled()
                    page.locator("#canon-job-cancel").click()
                    expect(page.locator("#canon-runs .canon-card")).to_contain_text("중지 요청")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert errors == []
            finally:
                browser.close()
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)


def test_unconfigured_canonical_page_shows_builtin_spec_and_blocks_start(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    srv, th = _serve_canonical(tmp_path, configured=False)
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            browser.contexts[0].add_cookies([{"name": "rosy_learning_session", "value": "reviewer", "url": base}])
            try:
                page.goto(base + "/learning/canonical", wait_until="domcontentloaded")
                playwright.expect(page.locator("#canon-kpis")).to_contain_text("0.274 < 0.35 rad")
                playwright.expect(page.locator("#canon-hosts-empty")).to_be_visible()
                playwright.expect(page.locator("#canon-job-submit")).to_be_disabled()
                playwright.expect(page.locator("#canon-job-cause")).to_contain_text("설정되지 않았습니다")
                assert errors == []
            finally:
                browser.close()
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)
