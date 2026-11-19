"""Screen-code, manual-address, candidate selection, and code-exchange helpers (D-361)."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Any

import httpx

from fleet.server.enrollment_errors import EnrollmentError

CODE_ALPHABET = frozenset("23456789ABCDEFGHJKMNPQRSTUVWXYZ")
CODE_LENGTH = 8
DEFAULT_PORT = 8080
SITE_WARN_S = 14 * 86400.0
LEGACY_WARN_S = 48 * 3600.0
SITE_LIFETIME_S = 90 * 86400.0
_AVAHI_SUFFIX = re.compile(r"^(?P<base>.+)-\d+$")
#: The console applies the same RFC 1918 rule before sending (web/enrollment.js).
_RFC1918 = tuple(ipaddress.ip_network(net) for net in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _seconds_between(start: object, end: object) -> float | None:
    try:
        return (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds()
    except (TypeError, ValueError):
        return None


def normalize_code(text: object) -> str:
    """Drop spaces and hyphens, uppercase, check the alphabet before any robot call."""
    if not isinstance(text, str):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    code = "".join(ch for ch in text if ch not in " -\t").upper()
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    return code


def parse_manual_address(text: object) -> str:
    """Private LAN IPv4[:port] only; `.local`, hostnames and public addresses are refused."""
    if not isinstance(text, str) or not text.strip():
        raise EnrollmentError("bad_address", 400, "enter the robot's private LAN IPv4 address, optionally with :port")
    host, _, port_text = text.strip().partition(":")
    try:
        ip = ipaddress.ip_address(host)
        port = int(port_text) if port_text else DEFAULT_PORT
    except ValueError:
        raise EnrollmentError("bad_address", 400,
                              "enter the robot's private LAN IPv4 address, optionally with :port") from None
    if (ip.version != 4 or not any(ip in net for net in _RFC1918)
            or not 1 <= port <= 65535):
        raise EnrollmentError("bad_address", 400, "only private LAN IPv4 addresses are accepted")
    return f"{ip}:{port}"


class EnrollmentCandidateMixin:
    """Candidate resolution, TLS binding prechecks, and screen-code exchange with CORE."""

    def _pending_binding(self, hostnames: set[str], port: int):
        """D-565: an HTTPS robot with no row enrolls only through an approved pending binding."""
        binding = (self._tls_bindings.pending(self._store.rows(), next(iter(hostnames)), port)
                   if self._tls_bindings is not None and len(hostnames) == 1 else None)
        if binding is None:
            raise EnrollmentError("tls_binding_required", 409, "HTTPS requires an approved TLS binding")
        return binding

    def _refuse_http_for_binding(self, hostnames: set[str], address: str) -> None:
        """D-565: a name or address an approved binding owns never enrolls over plain HTTP."""
        bound = {row["robot_id"] for row in self._store.rows() if row["address"] == address}
        if self._tls_bindings is not None and self._tls_bindings.claims(hostnames, bound):
            raise EnrollmentError("tls_binding_required", 409, "that robot has an approved TLS binding")

    def _candidate(self, discovery_name: str | None, address: str | None) -> tuple[str, dict | None, Any]:
        if (discovery_name is None) == (address is None):
            raise EnrollmentError("bad_request", 400, "choose one discovered robot or one address")
        if address is not None:
            target = parse_manual_address(address)
            secure = [row for row in (self._discovery.rows() if self._discovery else [])
                      if f"{row['address']}:{row['port']}" == target and row.get("transport") == "https"]
            enrolled = [row for row in self._store.rows() if row["address"] == target]
            if secure and not enrolled:
                return target, None, self._pending_binding({r["hostname"] for r in secure}, secure[0]["port"])
            if secure and (len(enrolled) != 1 or self._tls_bindings is None
                           or self._tls_bindings.binding(enrolled[0]["robot_id"]) is None):
                raise EnrollmentError("tls_binding_required", 409, "HTTPS requires approved enrolled TLS binding")
            if not secure:
                self._refuse_http_for_binding(
                    {row["hostname"] for row in (self._discovery.rows() if self._discovery else [])
                     if f"{row['address']}:{row['port']}" == target}, target)
            return target, None, None
        if self._discovery is None:
            raise EnrollmentError("not_discovered", 404, "that robot is not in the current scan")
        if any((row.get("discovery_name") or row["hostname"]).lower() == discovery_name.lower()
               for row in self._store.rows()):
            raise EnrollmentError("already_enrolled", 409, "that robot is already enrolled")
        console = self._console()
        snapshot = self._discovery.snapshot(console.registered_endpoints,
                                            console.hub.registry.identity_snapshot(),
                                            self.enrolled_names())
        rows = [row for row in snapshot["devices"] if row["name"] == discovery_name]
        if not rows:
            raise EnrollmentError("not_discovered", 404, "that robot is not in the current scan")
        if len({(row["address"], row["port"]) for row in rows}) > 1 or any(
                row["status"] == "conflict" for row in rows):
            raise EnrollmentError("conflict", 409, "that name is seen at several addresses")
        row = rows[0]
        pending = None
        if row.get("transport") == "https":
            registered = [r for r in self._store.rows() if r["address"] == f"{row['address']}:{row['port']}"]
            if not registered:
                pending = self._pending_binding({row["hostname"]}, row["port"])
            elif (len(registered) != 1 or self._tls_bindings is None
                    or self._tls_bindings.binding(registered[0]["robot_id"]) is None):
                raise EnrollmentError("tls_binding_required", 409, "HTTPS requires approved enrolled TLS binding")
        else:
            self._refuse_http_for_binding({row["hostname"]}, f"{row['address']}:{row['port']}")
        if not row.get("enrollable"):
            raise EnrollmentError("not_enrollable", 409, "that row is not waiting for registration")
        return f"{row['address']}:{row['port']}", row, pending

    async def _exchange(self, http: httpx.AsyncClient, code: str, principal_id: str,
                        target: str, action: str = "enroll") -> dict:
        body = {"code": code, "label": f"site:{self._fleet_name}", "purpose": "site"}
        try:
            response = await http.post("/api/v1/auth/pair", json=body)
        except httpx.HTTPError:
            self._store.audit(action=action, outcome="unreachable", principal_id=principal_id,
                              target=target)
            raise EnrollmentError("unreachable", 502, "the robot is not reachable (address, port)") from None
        status = response.status_code
        if status == 201:
            try:
                paired = response.json()
                if not isinstance(paired.get("token"), str) or not paired["token"]:
                    raise ValueError
                return paired
            except (ValueError, AttributeError):
                self._store.audit(action=action, outcome="robot_error",
                                  principal_id=principal_id, target=target)
                raise EnrollmentError("robot_error", 502, "the robot answered without a token") from None
        outcome = {401: "code_rejected", 429: "rate_limited", 403: "lan_forbidden",
                   400: "bad_format"}.get(status, "robot_error")
        detail = {}
        try:
            detail = (response.json().get("error") or {}).get("detail") or {}
        except (ValueError, AttributeError):
            pass
        if status == 401 and isinstance(detail, dict) and detail.get("burned"):
            outcome = "code_burned"
        self._store.audit(action=action, outcome=outcome, principal_id=principal_id, target=target)
        if outcome == "rate_limited":
            try:
                retry_after = max(1, int(response.headers.get("Retry-After", "60")))
            except ValueError:
                retry_after = 60
            raise EnrollmentError("rate_limited", 429, "too many attempts at this robot",
                                  retry_after=retry_after)
        messages = {
            "code_rejected": "the code is wrong, used or expired",
            "code_burned": "this robot's screen code was burned",
            "lan_forbidden": "the robot sees this server as outside its LAN",
            "bad_format": "the robot refused the code format",
            "robot_error": f"the robot answered {status}",
        }
        http_status = {"code_rejected": 401, "code_burned": 401, "lan_forbidden": 403,
                       "bad_format": 400}.get(outcome, 502)
        raise EnrollmentError(outcome, http_status, messages[outcome])

    @staticmethod
    def _consumed(reason: str, **detail) -> EnrollmentError:
        return EnrollmentError("code_consumed", 409,
                               "the code was consumed; restart the robot or get an administrator code",
                               reason=reason, detail=detail)

    @staticmethod
    async def _logout(http: httpx.AsyncClient, token: str) -> bool:
        """One logout attempt. True when the robot no longer holds the token."""
        from fleet.server.enrollment_tls import EnrollmentTlsError
        try:
            response = await http.post("/api/v1/auth/logout",
                                       headers={"Authorization": f"Bearer {token}"})
        except (httpx.HTTPError, EnrollmentTlsError):
            return False
        return response.status_code in (204, 401)
