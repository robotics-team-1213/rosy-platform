#!/usr/bin/env python3
"""Verify and atomically activate native ROSY releases.

The live runtime is only the ``/opt/rosy/current`` symlink.  A journal is
flushed before that link moves, so the boot-time recovery command can always
restore the last accepted release after an interrupted activation.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Callable, Protocol


# Installed copies carry signing.py beside this file (install-native-runtime.sh),
# and the script directory is already first on sys.path. The repository path is
# only a fallback for running from a checkout, so it must never shadow the
# installed module (D-174 F1).
# Bytecode written beside an installed release would be an unlisted file that
# fails signature verification, including verify(old_current) during recovery.
sys.dont_write_bytecode = True
RELEASE_TOOLS = Path(__file__).resolve().parents[1] / "release"
if RELEASE_TOOLS.is_dir() and str(RELEASE_TOOLS) not in sys.path:
    sys.path.append(str(RELEASE_TOOLS))

from signing import sha256_file, verify_release_files  # noqa: E402


RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
REQUIRED_PAYLOAD = {
    "install/.rosy-release",
    "deploy/robot/native/rosy-runtime.target",
    "rosy-packages.txt",
    "source-revision.txt",
}
METADATA = {"manifest.json", "SHA256SUMS", "SHA256SUMS.sig"}
# D-189: the CORE Python runtime lives in the image's /usr/local, outside the
# switchable release. A release names the runtime it was built against (the
# sha256 of deploy/robot/pinky_pro/image/device-python-requirements.txt) in a signed payload
# file; the image records the one it installed. They must match.
PYTHON_RUNTIME_RELEASE_FILE = "python-runtime.sha256"
PYTHON_RUNTIME_IMAGE_FILE = Path("usr/local/share/rosy/python-runtime.sha256")
RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_TARGET = "rosy-runtime.target"
# Seconds to wait after start before judging rosy-io (bringup fails ~7 s in).
IO_SETTLE_S = 20.0
# Every unit with PartOf=rosy-runtime.target (pinned by a test).
RUNTIME_STOP_UNITS = (RUNTIME_TARGET, "rosy-core.service", "rosy-io.service", "rosy-camera.service",
                      "rosy-host-agent.service", "rosy-ssh-pairing.service")
# D-553 addendum 4: units an activation may restart alone, CORE and the rest
# keeping their processes. The caller (tools/release/ship.py) asks for it only
# when every changed payload file is camera perception code no other unit loads.
RESTARTABLE_ALONE = {"rosy-camera.service"}
UNIT_SETTLE_S = 3.0


def _runtime_id(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value if RUNTIME_ID.fullmatch(value) else None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class LinkStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, release_id: str | None) -> None: ...


class SymlinkStore:
    """Linux implementation of the two atomic release pointers."""

    def __init__(self, base: Path, releases: Path) -> None:
        self.base = base
        self.releases = releases

    def _path(self, name: str) -> Path:
        if name not in {"current", "previous"}:
            raise ValueError("NATIVE_LINK_UNSAFE: unknown release link")
        return self.base / name

    def get(self, name: str) -> str | None:
        link = self._path(name)
        if not link.exists() and not link.is_symlink():
            return None
        if not link.is_symlink():
            raise ValueError(f"NATIVE_LINK_UNSAFE: {link} is not a symlink")
        resolved = link.resolve()
        if resolved.parent != self.releases.resolve() or not RELEASE_ID.fullmatch(resolved.name):
            raise ValueError(f"NATIVE_LINK_UNSAFE: {link} leaves the release store")
        return resolved.name

    def set(self, name: str, release_id: str | None) -> None:
        link = self._path(name)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() and not link.is_symlink():
            raise ValueError(f"NATIVE_LINK_UNSAFE: refusing to replace {link}")
        if release_id is None:
            link.unlink(missing_ok=True)
            return
        target = self.releases / release_id
        if target.is_symlink() or not target.is_dir() or target.resolve().parent != self.releases.resolve():
            raise ValueError("NATIVE_RELEASE_PATH: release link target is unsafe")
        temporary = link.with_name(f".{link.name}.new")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)


class NativeReleaseManager:
    """Native-systemd release switcher with fail-closed recovery."""

    def __init__(
        self,
        *,
        root: Path = Path("/"),
        public_key: Path,
        runtime: Callable[[str], None] | None = None,
        links: LinkStore | None = None,
        precheck: Callable[[], None] | None = None,
        units: Callable[[str, tuple[str, ...]], None] | None = None,
        io_active: Callable[[], bool] | None = None,
        io_settle_s: float = IO_SETTLE_S,
    ) -> None:
        self.root = Path(root).resolve()
        self.public_key = Path(public_key)
        self.releases = self.root / "opt" / "rosy" / "releases"
        self.current = self.root / "opt" / "rosy" / "current"
        self.previous = self.root / "opt" / "rosy" / "previous"
        self.state = self.root / "var" / "lib" / "rosy" / "releases"
        self.journal = self.state / "native-activation.json"
        self.lock = self.state / "native-release.lock"
        self._runtime = runtime or self._systemctl
        self.links = links or SymlinkStore(self.current.parent, self.releases)
        # D-412 review N1: a last condition (the updater's hold/seal/idle check) run
        # after verification and right before the runtime stops; raising refuses.
        self.precheck = precheck
        self._units = units or self._systemctl_units
        # rosy-io is Type=simple: "systemctl start" returns before bringup has
        # opened the motors. Real runs probe systemd; injected runtimes opt out.
        self.io_active = io_active or (self._io_is_active if runtime is None else (lambda: False))
        self.io_settle_s = io_settle_s

    @staticmethod
    def _systemctl(action: str) -> None:
        # The target is ordered After= its PartOf units, so stopping only the
        # target returns while CORE's stop job still waits behind io/camera;
        # the start that follows then cancels it and CORE keeps the old
        # release. Name every PartOf unit so systemctl waits for all of them.
        units = RUNTIME_STOP_UNITS if action == "stop" else (RUNTIME_TARGET,)
        subprocess.run(
            ["systemctl", action, *units],
            check=True,
            timeout=120,
        )

    @staticmethod
    def _systemctl_units(action: str, units: tuple[str, ...]) -> None:
        subprocess.run(["systemctl", action, *units], check=True, timeout=120)
        if action == "start":
            # Type=simple returns at fork; a unit that dies on start (bad import,
            # failed ExecCondition) shows as inactive within a few seconds.
            # ponytail: unit liveness only, like the full path's camera; a node
            # that dies inside a still-running ros2 launch is not seen here.
            time.sleep(UNIT_SETTLE_S)
            subprocess.run(["systemctl", "is-active", "--quiet", *units], check=True, timeout=30)

    @staticmethod
    def _io_is_active() -> bool:
        try:
            return subprocess.run(["systemctl", "is-active", "--quiet", "rosy-io.service"],
                                  check=False, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @contextlib.contextmanager
    def _locked(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a+b") as handle:
            if os.name == "posix":
                import fcntl

                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ValueError("NATIVE_RELEASE_BUSY: another operation is active") from exc
            try:
                yield
            finally:
                if os.name == "posix":
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _release(self, release_id: str) -> Path:
        if not RELEASE_ID.fullmatch(release_id):
            raise ValueError("RELEASE_ID_INVALID: expected YYYY.MM.DD-NNN")
        candidate = self.releases / release_id
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("NATIVE_RELEASE_MISSING: release directory is unavailable")
        if candidate.resolve().parent != self.releases.resolve():
            raise ValueError("NATIVE_RELEASE_PATH: release escapes the release store")
        return candidate

    def verify(self, release_id: str) -> dict:
        release = self._release(release_id)
        if self.public_key.is_symlink() or not self.public_key.is_file():
            raise ValueError("SIGNATURE_KEY_UNREADABLE: trusted public key is missing")
        rejections = verify_release_files(release, self.public_key)
        if rejections:
            first = rejections[0]
            raise ValueError(f"{first.code}: {first.detail}")
        try:
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("NATIVE_MANIFEST_UNREADABLE: manifest is invalid") from exc
        expected_top = {
            "schema_version", "release_id", "git_revision", "target", "runtime",
            "signing_key_id", "files",
        }
        if not isinstance(manifest, dict) or set(manifest) != expected_top:
            raise ValueError("NATIVE_MANIFEST_FIELDS: manifest shape is not supported")
        if manifest["schema_version"] != 1 or manifest["release_id"] != release_id:
            raise ValueError("NATIVE_MANIFEST_ID: release identity does not match its directory")
        if not re.fullmatch(r"[0-9a-f]{40}", str(manifest["git_revision"])):
            raise ValueError("NATIVE_MANIFEST_REVISION: full source revision is required")
        if manifest["signing_key_id"] != self.public_key.stem:
            raise ValueError("NATIVE_MANIFEST_KEY: manifest key is not the trusted key")
        target = manifest.get("target")
        required_target = {
            "board": "pinky_pro",
            "host": "raspberry-pi-5",
            "architecture": "arm64",
            "os_family": "ubuntu-server",
            "os_release": "24.04",
        }
        if target != required_target:
            differing = next(
                (key for key, value in required_target.items()
                 if not isinstance(target, dict) or target.get(key) != value),
                "target",
            )
            raise ValueError(f"NATIVE_TARGET_MISMATCH: {differing}")
        if manifest.get("runtime") != {"model": "native-systemd", "default_mode": "core"}:
            raise ValueError("NATIVE_RUNTIME_MISMATCH: core-only native systemd is required")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("NATIVE_MANIFEST_PAYLOAD: files must be a non-empty list")
        declared: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise ValueError("NATIVE_MANIFEST_PAYLOAD: invalid file entry")
            relative = entry.get("path")
            digest = entry.get("sha256")
            if (
                not isinstance(relative, str)
                or relative.startswith(("/", "\\", "~"))
                or ".." in relative.replace("\\", "/").split("/")
                or relative in declared
                or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
            ):
                raise ValueError("NATIVE_MANIFEST_PAYLOAD: unsafe or duplicate file entry")
            declared[relative] = digest
        actual = {
            path.relative_to(release).as_posix()
            for path in release.rglob("*")
            if path.is_file() and path.name not in METADATA
        }
        if set(declared) != actual or not REQUIRED_PAYLOAD <= actual:
            raise ValueError("NATIVE_MANIFEST_PAYLOAD: payload inventory is incomplete")
        for relative, digest in declared.items():
            path = release / relative
            if path.is_symlink() or sha256_file(path) != digest:
                raise ValueError(f"NATIVE_MANIFEST_PAYLOAD: digest mismatch for {relative}")
        return manifest

    def check_python_runtime(self, release_id: str) -> str:
        """Refuse a verified release whose Python runtime is not the image's.

        Only activate and rollback call this. Recovery restores the release that
        was already running and must never hold on it.
        """
        release = self._release(release_id)
        wanted = _runtime_id(release / PYTHON_RUNTIME_RELEASE_FILE)
        present = _runtime_id(self.root / PYTHON_RUNTIME_IMAGE_FILE)
        if wanted is None:
            raise ValueError(
                f"NATIVE_PYTHON_RUNTIME: release {release_id} does not declare its Python runtime "
                f"({PYTHON_RUNTIME_RELEASE_FILE}); reflash with a matching image")
        if present != wanted:
            raise ValueError(
                f"NATIVE_PYTHON_RUNTIME: this release needs Python runtime {wanted}; "
                f"this image has {present or 'none recorded'}; reflash with a matching image")
        return wanted

    def _link_id(self, link: Path) -> str | None:
        return self.links.get(link.name)

    def _set_link(self, link: Path, release_id: str | None) -> None:
        if release_id is not None:
            self._release(release_id)
        self.links.set(link.name, release_id)

    def _write_journal(
        self,
        *,
        operation: str,
        candidate: str,
        old_current: str | None,
        old_previous: str | None,
        phase: str,
    ) -> None:
        _write_json_atomic(self.journal, {
            "schema_version": 1,
            "operation": operation,
            "candidate": candidate,
            "old_current": old_current,
            "old_previous": old_previous,
            "phase": phase,
        })

    def _restore(self, old_current: str | None, candidate: str) -> None:
        self._set_link(self.current, old_current)
        self._set_link(self.previous, candidate)

    def activate(self, release_id: str, restart_units: tuple[str, ...] = ()) -> dict:
        restart_units = tuple(restart_units)
        if not set(restart_units) <= RESTARTABLE_ALONE:
            raise ValueError(f"NATIVE_RESTART_UNIT: only {sorted(RESTARTABLE_ALONE)} may restart alone")
        if restart_units:
            def runtime(action: str) -> None:
                self._units(action, restart_units)
        else:
            runtime = self._runtime
        with self._locked():
            self.verify(release_id)
            self.check_python_runtime(release_id)
            old_current = self._link_id(self.current)
            old_previous = self._link_id(self.previous)
            if old_current == release_id:
                return {"ok": True, "release_id": release_id, "previous": old_previous}
            if self.precheck is not None:
                self.precheck()
            self._write_journal(
                operation="activate", candidate=release_id,
                old_current=old_current, old_previous=old_previous, phase="prepared",
            )
            expect_io = not restart_units and self.io_active()
            runtime("stop")
            self._set_link(self.previous, old_current)
            self._set_link(self.current, release_id)
            self._write_journal(
                operation="activate", candidate=release_id,
                old_current=old_current, old_previous=old_previous, phase="switched",
            )
            try:
                runtime("start")
                if expect_io:
                    # 2026.10.10-100 on 8kcn: bringup died 7 s after start and
                    # nothing noticed. Wait past that window, then require I/O.
                    time.sleep(self.io_settle_s)
                    if not self.io_active():
                        raise RuntimeError("NATIVE_IO_NOT_ACTIVE: rosy-io.service is not active after start")
            except Exception as exc:
                runtime("stop")
                self._restore(old_current, release_id)
                if old_current is not None:
                    runtime("start")
                self.journal.unlink(missing_ok=True)
                raise RuntimeError("candidate failed health check and was rolled back") from exc
            self.journal.unlink(missing_ok=True)
            outcome = {"ok": True, "release_id": release_id, "previous": old_current}
            if restart_units:
                outcome["restarted"] = list(restart_units)
            return outcome

    def rollback(self) -> dict:
        with self._locked():
            old_current = self._link_id(self.current)
            candidate = self._link_id(self.previous)
            if old_current is None or candidate is None:
                raise ValueError("NATIVE_ROLLBACK_UNAVAILABLE: current and previous are required")
            self.verify(candidate)
            self.check_python_runtime(candidate)
            self._write_journal(
                operation="rollback", candidate=candidate,
                old_current=old_current, old_previous=candidate, phase="prepared",
            )
            self._runtime("stop")
            self._set_link(self.current, candidate)
            self._set_link(self.previous, old_current)
            self._write_journal(
                operation="rollback", candidate=candidate,
                old_current=old_current, old_previous=candidate, phase="switched",
            )
            try:
                self._runtime("start")
            except Exception as exc:
                self._runtime("stop")
                self._set_link(self.current, old_current)
                self._set_link(self.previous, candidate)
                self._runtime("start")
                self.journal.unlink(missing_ok=True)
                raise RuntimeError("rollback candidate failed; original release restored") from exc
            self.journal.unlink(missing_ok=True)
            return {"ok": True, "release_id": candidate, "previous": old_current}

    def recover(self) -> dict:
        with self._locked():
            if not self.journal.is_file():
                return {"ok": True, "recovered": False, "release_id": self._link_id(self.current)}
            try:
                data = json.loads(self.journal.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("NATIVE_RECOVERY_HOLD: activation journal is unreadable") from exc
            expected = {
                "schema_version", "operation", "candidate", "old_current",
                "old_previous", "phase",
            }
            if (
                not isinstance(data, dict)
                or set(data) != expected
                or data.get("schema_version") != 1
                or data.get("operation") not in {"activate", "rollback"}
                or data.get("phase") not in {"prepared", "switched"}
            ):
                raise ValueError("NATIVE_RECOVERY_HOLD: activation journal is invalid")
            old_current = data.get("old_current")
            candidate = data.get("candidate")
            if old_current is not None:
                self.verify(old_current)
            self._restore(old_current, candidate)
            self.journal.unlink(missing_ok=True)
            return {"ok": True, "recovered": True, "release_id": old_current}


PRECHECK_ENV = "ROSY_ACTIVATE_PRECHECK"
PRECHECK_TIMEOUT_S = 60
#: The precheck's "the robot is busy" answer. Any other failure is NATIVE_PRECHECK_FAILED.
PRECHECK_BUSY_EXIT = 3


def _env_precheck() -> Callable[[], None] | None:
    """The command named by ROSY_ACTIVATE_PRECHECK, as a precheck; exit 0 passes."""
    command = os.environ.get(PRECHECK_ENV, "").strip()
    if not command:
        return None

    def precheck() -> None:
        try:
            result = subprocess.run(shlex.split(command), capture_output=True, text=True,
                                    timeout=PRECHECK_TIMEOUT_S, check=False)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ValueError(f"NATIVE_PRECHECK_FAILED: precheck could not run: {exc}") from exc
        detail = " ".join((result.stdout + " " + result.stderr).split())[-300:]
        if result.returncode == PRECHECK_BUSY_EXIT:
            raise ValueError(f"NATIVE_PRECHECK_REFUSED: {detail}")
        if result.returncode != 0:
            raise ValueError(f"NATIVE_PRECHECK_FAILED: exit {result.returncode}: {detail}")

    return precheck


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--public-key", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--release-id", required=True)
    activate.add_argument("--restart-unit", action="append", default=[],
                          help="restart only this unit (D-553 addendum 4: rosy-camera.service)")
    verify = sub.add_parser("verify")
    verify.add_argument("--release-id", required=True)
    sub.add_parser("rollback")
    sub.add_parser("recover")
    args = parser.parse_args(argv)
    manager = NativeReleaseManager(root=args.root, public_key=args.public_key, precheck=_env_precheck())
    try:
        if args.command == "activate":
            result = manager.activate(args.release_id, tuple(args.restart_unit))
        elif args.command == "verify":
            manifest = manager.verify(args.release_id)
            result = {"ok": True, "release_id": manifest["release_id"]}
        elif args.command == "rollback":
            result = manager.rollback()
        else:
            result = manager.recover()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
