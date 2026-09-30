"""tools/web_visible_roles.py - the in-repo role-surface measurement harness.

Pins the judgement surface (problems_in) with mutations, the constants the
role model rests on, and the real-CORE seam (build_client answers the role
surfaces over HTTP). No Playwright needed here - the browser half is what
the tool itself runs.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import web_visible_roles  # noqa: E402


def test_each_role_has_its_own_token_and_reachable_surfaces():
    tokens = [token for _role, token, _surfaces in web_visible_roles.ROLES]
    assert len(tokens) == len(set(tokens)), "roles share a dev token"
    for role, _token, surfaces in web_visible_roles.ROLES:
        assert surfaces, f"{role} reaches no surface"
    assert ("administrator", "rosy-dev-admin", ("console", "setup", "device")) \
        in web_visible_roles.ROLES


def test_viewports_cover_desktop_and_mobile():
    widths = {width for width, _height in web_visible_roles.VIEWPORTS}
    assert 1366 in widths and 390 in widths


def test_the_measure_script_counts_kindless_buttons():
    assert "data-kind-missing" in web_visible_roles.MEASURE


def _row(**changes):
    row = {
        "role": "operator", "surface": "console", "viewport": 1366,
        "measurements": {"missingKinds": 0, "scrollWidth": 1366, "viewport": 1366},
        "firstResponses": [("/console", 200)],
    }
    row.update(changes)
    return row


def test_a_clean_report_has_no_problems():
    report = {"results": [_row()], "pageErrors": []}
    assert web_visible_roles.problems_in(report) == []


@pytest.mark.parametrize("mutation, fragment", [
    ({"measurements": {"missingKinds": 2, "scrollWidth": 1366, "viewport": 1366}},
     "without a kind"),
    ({"measurements": {"missingKinds": 0, "scrollWidth": 1420, "viewport": 1366}},
     "horizontal overflow"),
    ({"firstResponses": [("/console", 200), ("/assets/app.js", 404)]},
     "answered 404"),
])
def test_each_violation_shape_is_reported(mutation, fragment):
    report = {"results": [_row(**mutation)], "pageErrors": []}
    problems = web_visible_roles.problems_in(report)
    assert len(problems) == 1 and fragment in problems[0]


def test_page_errors_are_reported():
    report = {"results": [], "pageErrors": ["TypeError: x is undefined"]}
    assert "page error" in web_visible_roles.problems_in(report)[0]


def test_the_real_core_serves_the_role_surfaces(tmp_path):
    client = web_visible_roles.build_client(tmp_path)
    for path in ("/console", "/setup", "/device"):
        response = client.get(path, headers={"Authorization": "Bearer rosy-dev-admin"})
        assert response.status_code == 200, path
