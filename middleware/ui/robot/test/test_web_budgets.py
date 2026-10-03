"""Web budget verdicts were consolidated into the architecture gate (D-362).

D-262 ran a src-wide `.js`/`.html` scan from this package with a 600-line
budget and its own verdict table. D-362 (2026-09-30) moved web budgets into
``test/architecture/test_module_structure.py`` — per-type table (800 for web
assets), set-equality, ops roots, zero growth allowance above 1000 — which is
a strict superset of this scan. The local table had already drifted by then:
``site/fleet/fleet/server/web/map-view.js`` was committed at 612 lines with no
verdict (e89e09e1, 2026-09-30). What stays here is the machine-checked
hand-off: the architecture gate must actually own what D-262 cared about.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GATE = REPO / "test" / "architecture" / "test_module_structure.py"


def _architecture_gate():
    spec = importlib.util.spec_from_file_location("rosy_module_structure_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_budgets_are_owned_by_the_architecture_gate():
    gate = _architecture_gate()
    # D-262 scanned .js and .html; D-362 covers those plus .css.
    assert {".js", ".html", ".css"} <= gate.WEB_SUFFIXES
    assert gate.FILE_BUDGET_WEB == 800
    # The two files D-262 kept verdicts for must stay under recorded verdicts.
    over = gate._over_budget()
    assert "runtime/sensing/web/diagnostic.html" in over
    assert "sim/gz_sim/scripts/lane_live_view.html" in over
