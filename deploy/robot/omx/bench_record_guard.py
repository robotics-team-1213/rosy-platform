"""Guards for the bench record page (D-943): other-arm lock holding, /proc visibility, input snapshots, restore list.

Split out of bench_record.py; behaviour is described there. Linux only (fcntl, /proc): anywhere else every check
refuses (fail closed).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import joint_tune_lock  # noqa: E402  (lock_root: where the per-arm session locks live)
from camera_roles import load_registry, resolve_record_cameras  # noqa: E402


def proc_cmdlines():
    """Command lines of every process (Linux /proc); unreadable /proc raises, so the caller refuses (fail closed)."""
    return [(p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            for p in Path("/proc").iterdir() if p.name.isdigit() and p.name != str(os.getpid()) and (p / "cmdline").exists()]


def proc_mounts():
    return Path("/proc/mounts").read_text()


def hold_other_arm_locks(arm, arms, procs=proc_cmdlines, mounts=proc_mounts, own=False):
    """(handles, None) with every OTHER arm of `arms`'s lock held, or ([], why a handover must not start). record_session --arm
    takes session.lock shared and session-<arm>.lock exclusive, so holding the same here (never the chosen arm's own,
    record_session takes that) keeps a second session from starting during handover; the caller keeps the handles
    until the units are restored. own=True also keeps the chosen arm's own lock (a caller that reads that arm's bus itself). The /proc scan is an extra check, refused when hidepid could hide processes."""
    handles = []
    try:
        import fcntl
        root = joint_tune_lock.lock_root()
        root.mkdir(parents=True, exist_ok=True)
        others = {f"session-{a}.lock" for a in arms if a != arm}
        others |= {p.name for p in root.glob("session-*.lock")} - {f"session-{arm}.lock"}
        for name, mode in [("session.lock", fcntl.LOCK_SH), *[(n, fcntl.LOCK_EX) for n in sorted(others)]]:
            handle = (root / name).open("a")
            handles.append(handle)
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _Held(f"다른 OMX 세션이 {name}을 잡고 있습니다") from None
        # The chosen arm's own lock is record_session's to take next (shared cell lock + its own); probing it here only
        # refuses a start while something else already holds it, and releases it again right away. Residual window
        # (accepted): another same-arm session may start between this probe and record_session's own lock; its exclusive
        # session-<arm>.lock makes a concurrent same-arm recording fail to start.
        mine = (root / f"session-{arm}.lock").open("a")
        handles.append(mine)
        try:
            fcntl.flock(mine, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _Held(f"다른 OMX 세션이 session-{arm}.lock을 잡고 있습니다") from None
        if not own:
            handles.pop().close()
        check_proc_visible(mounts)
        if recorder_running(procs):
            raise _Held("record_session 또는 chunk_runner가 실행 중입니다")
        return handles, None
    except Exception as exc:  # no fcntl, unreadable root or /proc: cannot prove the cell is idle
        release(handles)
        return [], str(exc) if isinstance(exc, _Held) else f"다른 세션이 없는지 확인할 수 없습니다: {type(exc).__name__}"


def hold_arm_lock(arm):
    """(handle, None) holding session-<arm>.lock exclusively for a recovery that touches the port (the configuration tool takes no lock itself),
    or (None, why). The caller releases it just before the recorder that follows takes the lock on its own."""
    try:
        import fcntl
        root = joint_tune_lock.lock_root()
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / f"session-{arm}.lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None, f"다른 OMX 세션이 session-{arm}.lock을 잡고 있습니다"
        return handle, None
    except Exception as exc:  # no fcntl or an unreadable root: cannot prove the port is ours
        return None, f"세션 잠금을 잡을 수 없습니다: {type(exc).__name__}"


def check_proc_visible(mounts=proc_mounts):
    """Raises _Held unless /proc shows every process (hidepid other than 0/off could hide a recorder); fail closed."""
    for line in mounts().splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "/proc" and fields[2] == "proc":
            if re.search(r"(^|,)hidepid=(?!(0|off)(,|$))", fields[3]):
                raise _Held("/proc가 hidepid로 마운트되어 다른 세션 프로세스를 확인할 수 없습니다")
            return
    raise _Held("/proc 마운트 옵션을 확인할 수 없습니다")


def recorder_running(procs=proc_cmdlines):
    """True when a recorder/chunk runner is alive, or when that cannot be told (fail closed)."""
    try:
        return any(re.search(r"record_session\.py|chunk_runner", line) for line in procs())
    except Exception:
        return True


class _Held(Exception):
    pass


FOLLOWER_TORQUE_ON = "팔로워 토크가 켜져 있습니다 — 사람이 팔을 받친 뒤 확인"


def follower_torque_on(out) -> bool:
    """leader_home's last stdout line says it refused to read a Follower whose torque is ON (it wrote nothing)."""
    try:
        return json.loads((out or "").strip().splitlines()[-1]).get("follower_torque_on") is True
    except (ValueError, IndexError, AttributeError):
        return False


