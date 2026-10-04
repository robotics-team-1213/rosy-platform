"""Gazebo-side helpers for probe_cell_transfer.py (Rosy Cell C3/C3b, simulation only).

``SimAid`` drives the labelled DetachableJoint SIM AID described in
integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf, and ``spawn_infeed_block`` stages the
next block. They exist only in this simulation probe path; no production module imports them.

C3b: the aid joint is added to omx_f at runtime (parent omx_f::link5, child the block) by
the world's entity/system/add service, and only when the gripper readback has proved a
hold. In C3 the plugin lived in the block (block = parent of link5, attached from load):
the weld then fought the finger contact, tilted the block 0.05-0.15 rad and threw the
fingers past their limits (C3 run16, C3b run3).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import time
from pathlib import Path

WORLD = "omx_cell_workcell"


_ARM_OWNERS = ("pilot_sim_server", "probe_cell_transfer", "run_cell_owner")


def refuse_second_owner(proc_root: Path | str = "/proc") -> None:
    """Refuse to start next to another /arm_controller writer (D-390 §3, D-403 §8)."""
    mine = {os.getpid(), os.getppid()}
    for proc in Path(proc_root).iterdir():
        if not proc.name.isdigit() or int(proc.name) in mine:
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        cmd = b" ".join(argv).decode(errors="ignore")
        if b"python" in argv[0] and any(owner in cmd for owner in _ARM_OWNERS):
            raise RuntimeError(f"another arm owner process is running (pid {proc.name}): {cmd[:80]}")


def model_pose(name: str, attempts: int = 5) -> dict:
    # `gz model -p` sometimes prints nothing under load (its service request times out); retry.
    for _ in range(attempts):
        out = subprocess.run(["gz", "model", "-m", name, "-p"], capture_output=True, text=True,
                             timeout=60).stdout
        triples = [g.split() for g in re.findall(r"\[([^\]]+)\]", out)]
        triples = [[float(v) for v in t] for t in triples if len(t) == 3]
        if len(triples) >= 2:
            break
        time.sleep(1.0)
    else:
        raise RuntimeError(f"gz model pose for {name} not found after {attempts} attempts")
    (x, y, z), (roll, pitch, yaw) = triples[-2], triples[-1]
    return {"x": x, "y": y, "z": z, "roll": roll, "pitch": pitch, "yaw": yaw}


class SimAid:
    """The labelled DetachableJoint SIM AID: parent omx_f::link5, child <block>::block.

    One gz-transport node lives for the whole probe and watches each block's state topic
    from before its attach: the plugin echoes "attached" only once, and a node created at
    attach time missed it (C3b run13/run14: the joint was attached, the echo was lost).
    """

    def __init__(self) -> None:
        from gz.transport13 import Node as GzNode

        self._node = GzNode()
        self._states: dict[str, list[str]] = {}
        self._publishers: dict[str, object] = {}

    def watch(self, model: str) -> None:
        from gz.msgs10.empty_pb2 import Empty
        from gz.msgs10.stringmsg_pb2 import StringMsg

        if model in self._states:
            return
        states: list[str] = []
        self._states[model] = states
        self._node.subscribe(StringMsg, f"/c3_sim_aid/{model}/state", lambda msg: states.append(msg.data))
        self._publishers[model] = self._node.advertise(f"/c3_sim_aid/{model}/detach", Empty)

    def _robot_entity_id(self, attempts: int = 5) -> int:
        # `gz model` sometimes prints nothing under load (as for model_pose); retry, then cache.
        if getattr(self, "_robot_id", None) is None:
            for _ in range(attempts):
                described = subprocess.run(["gz", "model", "-m", "omx_f"], capture_output=True, text=True,
                                           timeout=60).stdout
                found = re.search(r"Model: \[(\d+)\]", described)
                if found:
                    self._robot_id = int(found.group(1))
                    break
                time.sleep(1.0)
            else:
                raise RuntimeError("omx_f entity id not found")
        return self._robot_id

    def _wait(self, model: str, want: str, limit_s: float) -> bool:
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if self._states[model] and self._states[model][-1] == want:
                return True
            time.sleep(0.1)
        return False

    def attach(self, model: str) -> dict:
        """Add the joint to omx_f through entity/system/add; the plugin attaches on load."""
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.entity_pb2 import Entity
        from gz.msgs10.entity_plugin_v_pb2 import EntityPlugin_V

        self.watch(model)
        # The service needs the model's entity id; a name alone fails ("should be attached to
        # a model entity", C3b run4-run8).
        request = EntityPlugin_V()
        request.entity.id = self._robot_entity_id()
        request.entity.name = "omx_f"
        request.entity.type = Entity.MODEL
        plugin = request.plugins.add()
        plugin.name = "gz::sim::systems::DetachableJoint"
        plugin.filename = "gz-sim-detachable-joint-system"
        plugin.innerxml = (
            f"<parent_link>link5</parent_link><child_model>{model}</child_model><child_link>block</child_link>"
            f"<attach_topic>/c3_sim_aid/{model}/attach</attach_topic>"
            f"<detach_topic>/c3_sim_aid/{model}/detach</detach_topic>"
            f"<output_topic>/c3_sim_aid/{model}/state</output_topic>")
        sent = time.time()
        ok, response = self._node.request(f"/world/{WORLD}/entity/system/add", request, EntityPlugin_V,
                                          Boolean, 10000)
        confirmed = self._wait(model, "attached", 5.0)
        retried = None
        if not confirmed:
            # The load-time "attached" echo is sometimes lost (C3b run17). Re-command it with
            # echoes: detach (the block still sits on the table in the closed fingers), attach.
            retried = self.detach(model)
            from gz.msgs10.empty_pb2 import Empty

            publisher = self._node.advertise(f"/c3_sim_aid/{model}/attach", Empty)
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline and not confirmed:
                publisher.publish(Empty())
                confirmed = self._wait(model, "attached", 0.5)
        return {"model": model, "command": "attach (entity/system/add on omx_f)", "sent_wall": sent,
                "service_ok": bool(ok and response.data), "state_echo": (self._states[model] or [None])[-1],
                "confirmed": confirmed, "re_commanded_after": retried}

    def detach(self, model: str) -> dict:
        """Publish detach until the state echoes (one publish was lost in C3 run15)."""
        from gz.msgs10.empty_pb2 import Empty

        self.watch(model)
        publisher = self._publishers[model]
        sent = time.time()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not (self._states[model] and self._states[model][-1] == "detached"):
            publisher.publish(Empty())
            time.sleep(0.5)
        return {"model": model, "command": "detach", "sent_wall": sent,
                "state_echo": (self._states[model] or [None])[-1],
                "confirmed": bool(self._states[model]) and self._states[model][-1] == "detached"}


def block_sdf(model: str, size: tuple[float, float, float], mass: float) -> str:
    """The world's infeed block (same geometry and friction); the aid is added at runtime."""
    a, b, c = size
    ixx, iyy, izz = (mass / 12 * (b * b + c * c), mass / 12 * (a * a + c * c), mass / 12 * (a * a + b * b))
    return f"""<sdf version="1.9"><model name="{model}"><link name="block">
      <inertial><mass>{mass}</mass><inertia><ixx>{ixx:.3e}</ixx><iyy>{iyy:.3e}</iyy>
      <izz>{izz:.3e}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
      <collision name="collision"><geometry><box><size>{a} {b} {c}</size></box></geometry>
        <surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>
      <visual name="visual"><geometry><box><size>{a} {b} {c}</size></box></geometry>
        <material><diffuse>0.9 0.35 0.2 1</diffuse></material></visual>
      </link></model></sdf>"""


def spawn_infeed_block(model: str, xyz: tuple[float, float, float], yaw: float, size, mass: float) -> dict:
    """Stage the next block at the infeed for a repeat transfer (sim staging, not motion)."""
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.entity_factory_pb2 import EntityFactory
    from gz.transport13 import Node as GzNode

    request = EntityFactory()
    request.sdf = block_sdf(model, size, mass)
    request.name = model
    request.pose.position.x, request.pose.position.y, request.pose.position.z = xyz
    request.pose.orientation.z, request.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
    ok, response = GzNode().request(f"/world/{WORLD}/create", request, EntityFactory, Boolean, 10000)
    return {"model": model, "xyz": list(xyz), "yaw": yaw, "ok": bool(ok and response.data)}


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
