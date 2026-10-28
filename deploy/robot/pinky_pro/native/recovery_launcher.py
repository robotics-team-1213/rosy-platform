"""Root recovery credential issuance and unprivileged installed HTTPS launch."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import subprocess
import time

from network_recovery import RecoveryCoordinator, RecoveryError, RecoveryState, issue_code
from network_recovery_http import serve as serve_https
from network_runtime import network_request, read_json, recovery_state

STORE = "var/lib/rosy/network-recovery"
VERIFIER = STORE + "/verifier.json"
CERTIFICATE = STORE + "/certificate.pem"
PRIVATE_KEY = STORE + "/private-key.pem"
TLS_IDENTITY = STORE + "/tls-identity.json"
RUNTIME = "run/rosy-network-recovery"
AUTH_DIR = RUNTIME + "/auth"
DISPLAY = "run/rosy-boot/recovery-display.txt"


@dataclass(frozen=True)
class Accounts:
    owner_uid: int
    recovery_uid: int
    recovery_gid: int
    display_gid: int


def _accounts():
    import grp
    import pwd
    return Accounts(0, pwd.getpwnam("rosy-recovery").pw_uid,
                    grp.getgrnam("rosy-recovery").gr_gid, grp.getgrnam("rosy-display").gr_gid)


@contextmanager
def _directory(root, relative, accounts, *, create=False, owner=None, group=None, mode=0o750):
    """Walk directory descriptors so neither an ancestor nor the leaf can redirect writes."""
    owner = accounts.owner_uid if owner is None else owner
    group = accounts.recovery_gid if group is None else group
    parts = Path(relative).parts
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            info = os.fstat(descriptor)
            if info.st_uid != accounts.owner_uid or info.st_mode & 0o022:
                raise RecoveryError("credential_permissions_invalid")
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
            if index == len(parts) - 1:
                info = os.fstat(descriptor)
                if info.st_uid not in {accounts.owner_uid, owner} or info.st_mode & 0o022:
                    raise RecoveryError("credential_permissions_invalid")
                if create:
                    os.fchown(descriptor, owner, group)
                    os.fchmod(descriptor, mode)
                elif info.st_uid != owner or stat.S_IMODE(info.st_mode) != mode:
                    raise RecoveryError("credential_permissions_invalid")
        yield descriptor
    finally:
        os.close(descriptor)


def _read(directory, name, accounts, *, group=None):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != accounts.owner_uid
                or info.st_gid != (accounts.recovery_gid if group is None else group)
                or stat.S_IMODE(info.st_mode) != 0o640 or info.st_size > 65536):
            raise RecoveryError("credential_permissions_invalid")
        return handle.read(65537)


def _write(directory, name, content, accounts, *, group=None):
    _read(directory, name, accounts, group=group)
    temporary = "." + name + "." + secrets.token_hex(8)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchown(handle.fileno(), accounts.owner_uid, accounts.recovery_gid if group is None else group)
            os.fchmod(handle.fileno(), 0o640)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


@contextmanager
def _issuance_lock(directory, accounts):
    import fcntl
    descriptor = os.open(".issue.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != accounts.owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RecoveryError("credential_permissions_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def _fingerprint(certificate):
    der = ssl.PEM_cert_to_DER_cert(certificate.decode("ascii"))
    return ":".join(f"{value:02X}" for value in hashlib.sha256(der).digest())


def _tls(root, directory, state, name, accounts, run):
    identity = {"device_uid": state.device_uid, "hardware_serial": state.hardware_serial,
                "ap_address": state.ap_address, "device_name": name}
    certificate = _read(directory, "certificate.pem", accounts)
    key = _read(directory, "private-key.pem", accounts)
    metadata = _read(directory, "tls-identity.json", accounts)
    if any(value is not None for value in (certificate, key, metadata)):
        if not all(value is not None for value in (certificate, key, metadata)):
            raise RecoveryError("tls_unavailable")
        stored = json.loads(metadata)
        if any(stored.get(field) != value for field, value in identity.items()):
            raise RecoveryError("tls_identity_mismatch")
        fingerprint = _fingerprint(certificate)
        if stored.get("fingerprint") != fingerprint or stored.get("key_sha256") != hashlib.sha256(key).hexdigest():
            raise RecoveryError("tls_unavailable")
        return fingerprint
    staging = ".tls-" + secrets.token_hex(8)
    os.mkdir(staging, 0o700, dir_fd=directory)
    temporary = Path(root) / STORE / staging
    try:
        result = run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
                      "-days", "3650", "-subj", "/CN=" + name,
                      "-addext", f"subjectAltName=DNS:{name},IP:{state.ap_address}",
                      "-keyout", str(temporary / "private-key.pem"), "-out", str(temporary / "certificate.pem")])
        if result.returncode != 0:
            raise RecoveryError("tls_unavailable")
        files = []
        for filename in ("certificate.pem", "private-key.pem"):
            descriptor = os.open(temporary / filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != accounts.owner_uid or info.st_size > 65536:
                    raise RecoveryError("tls_unavailable")
                files.append(handle.read(65537))
        certificate, key = files
        fingerprint = _fingerprint(certificate)
        _write(directory, "private-key.pem", key, accounts)
        _write(directory, "certificate.pem", certificate, accounts)
        _write(directory, "tls-identity.json", json.dumps(dict(identity, fingerprint=fingerprint,
               key_sha256=hashlib.sha256(key).hexdigest())).encode(), accounts)
        return fingerprint
    finally:
        for filename in ("private-key.pem", "certificate.pem"):
            try:
                (temporary / filename).unlink()
            except FileNotFoundError:
                pass
        temporary.rmdir()


def eligible(root=Path("/"), *, state_supplier=None):
    try:
        return (state_supplier or (lambda: recovery_state(root)))().eligible()
    except Exception:
        return False


def issue(root=Path("/"), *, renew=False, state_supplier=None, run=_run, accounts=None,
          euid=os.geteuid, clock=time.monotonic):
    if euid() != 0:
        raise PermissionError("root_required")
    accounts = accounts or _accounts()
    state = (state_supplier or (lambda: recovery_state(root)))()
    if not state.eligible():
        raise RecoveryError("recovery_unavailable")
    identity = read_json(root, "etc/rosy/device-identity.json")
    name = identity.get("device_name", "")
    if identity.get("device_uid") != state.device_uid or not re.fullmatch(r"rosy-pinky-[a-z2-9]{4}", name):
        raise RecoveryError("identity_invalid")
    try:
        with _directory(root, STORE, accounts, create=True) as store:
            with _issuance_lock(store, accounts):
                with _directory(root, RUNTIME, accounts, create=True):
                    pass
                with _directory(root, AUTH_DIR, accounts, create=True, owner=accounts.recovery_uid, mode=0o700):
                    pass
                with _directory(root, "run/rosy-boot", accounts, create=True,
                                group=accounts.display_gid, mode=0o755) as display:
                    fingerprint = _tls(root, store, state, name, accounts, run)
                    previous = _read(store, "verifier.json", accounts)
                    record = json.loads(previous) if previous else {}
                    if renew or record.get("context") != state.scope():
                        record, code = issue_code(state, now=clock(), uid=0)
                        _write(store, "verifier.json", json.dumps(record).encode(), accounts)
                        text = (f"DEVICE={name}\nURL=https://{state.ap_address}:8443\n"
                                f"CODE={code[:4]}-{code[4:]}\nSHA256={fingerprint}\n"
                                f"EXPIRES_MONOTONIC={record['deadline']}\n"
                                f"BOOT_ID={state.boot_id}\nAP_EPOCH={state.ap_epoch}\n")
                        _write(display, "recovery-display.txt", text.encode(), accounts, group=accounts.display_gid)
                    return {"active": True, "boot_id": state.boot_id, "fingerprint": fingerprint,
                            "url": f"https://{state.ap_address}:8443"}
    except RecoveryError:
        raise
    except Exception:
        raise RecoveryError("tls_unavailable") from None


def run_frontend(root=Path("/"), *, request=network_request, serve=serve_https, accounts=None, euid=os.geteuid):
    accounts = accounts or _accounts()
    if euid() == 0 or euid() != accounts.recovery_uid:
        raise PermissionError("recovery_user_required")
    rotated = False
    def record():
        with _directory(root, STORE, accounts) as directory:
            raw = _read(directory, "verifier.json", accounts)
            if not raw:
                raise RecoveryError("authentication_unavailable")
            return json.loads(raw)
    try:
        verifier = record()
        def current():
            nonlocal rotated
            if record().get("id") != verifier.get("id"):
                rotated = True
                raise RecoveryError("credential_rotated")
            snapshot = request("network.status", {}).get("recovery")
            if not isinstance(snapshot, dict):
                raise RecoveryError("recovery_unavailable")
            return RecoveryState(**snapshot)
        coordinator = RecoveryCoordinator(current, request, verifier,
            auth_state_path=Path(root) / AUTH_DIR / "auth-state.json")
        if coordinator.active_state() is None:
            raise RecoveryError("recovery_unavailable")
        with _directory(root, AUTH_DIR, accounts, owner=accounts.recovery_uid, mode=0o700):
            pass
        serve(coordinator, Path(root) / CERTIFICATE, Path(root) / PRIVATE_KEY,
              assets_dir=Path(root) / "opt/rosy/native-runtime/recovery-web")
        if rotated:
            # A physical reissue restarts the unprivileged process through Restart=on-failure.
            raise RecoveryError("credential_rotated")
    except RecoveryError:
        raise
    except Exception:
        raise RecoveryError("recovery_unavailable") from None
