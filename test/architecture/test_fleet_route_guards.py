"""Every /api/fleet route that changes state, or reads, sits behind an auth guard (2026-11-13 R incident).

The live Fleet on R served 12 routes with ``dependencies=[]``. This builds the real Fleet app and walks each
route's FastAPI dependant tree. A route passes when a site role guard (or a named machine-ingress guard) is in
that tree. Routes that check a credential inside the handler are listed below, each with its reason; the two
tables are checked both ways, so a stale entry fails like a new offender.
"""

from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi.routing import APIRoute

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

# Site role guards from auth/site_auth.build_role_guards, plus the guards other installers own:
# require_ai_observer (AI PC facts), parent_only (control-unit parent), require_camera_viewer (vision lease).
ROLE_GUARDS = frozenset({
    "require_viewer", "require_operator", "require_named_operator", "require_proposer",
    "require_ai_observer", "parent_only", "require_camera_viewer",
})
# Machine ingress: the arm-transfer observer token dependency (work/physical_transfer_observer_routes.py).
INGRESS_GUARDS = frozenset({"authenticate"})
GUARDS = ROLE_GUARDS | INGRESS_GUARDS
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# No guard in the dependant tree, so the handler checks the credential itself. One reason per row.
INLINE_AUTH = {
    ("POST", "/api/fleet/auth/development-session"): "always answers 403 human login required",
    ("GET", "/api/fleet/admin/db-status"): "require_admin(): cookie session, policy-admin, same origin",
    ("PUT", "/api/fleet/admin/db-settings"): "require_admin(): cookie session, policy-admin, same origin",
    ("POST", "/api/fleet/admin/db-maintenance"): "require_admin(): cookie session, policy-admin, same origin",
    ("POST", "/api/fleet/workcell-observations/{workcell_id}/intake-readings"):
        "X-Workcell-Observation-Token (workcell ingress)",
    ("POST", "/api/fleet/workcell-observations/{workcell_id}/port-events"):
        "X-Workcell-Observation-Token (workcell ingress)",
    ("POST", "/api/fleet/workcell-observations/arms/{source_id}"):
        "X-Workcell-Observation-Token (arm ingress, intake.authorize)",
    ("POST", "/api/fleet/device-profiles/{device_id}/load-reports/{source_id}"):
        "X-Workcell-Observation-Token (arm ingress, observations.authorize)",
    ("DELETE", "/api/fleet/ai/human-classes/{type_key}"):
        "authorize + inline permits_site('fleet.policy', policy-admin)",
}
# GET routes that need no role guard. Each is public or answers about the caller's own session.
PUBLIC_READS = {
    ("GET", "/api/fleet/auth/connection"): "login discovery: mode and whether password login exists",
    ("GET", "/api/fleet/auth/session"): "authorize only: reports the caller's own session",
}
ALLOWED = {**INLINE_AUTH, **PUBLIC_READS}


@pytest.fixture(scope="module")
def routes(tmp_path_factory):
    users = {sha256(f"fleet-{role}".encode()).hexdigest(): {"principal_id": f"site-{role}", "role": role}
             for role in ("viewer", "operator", "policy-admin")}
    service = FleetTaskService(FleetTaskStore(tmp_path_factory.mktemp("fleet") / "fleet.sqlite3"), robot_ids=set())
    app = create_app(FleetConsole([], []), site_users=users, task_service=service,
                     vision_lease_secret="v" * 32, vision_sources=("ceiling-north",))
    return [route for route in app.routes
            if isinstance(route, APIRoute) and route.path.startswith("/api/fleet")]


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        names.add(getattr(sub.call, "__name__", repr(sub.call)))
        names |= _dependency_names(sub)
    return names


def _unguarded(routes) -> set[tuple[str, str]]:
    return {(method, route.path) for route in routes if not _dependency_names(route.dependant) & GUARDS
            for method in route.methods - {"HEAD", "OPTIONS"}}


def test_fleet_app_builds_the_routes_this_test_judges(routes):
    assert len(routes) > 150, "the app built with too few routes; the guard check would pass vacuously"
    assert any(method in MUTATING for route in routes for method in route.methods)


def test_every_fleet_route_has_an_auth_guard_or_a_listed_inline_check(routes):
    offenders = sorted(_unguarded(routes) - ALLOWED.keys())
    assert not offenders, "Fleet routes without an auth guard (add require_*/read_guard, or list the inline check):\n" \
        + "\n".join(f"  {method} {path}" for method, path in offenders)


def test_allow_tables_only_name_routes_that_exist_and_lack_a_guard(routes):
    stale = sorted(ALLOWED.keys() - _unguarded(routes))
    assert not stale, f"allow-listed routes that are gone or now guarded (remove the row): {stale}"