def arm_free(arm, manual=None):
    """None when no bus child may be refused for this arm, else why not: a held lease, a live lease of another owner (D-1035) or an incident /
    local hold - the same omx_incident.refuse_if_held record_session applies, asked BEFORE any child that opens a bus (record_session would
    refuse too late, after an alignment child or a torque write already ran)."""
    import cell_arm_lease
    import omx_incident
    if manual is not None and Path(manual).exists():  # a person-check marker on disk (it survives a service restart): no bus child until a person clears it
        return f"사람 확인이 필요합니다 ({manual}) — 팔 상태를 직접 확인한 뒤 그 파일을 삭제하세요. 장치에 손대지 않았습니다"
    record = cell_arm_lease.status(arm).get(arm)
    if record and (record.get("hold") or (record.get("live") and record.get("owner") != cell_arm_lease.default_owner())):
        why = record.get("hold") or f"{record.get('owner')} ({record.get('purpose') or '-'})"
        return f"{arm} 임대가 사용 중입니다: {why} — 장치에 손대지 않았습니다 (cell_arm_lease.py release-hold는 사람이 팔을 확인한 뒤)"
    try:
        omx_incident.refuse_if_held(arm)
    except SystemExit as exc:
        return f"{exc} — 장치에 손대지 않았습니다"
    return None


def release(handles):
    for handle in reversed(handles):
        try:
            handle.close()
        except OSError:
            pass


def write_snapshot(snap, files):
    """Write each (name, bytes) into a new private dir (0700) as exclusive 0600 files and check the bytes read back."""
    snap.mkdir(parents=True, mode=0o700)
    for name, data in files:
        fd = os.open(snap / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        if (snap / name).read_bytes() != data:
            raise ValueError("스냅샷 파일이 검증한 내용과 다릅니다")


def write_restore_list(path, units):
    """The units still to restore, atomically (temp + rename); an empty list removes the file."""
    if not units:
        return path.unlink(missing_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(units))
    os.replace(tmp, path)  # a crash never leaves a half-written list


# Dependents first: camera-view's Requires= pulls readiness down with it (record_session note, 2026-10-24).
HANDOVER = (r"rosy-omx-cameras-bind\.timer",
            r"rosy-omx-camera-view\.service", r"rosy-omx-camera-readiness\.service",
            r"rosy-omx-camera@[\w-]+\.service", r"rosy-omx-observer@[\w-]+\.service")


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)


def active_handover_units(run=systemctl):
    listed = run("list-units", "--state=active,activating", "--no-legend", "--plain", "rosy-omx-*").stdout.split()
    units = [u for u in listed if u.endswith((".service", ".timer"))]
    return [u for pattern in HANDOVER for u in units if re.fullmatch(pattern, u)]


_ARM_LETTERS = {"arm_a": "a", "arm_b": "b", "arm_s": "s"}


