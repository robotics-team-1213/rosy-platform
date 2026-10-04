"""Isolated G2 simulation ports. Fleet and the device remain the command owners."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading


def fresh_evidence(path):
    path = Path(path).resolve()
    if path.exists() and any(path.iterdir()):
        raise ValueError("G2 evidence directory must be empty; preserve previous runs")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_json(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class SimAidGoalPort:
    """Injected at the canonical final fenced dispatch edge, never a ROS writer."""

    def __init__(self, delegate, *, before):
        self.delegate, self.before = delegate, before

    def submit(self, command, *, on_goal_event):
        self.before(command)
        return self.delegate.submit(command, on_goal_event=on_goal_event)

    def cancel_goal(self, driver_goal_id):
        return self.delegate.cancel_goal(driver_goal_id)


class StagingTransport:
    """Stage once for an already issued Fleet grant; lost replies never cause replay."""

    def __init__(self, delegate, *, observer, stage, directory, box, clock=None):
        self.delegate, self.observer, self.stage = delegate, observer, stage
        self.directory, self.box = Path(directory), box
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.Lock()
        self.attempted = set()

    def submit(self, grant):
        from core_common.protocol.schemas import FleetCellTransferGrant
        if not isinstance(grant, FleetCellTransferGrant) or grant.cell_transfer.item != "box":
            raise ValueError("G2 stages only typed Fleet-issued box grants")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", grant.action_id):
            raise ValueError("unsafe model identity")
        intent = self.directory / (grant.action_id + ".intent.json")
        with self.lock:
            if (grant.action_id in self.attempted
                    or intent.exists() or (self.directory / (grant.action_id + ".json")).exists()):
                raise RuntimeError("staged attempt may not be submitted again; reconcile only")
            if self.clock() >= grant.expires_at:
                raise RuntimeError("grant already expired; no staging or UDS submit")
            # Durable before the first world mutation: a crash/lost response cannot stage again.
            write_json(intent, {"grant": grant.model_dump(mode="json"), "sim_aid": True,
                                "state": "STAGING_INTENT_NO_REPLAY"})
            self.attempted.add(grant.action_id)
        model = "cell_" + grant.action_id
        offset = self.box["grasp_depth"] - self.box["height"] / 2
        pick = grant.cell_transfer.pick
        if self.stage(model, (pick.x, pick.y, pick.z + offset), pick.yaw,
                      (self.box["length"], self.box["width"], self.box["height"]),
                      self.box["mass_kg"]).get("ok") is not True:
            raise RuntimeError("SIM staging uncertain; no UDS submit or replacement")
        observed = self.observer(model, require_open=False)
        if observed["observed_at"] < grant.issued_at.timestamp():
            raise RuntimeError("initial observation predates issued grant")
        if self.clock() >= grant.expires_at:
            raise RuntimeError("grant expired during staging; never renew or mint it")
        write_json(self.directory / (grant.action_id + ".json"), {
            "grant": grant.model_dump(mode="json"), "initial": observed,
            "sim_aid": True, "sim_gripper_sensor": True,
        })
        return self.delegate.submit(grant)

    def get(self, grant):
        return self.delegate.get(grant)

    def cancel(self, grant, *, reason):
        return self.delegate.cancel(grant, reason=reason)

    def owner_identity(self, instance_id):
        return self.delegate.owner_identity(instance_id)


class ObserverClient:
    def __init__(self, path):
        self.path = str(path)

    def __call__(self, model, *, require_open):
        import time
        deadline = time.monotonic()+2
        while True:
            result = self._read(model, require_open=require_open)
            if result.get("ok") is True:
                return result["observation"]
            if time.monotonic() >= deadline:
                raise RuntimeError("independent measurement refused: "+str(result.get("error")))
            time.sleep(0.05)

    def _read(self, model, *, require_open):
        import socket
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            connection.connect(self.path)
            connection.sendall(json.dumps({"model": model, "require_open": require_open}).encode()+b"\n")
            with connection.makefile("rb") as stream:
                raw = stream.readline(65537)
            if len(raw) > 65536:
                raise RuntimeError("independent observation exceeds bounded frame")
        result = json.loads(raw)
        return result


def isolation_guard(repo):
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("G2 requires localhost-only discovery")
    if any(path.name != "lo" for path in Path("/sys/class/net").iterdir()):
        raise RuntimeError("G2 requires network-none isolation")
    if Path("/dev/serial/by-id").exists() or any(
            list(Path("/dev").glob(pattern)) for pattern in ("video*", "ttyACM*", "ttyUSB*", "ttyS*")):
        raise RuntimeError("G2 refuses hardware grants")
    import subprocess
    flags = subprocess.run(["findmnt", "-n", "-o", "OPTIONS", "--target", str(repo)],
                           check=True, capture_output=True, text=True, timeout=5).stdout.strip().split(",")
    if "ro" not in flags:
        raise RuntimeError("G2 candidate source must be mounted read-only")
    root_flags = subprocess.run(["findmnt", "-n", "-o", "OPTIONS", "--target", "/"],
                                check=True, capture_output=True, text=True, timeout=5).stdout.strip().split(",")
    if "ro" not in root_flags:
        raise RuntimeError("G2 container root must be read-only")


def refuse_g2_owner(proc_root="/proc"):
    for proc in Path(proc_root).iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        names = [Path(arg.decode(errors="ignore")).name for arg in argv[1:] if arg]
        if argv and b"python" in argv[0] and "g2_owner.py" in names:
            raise RuntimeError("another G2 canonical owner already exists")
