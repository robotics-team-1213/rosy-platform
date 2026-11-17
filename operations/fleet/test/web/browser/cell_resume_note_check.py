"""Standalone Playwright check (no pytest): cell-resume-view note / restart-confirm / refusals with mocked API.

Run: python operations/fleet/test/web/browser/cell_resume_note_check.py
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[5]
SHARED = ROOT / "shared" / "web"
FLEET = ROOT / "applications" / "fleet" / "web"

PAGE = """<!doctype html><meta charset=utf-8><link rel=stylesheet href=/common/components.css>
<body><div id=anchor></div><script type=module>
import "/common/ui.js";
import {confirmIrreversible} from "/common/ui.js";
import {createConfirmedAction} from "/console/assets/confirmed-action.js";
import {createCellResumeView} from "/console/assets/cell-resume-view.js";
const scope = {capture: () => ({signal: new AbortController().signal, current: () => true, check() {}}),
  listen: (el, ev, fn) => el.addEventListener(ev, fn), onDispose() {}, guard: f => f};
const id = {role: "operator", locked: false, token: "t", principal: "kim"};
const act = createConfirmedAction({scope, identity: () => id, confirm: confirmIrreversible});
async function call(url, o = {}) {
  const r = await fetch(url, {method: o.method || "GET", headers: o.headers, body: o.body});
  const b = await r.json().catch(() => ({}));
  if (!r.ok) { const d = b.detail || {}; throw Object.assign(new Error(d.message || d.code || "err"), {status: r.status, code: d.code}); }
  return b;
}
const v = createCellResumeView({scope, call, anchor: document.getElementById("anchor"), active: true,
  approveReason: () => "", principal: () => "kim", confirm: o => act.run(o)});
window.refresh = () => v.refresh();
</script>"""

DATA = {
    "human_safety": {"human_detected": {"cell_s": False, "cell_ab": False}, "active_estop": False},
    "cells": {},
    "tasks": [{"task_id": "t1", "cell_id": "cell_s", "arm_id": "arm_s", "status": "PAUSED_HUMAN",
               "paused_by": "alice", "paused_reason": "HUMAN_DETECTED_ESTOP", "paused_from_status": "RUNNING"}],
    "decision_proposals": [{"decision_id": "d1", "proposed_by": "ai-1", "cell": "cell_s"}],
}


def main():
    posts, mode = [], {"resume": []}

    def route(r):
        req = r.request
        u = req.url.split("//", 1)[1].split("/", 1)[1]
        path = "/" + u.split("?")[0]
        if path == "/":
            return r.fulfill(body=PAGE, content_type="text/html")
        if path.startswith("/common/"):
            f = SHARED / path[8:]
        elif path == "/console/assets/confirmed-action.js":
            f = FLEET / "confirmed-action.js"
        elif path == "/console/assets/cell-resume-view.js":
            f = FLEET / "work" / "cell-resume-view.js"
        elif path == "/console/assets/poll-gate.js":
            f = FLEET / "shared" / "poll-gate.js"
        elif path == "/api/fleet/pipeline/cell-tasks":
            return r.fulfill(body=json.dumps(DATA), content_type="application/json")
        elif path.endswith("/resume"):
            body = json.loads(req.post_data)
            posts.append(body)
            status, detail = mode["resume"].pop(0)
            return r.fulfill(status=status, body=json.dumps({"detail": detail}), content_type="application/json")
        else:
            return r.fulfill(status=404, body="")
        ct = "text/css" if f.suffix == ".css" else "text/javascript"
        return r.fulfill(body=f.read_text(encoding="utf8"), content_type=ct)

    fails = []

    def check(cond, msg):
        print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/*", route)
        pg.goto("http://test.local/")
        pg.evaluate("refresh()")
        pg.wait_for_selector("[data-paused-task=t1]")
        t = "[data-paused-task=t1]"

        # proposal field names come straight from the server
        check(pg.locator("[data-decision-proposal=d1]").count() == 1, "proposal rendered by decision_id")
        check("alice" in pg.locator(t).inner_text() and "사람 감지 비상정지" in pg.locator(t).inner_text(), "paused_by/paused_reason shown")

        def open_resume():
            pg.locator(f"{t} ui-button").click()
            pg.wait_for_selector("dialog.ui-confirm[open]")

        # note required: action disabled until 1..200 chars
        open_resume()
        run = pg.locator("dialog.ui-confirm ui-button[kind=irreversible]")
        check(run.evaluate("e => e.disabled || e.hasAttribute('disabled')"), "send disabled with empty note")
        check("사유 메모" in (run.get_attribute("reason") or ""), "disabled reason names the note")
        pg.fill("dialog.ui-confirm input", "x" * 250)
        check(pg.locator("dialog.ui-confirm input").input_value() == "x" * 200, "note capped at 200")
        pg.fill("dialog.ui-confirm input", "확인함")
        check(not run.evaluate("e => e.disabled"), "send enabled once note typed")

        # restart path: 409 -> second explicit confirm -> resend with restart_from_start
        mode["resume"] = [(409, {"code": "RESUME_NEEDS_RESTART_CONFIRM"}), (200, {})]
        run.click()
        pg.wait_for_function("document.querySelector('dialog.ui-confirm[open]')?.innerText.includes('처음부터 다시 시작합니다')")
        check(pg.locator("dialog.ui-confirm input").count() == 0, "restart confirm has no note field")
        check(posts[0] == {"note": "확인함"}, "first post has note only")
        pg.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        pg.wait_for_function("document.querySelector('#cell-resume-status')?.textContent.includes('재개됨')")
        check(posts[1] == {"note": "확인함", "restart_from_start": True}, "second post carries restart_from_start")

        # each refusal shown once, in Korean
        for code, text in [("CELL_ABORTED_HOLD", "중단"), ("ARM_HOLD_ACTIVE", "팔 홀드가"), ("HUMAN_HOLD_ACTIVE", "셀 안전 홀드"),
                           ("NOTE_REQUIRED", "사유 메모")]:
            pg.goto("http://test.local/")  # a refusal keeps the button locked with its reason until the next load
            pg.evaluate("refresh()")
            pg.wait_for_selector("[data-paused-task=t1] ui-button:not([disabled])")
            mode["resume"] = [(409 if code != "NOTE_REQUIRED" else 422, {"code": code})]
            open_resume()
            pg.fill("dialog.ui-confirm input", "n")
            pg.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            pg.wait_for_function("t => document.querySelector(t).innerText.includes(arguments[0] || '')" if False else
                                 "([t, s]) => document.querySelector(t).innerText.includes(s)", arg=[t, text])
            n = pg.locator("body").inner_text().count(text)
            check(n == 1, f"{code} shown once (count {n})")
        check(not errs, f"no page errors {errs}")
        b.close()
    sys.exit(1 if fails else 0)


main()
