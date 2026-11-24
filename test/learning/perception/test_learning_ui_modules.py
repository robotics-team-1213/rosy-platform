"""Unit and static serving checks for shared Learning UI web helpers."""
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
LEARNING_PERCEPTION = REPO / "learning" / "curation" / "perception"
WEB = LEARNING_PERCEPTION / "review_app_web"


def test_review_static_serves_learning_ui_and_preauth_lists_it():
    static_text = (LEARNING_PERCEPTION / "review_static.py").read_text(encoding="utf-8")
    collab_text = (LEARNING_PERCEPTION / "learning_collaboration.py").read_text(encoding="utf-8")
    assert "'/learning-ui.js': 'learning-ui.js'" in static_text
    assert "'/learning-ui.js'" in collab_text
    assert (WEB / "learning-ui.js").is_file()


def test_learning_ui_helpers_unit_checks(tmp_path):
    mod_file = tmp_path / "learning-ui.mjs"
    mod_file.write_text((WEB / "learning-ui.js").read_text(encoding="utf-8"), encoding="utf-8")
    script = f"""
import assert from "node:assert/strict";
globalThis.location = {{ origin: "https://learning.test" }};
const mod = await import({json.dumps(mod_file.as_uri())});
const u1 = mod.makeUuid();
const u2 = mod.makeUuid();
assert.match(u1, /^[0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$/);
assert.notEqual(u1, u2);
assert.equal(mod.safeLocalUrl("/api/learning/recording/preview/cam0?t=1"), "/api/learning/recording/preview/cam0?t=1");
assert.equal(mod.safeLocalUrl("//evil.test/x"), null);
assert.equal(mod.safeLocalUrl("https://evil.test/x"), null);
assert.equal(mod.safeLocalUrl("relative/path"), null);
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
