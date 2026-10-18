"""Web budget verdicts were consolidated into the architecture gate (D-362, now D-766).

D-262 ran a src-wide `.js`/`.html` scan from this package with a 600-line
budget and its own verdict table. D-362 (2026-09-30) moved web budgets into
``test/architecture/test_module_structure.py`` (800 for web assets), a strict
superset of this scan. The local table had already drifted by then:
``site/fleet/fleet/server/web/map-view.js`` was committed at 612 lines with no
verdict (e89e09e1, 2026-09-30). D-766 (2026-10-15) made the limits absolute and
froze what is over in ``test/architecture/size_ratchet.txt``; the rule lives in
``tools/harness/size_limits.py``. What stays here is the machine-checked
hand-off: the architecture gate must actually own what D-262 cared about.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def _size_limits():
    spec = importlib.util.spec_from_file_location("rosy_size_limits", REPO / "tools" / "harness" / "size_limits.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_budgets_are_owned_by_the_architecture_gate():
    limits = _size_limits()
    # D-262 scanned .js and .html; D-362 covers those plus .css.
    assert {".js", ".html", ".css"} <= limits.WEB_SUFFIXES
    assert limits.FILE_LIMIT_WEB == 800
    # The two files D-262 kept verdicts for stay frozen as ratchet rows.
    rows, _ = limits.parse_ratchet((REPO / limits.RATCHET).read_text(encoding="utf-8"))
    assert "perception/web/diagnostic.html" in rows
    assert "simulation/gazebo/scripts/lane_live_view.html" in rows
