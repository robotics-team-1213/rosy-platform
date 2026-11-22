"""Chromium verification for /learning/canonical: 2-PC live monitor, telemetry meters, eval ladder, cell_live_check, spec & job runner."""
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
    (watch_dir / "arm_b" / "train" / "checkpoints" / "002500").mkdir(parents=True)
    (watch_dir / "arm_b.train.log").write_text(
        "Training:  17%|##| 1248/7500 [03:10<15:52,  6.56step/s]\r"
        "INFO step:1K loss:0.099 grdn:2.309 lr:9.7e-05\n",
        encoding="utf-8",
    )
    (watch_dir / "arm_b_ladder").mkdir(parents=True)
    (watch_dir / "arm_b_ladder" / "dev-002500.log").write_text(
        "EVAL 3101 arm_b ship-h1r1-l0 fail 0.0 False\nEVAL 3102 arm_b ship-h1r2-l0 pass 139.35 True\n",
        encoding="utf-8",
    )
    (watch_dir / "eval_l1").mkdir(parents=True)
    (watch_dir / "eval_l1" / "step-5000.json").write_text(json.dumps({
        "verdict": "pass", "task": "ship-h1", "physics_candidate": "canonical-test",
        "profiles": {
            "nominal": {"policy_episodes": 50, "teacher_episodes": 50, "teacher_successes": 48, "policy_successes": 48, "neighbour_disturbed": 0, "arm_link_contacts": 0},
            "delayed": {"policy_episodes": 30, "teacher_episodes": 30, "teacher_successes": 29, "policy_successes": 29, "neighbour_disturbed": 0, "arm_link_contacts": 0},
        },
        "per_layer": {"L0": {"episodes": 16, "successes": 16}, "L1": {"episodes": 17, "successes": 17}},
    }), encoding="utf-8")
    (watch_dir / "arm_b_cell_live_check.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-live-check.v1", "arm_id": "arm_b", "policy_revision": "canon-rev-5000",
        "checkpoints": {
            "002500": {
                "states": {
                    "legacy_home_closed": {"goal_3": {"strict_ok": False, "margin_ok": False, "strict_oor": [{"name": "wrist_roll"}], "margin_oor": [], "wrist_roll_warning": "frame 0 wrist_roll=22.00 lies between trained branches"}},
                    "canonical_start_open": {"goal_3": {"strict_ok": True, "margin_ok": True, "strict_oor": [], "margin_oor": [], "wrist_roll_warning": None}},
                },
            },
        },
    }), encoding="utf-8")
    from rosy.contracts.learning import omx_recording_todo as rt
    inv = rt.derive_inventory_from_manifest({
        "schema": rt.CURATED_MANIFEST_SCHEMA,
        "curated_version": "omx-real-v1",
        "hf_repo": "robotteam/rosy-omx-data",
        "hf_revision": "1234567890abcdef",
        "datasets": [
            {"dataset_id": "r-f01-s03", "arm": "arm_a", "direction": "load", "bay": "ship-h1", "slot_id": "ship-h1r0-l0",
             "split_role": "train", "episodes": {"raw_total": 5, "curated_total": 5}, "wrist_roll_branch": {"branch": "positive_canonical"},
             "data_gate": {"goal_scope": "h1", "admissible": True, "counts": {"pass": 5, "review": 0, "reject": 0}, "dataset_reject": []}},
            {"dataset_id": "l-f02-s01", "arm": "arm_b", "direction": "load", "bay": "ship-h1", "slot_id": "ship-h1r2-l1",
             "split_role": "train", "episodes": {"raw_total": 10, "curated_total": 10}, "wrist_roll_branch": {"branch": "negative_raw"},
             "data_gate": {"goal_scope": "h1", "admissible": True, "counts": {"pass": 10, "review": 0, "reject": 0}, "dataset_reject": []}},
        ],
    })
    (watch_dir / "recording-inventory.json").write_text(json.dumps(inv), encoding="utf-8")


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
        _real_popen = cp.subprocess.Popen

        def _fake_popen(*a, **k):
            cmd = a[0] if a else k.get("args") or ()
            if not any("canonical_workers.py" in str(arg) for arg in cmd):
                return _real_popen(*a, **k)
            if k.get("stdout") and hasattr(k["stdout"], "write"):
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
        monkeypatch.setattr(center.canonical.telemetry, "snapshot", lambda: {
            "gpu": {"available": True, "name": "RTX 5080 Laptop GPU", "util_pct": 97, "vram_used_mib": 3936, "vram_total_mib": 16303, "temp_c": 59, "power_w": 79.6},
            "cpu": {"cores": 20, "load_1m": 7.3, "load_5m": 6.9}, "memory": {"used_gib": 14.2, "total_gib": 31.1, "pct": 45.7},
            "disk": {"free_gib": 73.0, "total_gib": 419.0, "use_pct": 82.6, "state": "warn"}, "collected_at": 1795357600.0, "stale": False,
        })
        monkeypatch.setattr(center.canonical.peers, "snapshot", lambda: {
            "ai": {
                "peer_id": "ai", "label": "AI PC", "status": "ok", "fetched_at": 1795357600.0, "error": None,
                "summary": {
                    "host_id": "ai", "configured": True, "writable": False,
                    "host_telemetry": {
                        "gpu": {"available": True, "name": "RTX 5080 Laptop GPU", "util_pct": 98, "vram_used_mib": 4925, "vram_total_mib": 16303, "temp_c": 60, "power_w": 79.6},
                        "cpu": {"cores": 20, "load_1m": 5.3, "load_5m": 4.9}, "memory": {"used_gib": 12.1, "total_gib": 31.1, "pct": 38.9},
                        "disk": {"free_gib": 25.0, "total_gib": 460.0, "use_pct": 94.6, "state": "crit"}, "collected_at": 1795357600.0, "stale": False,
                    },
                    "watched": {"ai_canon": {
                        "id": "ai_canon", "label": "AI PC mix-1122-canon", "host_id": "ai", "available": True,
                        "align_done": "RC=0", "gate_receipts": [], "collect_seeds": {"arm_a": 48, "arm_b": 0},
                        "checkpoints": {"arm_a": {"train": ["005000"]}},
                        "training": [{"file": "arm_a.train.log", "arm": "arm_a", "status": "running", "active": True, "ended": False,
                                      "step": 6200, "total_steps": 75000, "pct": 8.3, "rate_step_s": 7.0, "eta_s": 9800,
                                      "loss": 0.081, "grdn": 1.95, "lr": 3e-5, "log_age_s": 2.0}],
                        "eval_progress": [], "eval_ladder": [], "cell_live_checks": [], "markers": {}, "progress": None,
                    }},
                },
            },
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
                expect(page.locator("#canon-hosts .canon-host-card")).to_have_count(2)
                expect(page.locator("#canon-hosts")).to_contain_text("1,248 / 7,500")
                expect(page.locator("#canon-hosts")).to_contain_text("6,200 / 75,000")
                expect(page.locator("#canon-hosts")).to_contain_text("align.done: RC=0")
                expect(page.locator("#canon-hosts")).to_contain_text("pass 100/rev 0/rej 0")
                expect(page.locator("#canon-hosts")).to_contain_text("arm_b 1")
                expect(page.locator("#canon-hosts")).to_contain_text("평가 002500: 2")
                expect(page.locator("#canon-hosts progress.canon-progress").first).to_be_visible()
                assert page.locator("#canon-hosts progress.canon-progress").first.bounding_box()["width"] > 50
                assert page.locator("#canon-hosts meter.canon-meter").first.bounding_box()["width"] > 40
                expect(page.locator('#canon-hosts meter.canon-meter[data-level="warn"]')).to_have_count(1)
                expect(page.locator('#canon-hosts meter.canon-meter[data-level="crit"]')).to_have_count(1)
                if width == 1280:
                    assert page.locator("#canon-hosts").bounding_box()["y"] < page.locator("#canon-spec-table").bounding_box()["y"]

                expect(page.locator("#canon-spec-body tr")).to_have_count(12)
                expect(page.locator("#canon-todo-cards .canon-todo-card").first).to_have_attribute("data-priority", "p1")
                expect(page.locator('#canon-todo-cards [data-slot-state="target-empty"]').first).to_be_visible()
                assert page.locator("#canon-todo-cards svg.canon-svg-topdown").first.bounding_box()["width"] > 50
                assert page.locator("#canon-todo-cards svg.canon-svg-layers").first.bounding_box()["width"] > 30
                page.locator('.canon-view-bar [data-canon-view="todo"]').click()
                expect(page.locator("#canon-hosts")).to_be_hidden()
                expect(page.locator("#canon-todo-section")).to_be_visible()
                page.locator('.canon-view-bar [data-canon-view="all"]').click()
                expect(page.locator("#canon-hosts")).to_be_visible()
                expect(page.locator("#canon-evidence-badge")).to_contain_text("실물 제어 아님")
                expect(page.locator("#canonical-main")).to_contain_text("실물 로봇 제어·적용 권한이 없습니다")
                expect(page.locator("#canon-kpis")).to_contain_text("0.274 < 0.35 rad")
                for theme in ("light", "dark"):
                    page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if width == 390:
                    page.set_viewport_size({"width": 320, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.set_viewport_size({"width": 390, "height": 900})

                page.locator("#canon-unit").select_option("sim_rad")
                expect(page.locator("#canon-spec-body")).to_contain_text("0.5907")
                page.locator("#canon-unit").select_option("raw_ticks")
                expect(page.locator("#canon-spec-body")).to_contain_text("2130")

                expect(page.locator("#canon-eval-body")).to_contain_text("48/50")
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
                playwright.expect(page.locator("#canon-todo-empty")).to_be_visible()
                playwright.expect(page.locator("#canon-job-submit")).to_be_disabled()
                playwright.expect(page.locator("#canon-job-cause")).to_contain_text("설정되지 않았습니다")
                page.route("**/api/learning/canonical/recording-todo", lambda route: route.fulfill(status=503))
                page.reload(wait_until="domcontentloaded")
                playwright.expect(page.locator("#canon-todo-meta")).to_contain_text("unavailable")
                playwright.expect(page.locator("#canon-kpis")).to_contain_text("0.274 < 0.35 rad")
                assert errors == []
            finally:
                browser.close()
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)
