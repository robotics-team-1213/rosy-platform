"""The one way to write a cell-arm-{a,b}-stack.json: flock sidecar, hash check, original mode, timestamped .bak (newest 5).

cell_site_register, cell_calibrate and cell_surface all write the config through here, so a promote is not lost to a
calibration run (or the other way round) and a registered slot's evidence keys survive a whole-file rewrite.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

KEEP_BACKUPS = 5
LOCK_TIMEOUT_S = 30.0
# cell_site_target.REGISTER_KEYS, repeated: this module stays stdlib-only and importable by every writer
SLOT_KEYS = ("status", "provenance", "history", "measured_xy", "measured_z", "measured_tier_step")


class ConfigError(ValueError):
    pass


@contextlib.contextmanager
def locked(config):
    """flock on <config>.lock (resolved path, so a symlinked config has one lock)."""
    try:
        import fcntl
    except ImportError:  # not a cell host
        yield
        return
    with open(str(Path(config).resolve()) + ".lock", "a") as fh:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ConfigError("config is locked by another writer") from None
                time.sleep(0.05)
        yield


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dump(cfg: dict, indent: int = 2) -> str:
    return json.dumps(cfg, indent=indent, ensure_ascii=False) + "\n"  # shortcut: re-indents the file


def atomic_write(path, text: str, expect_sha: str | None = None) -> None:
    """Temp file in the same folder with the original mode, fsync, os.replace; the previous file is kept as <path>.bak-<time>.
    A symlink is resolved first. expect_sha: refuse when another writer changed the file since it was read."""
    path = Path(path).resolve()
    if expect_sha is not None and sha256_bytes(path.read_bytes()) != expect_sha:
        raise ConfigError("config changed while it was being updated; nothing written, retry")
    shutil.copy2(path, f"{path}.bak-{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns() % 10**6:06d}")
    for old in sorted(path.parent.glob(path.name + ".bak-*"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    if hasattr(os, "O_DIRECTORY"):  # POSIX: persist the rename too
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


GEOMETRY_KEYS = ("place", "surface_z", "yaw_deg", "tier_step_m", "map_from")  # what a registered slot's measurements are about


def _registered(entry) -> bool:
    return isinstance(entry, dict) and str((entry.get("provenance") or {}).get("tool", "")).startswith("cell_site_register/")


def write_config(path, config: dict, indent: int = 2, changed: dict | None = None) -> None:
    """Whole-file rewrite by a writer that read the config earlier (calibrate, surface). Under the lock the file is read again; for
    every site made by cell_site_register the disk entry's geometry and evidence keys win over the writer's stale copy, except the
    keys the writer names in changed ({site: (key, ...)}, e.g. the surface_z it just touched). A site registered meanwhile is kept."""
    changed = changed or {}
    with locked(path):
        raw = Path(path).resolve().read_bytes()
        disk = json.loads(raw.decode("utf-8")).get("sites") or {}
        sites = config.setdefault("sites", {})
        for name, entry in disk.items():
            if not isinstance(entry, dict):
                continue
            if name not in sites:
                if any(k in entry for k in SLOT_KEYS):
                    sites[name] = entry
                continue
            keys = (*SLOT_KEYS, *GEOMETRY_KEYS) if _registered(entry) else SLOT_KEYS
            mine = {k: sites[name][k] for k in changed.get(name, ()) if k in sites[name]}
            for key in keys:
                if key in entry:
                    sites[name][key] = entry[key]
            sites[name].update(mine)
        atomic_write(path, dump(config, indent), sha256_bytes(raw))


def write_config_checked(path, config: dict, indent: int = 2, done: list | None = None) -> str | None:
    """write_config for a writer whose arm has already moved. A failed write (lock timeout, file changed) must not lose what was
    measured: the touched heights go to <config>.unwritten-<time>.json and the returned message says so. None when written.
    done: the writer's step results; {"surface <site>": "touched", "surface_z": z} marks a measured height."""
    touched = {}
    for res in done or ():
        for step, outcome in res.items():
            if step.startswith("surface ") and outcome == "touched" and isinstance(res.get("surface_z"), (int, float)):
                touched[step.split()[1]] = res["surface_z"]
    try:
        write_config(path, config, indent, {name: ("surface_z",) for name in touched})
    except (ConfigError, OSError, ValueError) as exc:
        side = Path(f"{Path(path).resolve()}.unwritten-{time.strftime('%Y%m%dT%H%M%S')}.json")
        try:
            side.write_text(json.dumps({"config": str(path), "error": str(exc), "surface_z": touched}, indent=1), encoding="utf-8")
            where = f"; measured heights saved in {side}"
        except OSError:
            where = f"; could not save the measured heights {touched}"
        return f"config not written: {exc}{where}"
    return None
