"""E-stop release with the robot's administrator screen code (user decision 2026-10-31)."""

from __future__ import annotations

import pytest

from enrollment_fakes import CODE, ISSUED, NAME, PINNED, FakeCore, build, scan_row
from fakes import run
from fleet.server.enrollment import EnrollmentError

ADMIN = "admin-" + "tok-" + "Xq20"


def latched(tmp_path, *, role="administrator", **core_fields):
    core = FakeCore()
    service, network, console, discovery, store, _ = build(tmp_path, {PINNED: core})
    discovery.replace_scan([scan_row()])
    run(service.enroll(code=CODE, principal_id="alice", discovery_name=NAME))
    # The robot now shows a new code of `role`; the enrolled operator token still works.
    core.role, core.token, core.known, core.estop = role, ADMIN, {ISSUED}, True
    for key, value in core_fields.items():
        setattr(core, key, value)
    network.clear()
    return service, network, core, store


def refused(service) -> EnrollmentError:
    with pytest.raises(EnrollmentError) as caught:
        run(service.release_estop("rosy_09", code=CODE, principal_id="alice"))
    return caught.value


def test_admin_screen_code_releases_once_and_the_token_is_logged_out(tmp_path):
    service, network, core, store = latched(tmp_path)

    answer = run(service.release_estop("rosy_09", code=CODE, principal_id="alice"))

    assert answer == {"robot_id": "rosy_09", "estop": False}
    assert core.released == [ADMIN] and core.estop is False
    assert core.logged_out == [ADMIN]
    assert network.paths(PINNED)[-4:] == ["/api/v1/auth/pair", "/api/v1/system/info",
                                          "/api/v1/safety/release", "/api/v1/auth/logout"]
    assert any(row["action"] == "estop_release" and row["outcome"] == "released"
               and row["principal_id"] == "alice" for row in store.audit_rows())
    for text in (repr(answer), repr(store.rows()), repr(store.audit_rows())):
        assert ADMIN not in text and CODE not in text


def test_a_robot_not_in_estop_is_refused_before_the_code_is_used(tmp_path):
    service, network, core, _ = latched(tmp_path)
    core.estop = False

    assert refused(service).code == "not_latched"
    assert "/api/v1/auth/pair" not in network.paths()


def test_an_operator_code_is_refused_and_its_token_logged_out(tmp_path):
    service, network, core, _ = latched(tmp_path, role="operator")

    error = refused(service)

    assert (error.code, error.reason) == ("code_consumed", "admin_required")
    assert core.estop is True and core.released == []
    assert core.logged_out == [ADMIN]
    assert "/api/v1/safety/release" not in network.paths()


def test_a_different_robot_behind_the_address_is_not_released(tmp_path):
    service, network, core, _ = latched(tmp_path, robot_id="rosy_77")

    error = refused(service)

    assert (error.code, error.reason) == ("code_consumed", "wrong_robot")
    assert core.released == [] and core.logged_out == [ADMIN]