def resolve_record_config(prep, arm):
    """Return the active record config JSON path for an arm, preferring `-live` when standard config is absent."""
    letter = _ARM_LETTERS[arm]
    primary = prep / f"record-config-arm-{letter}.json"
    if primary.is_file():
        return primary
    live = prep / f"record-config-arm-{letter}-live.json"
    return live if live.is_file() else primary


def _port_exists(port):
    return Path(port).exists() if isinstance(port, str) and port.startswith("/dev/") else None


def arm_connectivity(prep, arm):
    """Read-only USB board presence check for one arm (never opens a serial port)."""
    if arm == "arm_ab":
        a, b = arm_connectivity(prep, "arm_a"), arm_connectivity(prep, "arm_b")
        f_vals, l_vals = (a["follower_connected"], b["follower_connected"]), (a["leader_connected"], b["leader_connected"])
        f_ok = True if all(v is True for v in f_vals) else (False if any(v is False for v in f_vals) else None)
        l_ok = True if all(v is True for v in l_vals) else (False if any(v is False for v in l_vals) else None)
        return {"connected": f_ok, "follower_connected": f_ok, "leader_connected": l_ok}
    if arm not in _ARM_LETTERS:
        return {"connected": None, "follower_connected": None, "leader_connected": None}
    try:
        cfg = json.loads(resolve_record_config(prep, arm).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {"connected": None, "follower_connected": None, "leader_connected": None}
    robot, teleop = (cfg.get("robot"), cfg.get("teleop")) if isinstance(cfg, dict) else (None, None)
    f_ok = _port_exists(robot.get("port") if isinstance(robot, dict) else None)
    l_ok = _port_exists(teleop.get("port") if isinstance(teleop, dict) else None)
    return {"connected": f_ok, "follower_connected": f_ok, "leader_connected": l_ok}


def iter_config_camera_items(robot):
    if not isinstance(robot, dict):
        return []
    items = [(k, v) for k, v in (robot.get("cameras") or {}).items() if isinstance(v, dict)]
    if robot.get("type") == "bi_omx_follower":
        for side in ("arm_a", "arm_b"):
            for k, v in ((robot.get(side) or {}).get("cameras") or {}).items():
                if isinstance(v, dict):
                    items.append((f"{side}.{k}", v))
    return items


def inspect_config_cameras(cfg_j, arm, registry, *, reg_err=None):
    """Return (cam_keys, rebinds, issues, resolved_cfg) for one record-config JSON."""
    r = cfg_j.get("robot") if isinstance(cfg_j, dict) else {}
    cams = [k for k, _ in iter_config_camera_items(r)]
    if reg_err:
        return cams, [], [reg_err], cfg_j
    resolved, rebinds, issues = resolve_record_cameras(cfg_j, arm, registry)
    return cams, rebinds, issues, resolved


def check_bimanual_child(prep, sub_arm, child_robot, check_single):
    """Verify bi_omx_follower arm_a/arm_b child directly or against its signed single-arm profile with cameras={}."""
    try:
        return check_single(sub_arm, "", child_robot)
    except ValueError as primary_exc:
        if not isinstance(child_robot, dict) or child_robot.get("cameras") != {}:
            raise
        candidates = [resolve_record_config(prep, sub_arm)] + sorted(prep.glob("record-config*.json"))
        seen = set()
        for path in candidates:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                ref_robot = json.loads(path.read_text(encoding="utf-8-sig")).get("robot")
                if isinstance(ref_robot, dict) and ref_robot.get("type") == "omx_follower" and {**ref_robot, "cameras": {}} == child_robot:
                    return check_single(sub_arm, path.name, ref_robot)
            except (OSError, ValueError, TypeError):
                continue
        raise primary_exc


def resolve_start_config(config_bytes, arm):
    """Parse start config and resolve cameras from omx-cameras.json, failing closed on missing/corrupt camera state."""
    cfg_data = json.loads(config_bytes.decode("utf-8-sig"))
    registry = load_registry()
    resolved, rebinds, issues = resolve_record_cameras(cfg_data, arm, registry)
    if issues:
        raise ValueError(f"카메라 확인 실패: {'; '.join(issues)}")
    return resolved, rebinds
