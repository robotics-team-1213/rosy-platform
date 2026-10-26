"""Bound trial health: observational I/O only, stable services, fresh CORE samples and watchdog."""
from __future__ import annotations

from datetime import datetime
import http.client
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import time

from auto_update_host import Host
from os_bootloader import BINDING, RAUC_STATE, _binding, _private, _snapshot
from os_installed_factory import verify_current
from os_motion_guard import require_inhibited
from os_rauc_service import _empty_cgroup
from os_state_io import _json_atomic
from os_state_layout import _pairs, _path, _read
from os_state_ready import verify_ready
from os_update_install import read_bound_report
from os_update_policy import authorize_trial
from os_update_watchdog import observe as observe_watchdog

IO_ENVIRONMENT_FILES = "/etc/rosy/runtime.env (ignore_errors=no) /run/rosy-os-update/motion.env (ignore_errors=yes)"
SERVICE_KEYS = {"ActiveState", "SubState", "MainPID", "InvocationID", "Result", "EnvironmentFiles", "DropInPaths"}
FIELDS = BINDING | {"boot_id", "samples", "services", "projection", "native_factory", "watchdog", "observed_boottime_ns"}


def _now():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def _run(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, LC_ALL="C"))


def _call(run, argv):
    result = run(argv, timeout=30)
    if result.returncode != 0 or len(result.stdout) > 16384:
        raise ValueError("trial service observation or restart failed")
    return result.stdout


def _properties(run, unit, keys):
    raw = _call(run, ["/usr/bin/systemctl", "show", unit, *("--property=" + key for key in sorted(keys))])
    value = _pairs([line.split("=", 1) for line in raw.splitlines()])
    if set(value) != keys:
        raise ValueError("trial service properties are incomplete")
    return value


def _service(run, unit):
    value = _properties(run, unit, SERVICE_KEYS)
    _validate_service(value, unit)
    return value


def _validate_service(value, unit):
    if not isinstance(value, dict) or set(value) != SERVICE_KEYS or any(type(v) is not str for v in value.values()):
        raise ValueError("trial service receipt is malformed")
    if (value["ActiveState"] != "active" or value["SubState"] != "running" or value["Result"] != "success"
            or not re.fullmatch(r"[1-9][0-9]*", value["MainPID"])
            or not re.fullmatch(r"[0-9a-f]{32}", value["InvocationID"])):
        raise ValueError("trial runtime service is not running successfully")
    if unit == "rosy-io.service" and (
            value["EnvironmentFiles"] != IO_ENVIRONMENT_FILES
            or value["DropInPaths"] != "/etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf"):
        raise ValueError("effective observational I/O environment or drop-ins differ")


def _probe():
    """Same local API readiness endpoint as wait-core-ready.py; never follow redirects or use a proxy."""
    port = os.environ.get("ROSY_API_PORT", "8080")
    tls = os.environ.get("ROSY_API_TLS", "none")
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535 or tls not in {"none", "required"}:
        raise ValueError("CORE readiness configuration is invalid")
    host = os.environ.get("ROSY_API_TLS_HOST", "")
    if tls == "required" and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.local", host):
        raise ValueError("CORE readiness TLS identity is invalid")
    with socket.create_connection(("127.0.0.1", int(port)), timeout=2) as raw:
        if tls == "required":
            context = ssl.create_default_context(cafile=os.environ["ROSY_API_TLS_CA_FILE"])
            connection = context.wrap_socket(raw, server_hostname=host)
        else:
            connection = raw
        try:
            connection.sendall(f"GET /api/v1 HTTP/1.1\r\nHost: {host or '127.0.0.1'}:{port}\r\nConnection: close\r\n\r\n".encode("ascii"))
            response = http.client.HTTPResponse(connection)
            try:
                response.begin()
                if not 200 <= response.status < 500:
                    raise ValueError("CORE readiness endpoint failed")
            finally:
                response.close()
        finally:
            if connection is not raw:
                connection.close()


def _trial(root, transaction_id, *, checking=False):
    facts, state, default = _snapshot(root)
    pending = state["pending"]
    if (pending is None or pending["transaction_id"] != transaction_id or facts["tryboot"] != 1
            or facts["slot"] != pending["target_slot"] or pending["trial_boot_id"] != facts["boot_id"]
            or pending["phase"] not in ({"TRIAL"} if checking else {"TRIAL", "HEALTHY", "COMMIT_INTENT"})
            or default != pending["source_slot"]):
        raise ValueError("health requires the bound uncommitted trial")
    require_inhibited(root)
    return facts, pending


def _deadline():
    now = _now()
    if type(now) is not int or not 0 <= now < 165_000_000_000:
        raise ValueError("trial health reached the independent reboot deadline margin")
    return now


