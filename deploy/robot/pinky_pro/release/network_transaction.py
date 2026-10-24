"""One recoverable owner for site Wi-Fi changes; ports never expose secrets."""

from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from network import NetworkProvisioner, SetupRequest


SITE_PROFILE = NetworkProvisioner.SITE_PROFILE
STATE_DIR = "var/lib/rosy/network"
LOCK_DIR = "run/rosy-network"
TERMINAL = {"committed", "rolled_back", "rejected"}
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
BUDGET_S = 120


def _secure_dir(root, relative):
    """Every parent is checked; private leaves prevent unprivileged path swaps."""
    path = Path(root)
    for part in Path(relative).parts:
        path /= part
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("unsafe network directory")
        if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise OSError("unsafe network directory owner")
    os.chmod(path, 0o700)
    return path


def _open_private(path, flags, mode=0o600):
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), mode)
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or
            (os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077))):
        os.close(descriptor)
        raise OSError("unsafe network file")
    return descriptor


def _read(path):
    try:
        descriptor = _open_private(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise OSError("oversized network journal")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise OSError("invalid network journal")
    return data


def _write(path, record):
    if path.is_symlink():
        raise OSError("unsafe network journal")
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        descriptor = _open_private(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def change_lock(root=Path("/"), *, blocking=False):
    """Yield ownership, or False when busy; all radio writers share this lock."""
    path = _secure_dir(root, LOCK_DIR) / "change.lock"
    descriptor = _open_private(path, os.O_RDWR | os.O_CREAT)
    acquired = False
    try:
        try:
            if os.name == "posix":
                import fcntl
                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(descriptor, flags)
            else:
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            acquired = True
        except (BlockingIOError, PermissionError):
            pass
        yield acquired
    finally:
        if acquired:
            if os.name == "posix":
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            else:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def _valid(ssid, psk):
    if not isinstance(ssid, str) or not isinstance(psk, str):
        return False
    try:
        valid_ssid = 1 <= len(ssid.encode("utf-8")) <= 32 and not any(ord(c) < 32 or ord(c) == 127 for c in ssid)
    except UnicodeEncodeError:
        return False
    request = SetupRequest("KR", "validation", psk, "validation", "validation")
    return valid_ssid and psk.isascii() and not any(ord(c) < 32 or ord(c) == 127 for c in psk) and not request.validate()


def _result(state, request_id=None, code=None, **fields):
    return {"state": state, "request_id": request_id, "code": code or state, **fields}


def validate_request(ssid, psk, request_id):
    """Pure boundary check shared by the queue and recovery HTTP frontend."""
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id) or not _valid(ssid, psk):
        raise ValueError("invalid_network_request")


class _ClaimLost(RuntimeError):
    pass


class NetworkTransaction:
    def __init__(self, backend, *, root=Path("/"), clock=time.monotonic, sleep=time.sleep,
                 maintenance_check=None, claim=None, on_commit=None):
        self.backend = backend
        self.root = Path(root)
        self.clock = clock
        self.sleep = sleep
        self.maintenance_check = maintenance_check
        self.claim = claim
        self.on_commit = on_commit

    def _paths(self):
        directory = _secure_dir(self.root, STATE_DIR)
        jobs = _secure_dir(self.root, STATE_DIR + "/jobs")
        return directory / "transaction.json", jobs

    def _save(self, record):
        journal, jobs = self._paths()
        _write(journal, record)
        if record["state"] in TERMINAL:
            _write(jobs / (record["request_id"] + ".json"), record)

    @staticmethod
    def _refresh(lease):
        try:
            if lease is not None and hasattr(lease, "refresh"):
                lease.refresh()
        except Exception:
            raise _ClaimLost("claim_lost") from None

    def _observed(self):
        data = self.backend.observe()
        fields = ("uuid", "ssid", "interface", "ipv4", "active", "default_route", "internet")
        return {key: data.get(key) for key in fields if key in data}

    def _matches(self, observed, profile_uuid, ssid):
        try:
            address = ipaddress.IPv4Interface(observed.get("ipv4") or "").ip
        except ValueError:
            return False
        return (observed.get("active") is True and observed.get("uuid") == profile_uuid and
                observed.get("ssid") == ssid and observed.get("interface") == getattr(self.backend, "interface", "wlan0") and
                not address.is_loopback and not address.is_unspecified and not address.is_multicast)

    def _wait(self, profile_uuid, ssid, deadline, lease):
        while self.clock() < deadline:
            self._refresh(lease)
            observed = self._observed()
            if self._matches(observed, profile_uuid, ssid):
                return observed
            self.sleep(min(1, max(0, deadline - self.clock())))
        raise TimeoutError("verification_timeout")

    def _recovery(self):
        try:
            self.backend.request_recovery()
        except Exception:
            pass

    def _held(self, record, code):
        record.update(state="held", code=code)
        try:
            self._save(record)
        except Exception:
            pass
        return record

    def _rollback(self, record, lease):
        record.update(state="rolling_back", code="rolling_back")
        try:
            self._save(record)
            self._refresh(lease)
            deadline = self.clock() + BUDGET_S
            previous = record["previous"]
            self.backend.restore(previous, timeout_s=BUDGET_S)
            observed = self._wait(previous["uuid"], previous["ssid"], deadline, lease)
            self._refresh(lease)
            self.backend.discard(record["profile_uuid"])
            record.update(state="rolled_back", code="rolled_back", observed=observed)
            self._save(record)
            return record
        except _ClaimLost:
            return self._held(record, "claim_lost")
        except Exception:
            self._recovery()
            return self._held(record, "restore_unverified")

    def _commit(self, record, lease):
        self._refresh(lease)
        record.update(state="committing", code="committing")
        self._save(record)
        self.backend.promote(record["profile_uuid"], record["previous"])
        self._refresh(lease)
        observed = self._observed()
        if not self._matches(observed, record["profile_uuid"], record["ssid"]):
            raise RuntimeError("candidate_lost")
        record["observed"] = observed
        if self.on_commit:
            self.on_commit({"request_id": record["request_id"], "profile_uuid": record["profile_uuid"],
                            "ssid": record["ssid"], "observation": observed})
        self._refresh(lease)
        record.update(state="committed", code="committed")
        self._save(record)
        return record

    def _run_locked(self, operation, request_id):
        if self.claim is None:
            return _result("held", request_id, "claim_unavailable")
        try:
            with self.claim() as lease:
                with change_lock(self.root) as acquired:
                    if not acquired:
                        return _result("busy", request_id, "network_busy")
                    if not self.maintenance_check or not self.maintenance_check():
                        return _result("rejected", request_id, "needs_maintenance")
                    self._refresh(lease)
                    return operation(lease)
        except _ClaimLost:
            return _result("held", request_id, "claim_lost")
        except Exception:
            return _result("held", request_id, "network_unavailable")

    def connect(self, ssid, psk, *, request_id):
        try:
            validate_request(ssid, psk, request_id)
        except ValueError:
            return _result("rejected", None, "invalid_request")

        def apply(lease):
            journal, jobs = self._paths()
            current = _read(journal)
            if current and current.get("state") not in TERMINAL:
                resumed = self._resume(lease)
                if resumed.get("state") not in {"committed", "rolled_back"}:
                    return resumed
                current = _read(journal)
            cached = _read(jobs / (request_id + ".json"))
            if cached is None and current and current.get("request_id") == request_id:
                cached = current
            if cached:
                return cached if cached.get("ssid") == ssid else _result("rejected", request_id, "request_id_conflict")
            if current:
                # Recover the journal-to-archive power-cut window before replacing it.
                _write(jobs / (current["request_id"] + ".json"), current)
            previous = self.backend.site_profile()
            if previous is None:
                self._recovery()
                return _result("held", request_id, "site_profile_missing")
            record = _result("prepared", request_id, ssid=ssid, profile_uuid=str(uuid.uuid4()), previous=previous)
            self._save(record)
            try:
                deadline = self.clock() + BUDGET_S
                self._refresh(lease)
                self.backend.prepare(record["profile_uuid"], ssid, psk)
                record.update(state="activating", code="activating")
                self._save(record)
                self._refresh(lease)
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError("activation_timeout")
                self.backend.activate(record["profile_uuid"], timeout_s=remaining)
                record["observed"] = self._wait(record["profile_uuid"], ssid, deadline, lease)
                return self._commit(record, lease)
            except _ClaimLost:
                return self._held(record, "claim_lost")
            except Exception:
                return self._rollback(record, lease)

        return self._run_locked(apply, request_id)

    def status(self, request_id=None):
        if request_id is not None and (not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id)):
            return _result("rejected", None, "invalid_request")
        try:
            journal, jobs = self._paths()
            current = _read(journal)
            record = _read(jobs / (request_id + ".json")) if request_id else current
            if record is None and current and current.get("request_id") == request_id:
                record = current
            result = dict(record or _result("unknown" if request_id else "idle", request_id))
            result["observed"] = self._observed()
            return result
        except Exception:
            return _result("held", request_id, "status_unavailable")

    def _resume(self, lease):
        journal, _ = self._paths()
        record = _read(journal)
        if not record:
            return _result("idle")
        if record.get("state") in TERMINAL:
            return record
        if record.get("state") == "committing":
            try:
                observed = self._observed()
                if self._matches(observed, record["profile_uuid"], record["ssid"]):
                    record["observed"] = observed
                    return self._commit(record, lease)
            except _ClaimLost:
                return self._held(record, "claim_lost")
            except Exception:
                pass
        return self._rollback(record, lease)

    def reconcile(self):
        return self._run_locked(self._resume, None)
