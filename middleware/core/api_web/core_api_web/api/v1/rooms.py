"""Public robot discovery hints; discovery never grants connection authority."""

from __future__ import annotations

import math
import subprocess
import threading
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core_common.discover import DiscoveredDevice, get_shared_cache
from core_common.protocol import discovery_txt
from core_common.protocol.schemas import SiteRoomsSnapshot

rooms_router = APIRouter(prefix="/api/v1/site", tags=["site"])
_ROBOT_SERVICE = discovery_txt.ROBOT
_MAX_ROOMS = 64
_MAX_OUTPUT = 128 * 1024
_FALLBACK_TTL_S = 5.0
_lock = threading.Condition()
_inflight = False
_expires = 0.0
_cached = ()
_error = None


class _Unavailable(Exception):
    """Discovery is unavailable; no empty successful scan is fabricated."""


def _rooms(devices):
    found, identities, conflicts = {}, {}, set()
    for device in devices:
        if discovery_txt.normalize_service_type(device.service_type) != _ROBOT_SERVICE:
            continue
        for address in device.addresses:
            verdict = discovery_txt.classify(device.service_type, device.host, address,
                                             device.port, list(device.txt))
            if not isinstance(verdict, discovery_txt.Accepted) or verdict.host is None:
                continue
            host = verdict.host
            if host in conflicts:
                continue
            identity = verdict.txt.get("name", device.instance).strip().casefold()
            if not identity or len(identity) > 256:
                continue
            old_host = identities.get(identity)
            if old_host is not None and old_host != host:
                conflicts.add(old_host)
                if host in found:
                    conflicts.add(host)
                continue
            scheme = "https" if verdict.txt.get("tls") == "required" else "http"
            signature = (address, device.port, scheme, identity)
            if host in found and found[host][0] != signature:
                conflicts.add(host)
                continue
            elif host not in found:
                if len(found) >= _MAX_ROOMS:
                    continue
                found[host] = (signature, {"hostname": host, "address": address,
                                           "port": device.port, "kind": "robot",
                                           "url": f"{scheme}://{host}:{device.port}/pilot/#join"})
                identities[identity] = host
    return [found[host][1] for host in sorted(found) if host not in conflicts]


def _parse_avahi(output):
    devices = []
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (len(columns) != 10 or columns[0] != "="
                or discovery_txt.normalize_service_type(columns[4]) != _ROBOT_SERVICE
                or columns[5].rstrip(".").lower() != "local"):
            continue
        try:
            port = int(columns[8])
        except ValueError:
            continue
        devices.append(DiscoveredDevice(columns[3], columns[4], columns[6], port,
                                        (columns[7],), tuple(discovery_txt.parse_txt_pairs(columns[9]))))
    return _rooms(devices)


def _avahi_browse_robot(*, timeout_s):
    try:
        proc = subprocess.Popen(["avahi-browse", "-r", "-t", "-p", "-k", _ROBOT_SERVICE],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    except OSError as exc:
        raise _Unavailable("Avahi discovery is unavailable") from exc
    output = bytearray()
    overflow = threading.Event()

    def read_output():
        try:
            while True:
                chunk = proc.stdout.read(min(4096, _MAX_OUTPUT + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _MAX_OUTPUT:
                    overflow.set()
                    break
        except OSError:
            overflow.set()

    reader = threading.Thread(target=read_output, name="rosy-room-output", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_s
    try:
        while proc.poll() is None and not overflow.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Unavailable("Avahi discovery timed out")
            overflow.wait(min(.02, remaining))
        if overflow.is_set():
            raise _Unavailable("Avahi discovery output exceeded its limit")
        reader.join(timeout=.5)
        if reader.is_alive() or overflow.is_set() or proc.returncode != 0:
            raise _Unavailable("Avahi discovery did not complete")
        return _parse_avahi(output.decode("utf-8", errors="replace"))
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=.5)
        except subprocess.TimeoutExpired as exc:
            raise _Unavailable("Avahi discovery process did not stop") from exc
        reader.join(timeout=.5)
        if not reader.is_alive():
            proc.stdout.close()


def _fallback(*, timeout_s):
    global _inflight, _expires, _cached, _error
    deadline = time.monotonic() + timeout_s + 1.0
    with _lock:
        while _inflight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Unavailable("Discovery is already in progress")
            _lock.wait(remaining)
        if time.monotonic() < _expires:
            if _error is not None:
                raise _Unavailable(_error)
            return [dict(row) for row in _cached]
        _inflight = True
    rows, error = (), None
    try:
        rows = tuple(_avahi_browse_robot(timeout_s=timeout_s))
    except _Unavailable as exc:
        error = str(exc)
    except BaseException:
        error = "Avahi discovery failed"
        raise
    finally:
        with _lock:
            _cached, _error = rows, error
            _expires = time.monotonic() + _FALLBACK_TTL_S
            _inflight = False
            _lock.notify_all()
    if error is not None:
        raise _Unavailable(error)
    return [dict(row) for row in rows]


def scan_robots(*, browse=None, timeout_s=4.0):
    if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 4:
        raise ValueError("discovery timeout must be finite and between zero and four seconds")
    if browse is not None:
        return _rooms(browse(timeout_s=timeout_s))
    cache = get_shared_cache()
    if cache.browse(_ROBOT_SERVICE):
        return _rooms(cache.snapshot(_ROBOT_SERVICE))
    return _fallback(timeout_s=timeout_s)


@rooms_router.get("/rooms", response_model=SiteRoomsSnapshot)
def site_rooms():
    try:
        rows = scan_robots(timeout_s=4.0)
    except _Unavailable as exc:
        return JSONResponse(status_code=503, headers={"Cache-Control": "no-store"},
                            content={"code": "DISCOVERY_UNAVAILABLE", "message": str(exc)})
    body = SiteRoomsSnapshot(rooms=rows).model_dump()
    return JSONResponse(headers={"Cache-Control": "no-store"}, content=body)