def _io_guard(root, factory):
    name = "rosy-os-io-guard.conf"
    owned = _read(Path(__file__).parent / name, 8192)
    actual = _read(_path(root, "etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf"), 8192, root.stat().st_uid)
    if actual != owned:
        raise ValueError("installed OS I/O guard differs from the frozen owner")
    source = "opt/rosy/releases/" + factory["release_id"] + "/deploy/robot/native/rosy-io.service"
    if (_read(_path(root, source), 16384, root.stat().st_uid)
            != _read(_path(root, "etc/systemd/system/rosy-io.service"), 16384, root.stat().st_uid)):
        raise ValueError("installed I/O unit differs from the verified factory")


def _report_path(root, pending):
    return _path(root, RAUC_STATE + "/health-" + pending["transaction_id"] + ".json")


def read_health(root: Path, pending: dict) -> dict:
    try:
        return _read_health(root, pending)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_HEALTH_HOLD: {exc}") from exc


def _read_health(root: Path, pending: dict) -> dict:
    facts, actual = _trial(root, pending["transaction_id"])
    if actual != pending:
        raise ValueError("health transaction changed")
    relative = _report_path(root, pending).relative_to(root).as_posix()
    value = _private(root, relative, FIELDS)
    if value is None or any(value[k] != v for k, v in _binding(pending).items()) or value["boot_id"] != facts["boot_id"]:
        raise ValueError("health receipt binding differs")
    observed = value["observed_boottime_ns"]
    if type(observed) is not int or not 0 <= observed <= _deadline() <= observed + 30_000_000_000:
        raise ValueError("health receipt is expired or has an invalid clock")
    if any(not isinstance(value[key], dict) for key in ("native_factory", "projection", "watchdog", "samples", "services")):
        raise ValueError("health receipt observations must be objects")
    expected = dict(schema_version=1, **pending["verified"]["metadata"]["native_factory"])
    if (value["native_factory"] != expected or type(value["native_factory"].get("schema_version")) is not int
            or value["projection"].get("boot_id") != facts["boot_id"]
            or value["projection"].get("slot") != facts["slot"] or value["watchdog"].get("boot_id") != facts["boot_id"]):
        raise ValueError("health receipt observations differ from the trial")
    samples = value["samples"]
    if (set(samples) != {"boot_id", "first_written_at", "second_written_at"} or samples["boot_id"] != facts["boot_id"]
            or not datetime.fromisoformat(samples["second_written_at"]) > datetime.fromisoformat(samples["first_written_at"])):
        raise ValueError("health receipt lacks distinct CORE samples")
    if set(value["services"]) != {"rosy-core.service", "rosy-io.service"}:
        raise ValueError("health receipt service inventory differs")
    for unit, data in value["services"].items():
        _validate_service(data, unit)
    return value


def check(root: Path, transaction_id: str, *, host: Host | None = None, run=_run) -> dict:
    """Publish health only; the commit owner must separately bind GOOD_ACK and durable intent."""
    try:
        root = Path(root).absolute()
        if root != Path("/") and run is _run:
            raise ValueError("a fake root requires an explicit test runner")
        _deadline()
        facts, pending = _trial(root, transaction_id, checking=True)
        projection = verify_ready(root)
        if projection["boot_id"] != facts["boot_id"] or projection["slot"] != facts["slot"]:
            raise ValueError("projection is not ready for this trial")
        factory = verify_current(root, pending["verified"]["metadata"])
        if read_bound_report(root, pending)["native_factory"] != factory:
            raise ValueError("installed receipt and running factory differ")
        _io_guard(root, factory)
        _call(run, ["/usr/bin/systemctl", "stop", "rosy-navigation.service"])
        navigation = _properties(run, "rosy-navigation.service", {"ActiveState", "MainPID", "ControlGroup"})
        if navigation["ActiveState"] not in {"inactive", "failed"} or navigation["MainPID"] != "0":
            raise ValueError("navigation did not stop")
        for group in {navigation["ControlGroup"], "/system.slice/rosy-navigation.service"}:
            _empty_cgroup(root, group, service="rosy-navigation.service")
        _call(run, ["/usr/bin/systemctl", "restart", "rosy-io.service"])
        services = {unit: _service(run, unit) for unit in ("rosy-core.service", "rosy-io.service")}
        watchdog = observe_watchdog(root, run=run)
        _probe()
        samples = authorize_trial(root, transaction_id, host=host)
        _probe()
        if observe_watchdog(root, run=run) != watchdog:
            raise ValueError("watchdog changed during health observation")
        if any(_service(run, unit) != value for unit, value in services.items()):
            raise ValueError("runtime service restarted or changed during health observation")
        if _trial(root, transaction_id, checking=True) != (facts, pending) or verify_ready(root) != projection:
            raise ValueError("trial or projection changed during health observation")
        _io_guard(root, factory)
        report = dict(_binding(pending), boot_id=facts["boot_id"], native_factory=factory, projection=projection,
                      services=services, watchdog=watchdog, samples=samples, observed_boottime_ns=_deadline())
        target = _report_path(root, pending)
        _private(root, target.relative_to(root).as_posix(), FIELDS)
        _json_atomic(target, report, 0o600)
        if read_health(root, pending) != report:
            raise ValueError("health receipt readback differs")
        return report
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_HEALTH_HOLD: {exc}") from exc
