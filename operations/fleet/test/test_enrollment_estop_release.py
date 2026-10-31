"""E-stop release with the robot's screen release code (user decision 2026-10-31, API v1.337)."""

from __future__ import annotations

import pytest

from enrollment_fakes import CODE, ISSUED, NAME, PINNED, FakeCore, build, scan_row
from fakes import run
from fleet.server.enrollment import EnrollmentError

#: What the latched robot's screen shows (a different code from the enrollment one).
SCREEN = "HJKM" + "NPQR"


def latched(tmp_path):
    core = FakeCore()
    service, network, console, discovery, store, _ = build(tmp_path, {PINNED: core})
    discovery.replace_scan([scan_row()])
    run(service.enroll(code=CODE, principal_id="alice", discovery_name=NAME))
    core.estop, core.release_code = True, SCREEN
    network.clear()
    return service, network, core, store


def refused(service, code=SCREEN) -> EnrollmentError:
    with pytest.raises(EnrollmentError) as caught:
        run(service.release_estop("rosy_09", code=code, principal_id="alice"))
    return caught.value


def test_the_screen_code_releases_over_the_enrolled_operator_connection(tmp_path):
    service, network, core, store = latched(tmp_path)

    answer = run(service.release_estop("rosy_09", code="hjkm-npqr", principal_id="alice"))

    assert answer == {"robot_id": "rosy_09", "estop": False} and core.estop is False
    assert core.release_calls == [{"code": SCREEN}]
    calls = [r for where, r in network.raw if r.url.path == "/api/v1/safety/release-code"]
    assert [r.headers["Authorization"] for r in calls] == [f"Bearer {ISSUED}"]
    assert "/api/v1/auth/pair" not in network.paths()
    assert any(row["action"] == "estop_release" and row["outcome"] == "released"
               and row["principal_id"] == "alice" for row in store.audit_rows())
    for text in (repr(answer), repr(store.rows()), repr(store.audit_rows())):
        assert SCREEN not in text


@pytest.mark.parametrize("setup, expected", [
    (lambda core: setattr(core, "estop", False), "not_latched"),
    (lambda core: None, "code_rejected"),
    (lambda core: setattr(core, "release_status", 409), "release_refused"),
])
def test_robot_refusals_are_classified_and_audited(tmp_path, setup, expected):
    service, _, core, store = latched(tmp_path)
    setup(core)

    error = refused(service, code=CODE if expected == "code_rejected" else SCREEN)

    assert error.code == expected
    assert any(row["action"] == "estop_release" and row["outcome"] == expected for row in store.audit_rows())


def test_a_mistyped_code_keeps_the_robot_enrolled(tmp_path):
    """Review 2026-10-31: a wrong code must not read as Fleet's credential dying (401)."""
    service, _, _, store = latched(tmp_path)

    assert refused(service, code=CODE).code == "code_rejected"
    assert store.get("rosy_09")["state"] == "active"


def test_a_malformed_code_never_reaches_the_robot(tmp_path):
    service, network, core, _ = latched(tmp_path)

    assert refused(service, code="0000").code == "bad_format"
    assert core.release_calls == [] and network.paths() == []
