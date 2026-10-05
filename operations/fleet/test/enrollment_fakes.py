"""A fake robot CORE behind httpx.MockTransport for D-361 enrollment tests.

Code and token values are assembled at runtime so no literal secret is tracked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from fleet.server.console import FleetConsole
from fleet.server.discovery import DiscoveryStore
from fleet.server.enrollment import EnrollmentService
from fleet.server.enrollment_store import EnrollmentStore
from fleet.server.roster import SiteRoster
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

KEY = bytes(range(32))
CODE = "7KXM" + "P3QA"
ISSUED = "site-" + "tok-" + "Rz81"
#: The token a moved robot issues when its new screen code is exchanged at the new address.
REISSUED = "site-" + "tok-" + "Qm47"
AUTH = "Authori" + "zation"
PINNED = "192.168.1.202:8080"
MOVED = "192.168.1.203:8080"
NAME = "rosy-pinky-8kcn"


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeCore:
    """One robot CORE at one address."""

    def __init__(self, *, role="operator", source="pair-physical", hostname=NAME,
                 robot_id="rosy_09", serial="sn-8kcn", lifetime=timedelta(days=7),
                 skew=timedelta(0), pair_status=201, pair_detail=None, retry_after=None,
                 token=ISSUED, pose=(0.0, 0.0), navigation="IDLE", path=(), known=(),
                 device_uid=None) -> None:
        self.role, self.source, self.hostname = role, source, hostname
        self.robot_id, self.serial, self.token = robot_id, serial, token
        created = datetime(2026, 9, 29, tzinfo=timezone.utc) + skew
        self.created_at = created.isoformat(timespec="seconds")
        self.expires_at = (created + lifetime).isoformat(timespec="seconds")
        self.pair_status, self.pair_detail, self.retry_after = pair_status, pair_detail, retry_after
        self.pose, self.navigation, self.path = pose, navigation, list(path)
        self.logout_status = 204
        #: Tokens this robot issued earlier and still honours (a moved robot keeps its old one).
        self.known = set(known)
        self.device_uid = device_uid
        self.logged_out: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/pair":
            if self.pair_status != 201:
                headers = {"Retry-After": str(self.retry_after)} if self.retry_after else {}
                return httpx.Response(self.pair_status, headers=headers, json={"error": {
                    "code": "X", "message": "refused", "detail": self.pair_detail}})
            return httpx.Response(201, json={
                "id": "tid-9", "token": self.token, "role": self.role, "label": "site:x",
                "source": self.source, "expires_at": self.expires_at})
        bearer = (request.headers.get(AUTH) or "").removeprefix("Bearer ")
        if bearer != self.token and bearer not in self.known:
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "no"}})
        if path == "/api/v1/auth/whoami":
            return httpx.Response(200, json={"id": "tid-9", "role": self.role, "label": "site:x",
                                             "source": self.source, "created_at": self.created_at,
                                             "expires_at": self.expires_at})
        if path == "/api/v1/system/info":
            info = {"robot_id": self.robot_id, "hostname": self.hostname,
                    "serial_number": self.serial}
            if self.device_uid is not None:
                info["device_uid"] = self.device_uid
            return httpx.Response(200, json=info)
        if path == "/api/v1/auth/logout":
            if self.logout_status == 204:
                self.logged_out.append(bearer)
                self.known.discard(bearer)
            return httpx.Response(self.logout_status)
        if path == "/api/v1/system/capabilities":
            return httpx.Response(200, json={"navigation": {"goal_navigation": True},
                                             "swarm": {"lead": True, "follow": True}})
        if path == "/api/v1/robot/state":
            return httpx.Response(200, json={"robot_id": self.robot_id, "navigation": self.navigation,
                                             "pose": {"x": self.pose[0], "y": self.pose[1],
                                                      "yaw": 0.0}})
        if path == "/api/v1/navigation/path":
            return httpx.Response(200, json={"poses": [{"x": x, "y": y} for x, y in self.path]})
        if path == "/api/v1/map":
            return httpx.Response(200, json={})
        if path == "/api/v1/navigation/cancel":
            return httpx.Response(200, json={"canceled": True})
        return httpx.Response(200, json={"accepted": True})


class Network:
    """Routes requests by host:port and records every request."""

    def __init__(self, cores: dict[str, FakeCore]) -> None:
        self.cores = cores
        self.requests: list[tuple[str, str, str, bool]] = []
        #: Every request whole (headers and body), to prove what never reached an address.
        self.raw: list[tuple[str, httpx.Request]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        address = f"{request.url.host}:{request.url.port}"
        self.requests.append((request.method, address, request.url.path, AUTH in request.headers))
        self.raw.append((address, request))
        core = self.cores.get(address)
        if core is None:
            raise httpx.ConnectError("no route to host", request=request)
        return core.handle(request)

    def paths(self, address: str | None = None) -> list[str]:
        return [path for _, where, path, _ in self.requests if address in (None, where)]

    def clear(self) -> None:
        self.requests.clear()
        self.raw.clear()

    def carried(self, address: str, secret: str) -> list[str]:
        """Paths of requests to `address` that carried `secret` anywhere (URL, headers, body)."""
        hits = []
        for where, request in self.raw:
            if where != address:
                continue
            text = str(request.url) + repr(list(request.headers.items())) + request.content.decode(
                "utf-8", "replace")
            if secret in text:
                hits.append(request.url.path)
        return hits


def scan_row(address: str = PINNED, name: str = NAME, hostname: str | None = None) -> dict:
    host, port = address.split(":")
    return {"name": name, "hostname": hostname if hostname is not None else f"{name}.local",
            "address": host, "port": int(port)}


def build(tmp_path, cores: dict[str, FakeCore], *, static=(), key=KEY, clock=None):
    network = Network(cores)
    endpoints = [RobotEndpoint(robot.robot_id, f"http://10.0.0.{i + 1}:8080", f"rest-{i}")
                 for i, robot in enumerate(static)]
    console = FleetConsole(endpoints, list(static))
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                             robot_ids=set(console.robot_ids))
    roster = SiteRoster(console, task_service=tasks)
    discovery = DiscoveryStore()
    store = EnrollmentStore(tmp_path / "fleet.sqlite3")
    service = EnrollmentService(store, roster, key=key, fleet_name="site-a", discovery=discovery,
                                transport=httpx.MockTransport(network), clock=clock or Clock())
    return service, network, console, discovery, store, tasks
