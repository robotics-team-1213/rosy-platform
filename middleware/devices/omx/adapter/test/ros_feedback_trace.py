"""Failure-only diagnostics for the hardware-free owner scheduling regression."""
from collections import deque
import faulthandler
import hashlib
from importlib.metadata import PackageNotFoundError, version
import inspect
import tempfile
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor


class OwnerProgressTrace:
    def __init__(self, runtime):
        self.runtime = runtime
        self.events = {name: deque(maxlen=64) for name in ("poll", "intake", "cancel")}
        self.stack_file = tempfile.TemporaryFile(mode="w+b")
        self.poll = runtime.owner.poll
        self.snapshot = runtime._joint_state_intake.snapshot
        self.send_goal = runtime.action_port.send_goal
        runtime.owner.poll = self._poll
        runtime._joint_state_intake.snapshot = self._snapshot
        runtime.action_port.send_goal = self._send_goal

    def _poll(self):
        self.events["poll"].append(("enter", time.monotonic()))
        try:
            return self.poll()
        finally:
            self.events["poll"].append(("exit", time.monotonic()))

    def _snapshot(self, *args, **kwargs):
        age = (kwargs["source_now_ns"] - kwargs["stamp_ns"]) / 1e9
        self.events["intake"].append(("enter", time.monotonic(), age))
        try:
            state = self.snapshot(*args, **kwargs)
        except Exception as exc:
            self.events["intake"].append((type(exc).__name__, time.monotonic()))
            raise
        self.events["intake"].append(("accepted", time.monotonic(), state.sequence))
        return state

    def _send_goal(self, command):
        handle = self.send_goal(command)
        cancel = handle.cancel

        def observed_cancel():
            self.events["cancel"].append(("enter", time.monotonic()))
            try:
                return cancel()
            finally:
                self.events["cancel"].append(("exit", time.monotonic()))

        handle.cancel = observed_cancel
        return handle

    def arm(self):
        # Capture during timeout, before a delayed assertion can observe recovery.
        faulthandler.dump_traceback_later(1.3, file=self.stack_file)

    def dump(self):
        faulthandler.cancel_dump_traceback_later()
        source = inspect.getsource(MultiThreadedExecutor._spin_once_impl)
        print("installed rclpy:", rclpy.__file__)
        try:
            print("rclpy distribution version:", version("rclpy"))
        except PackageNotFoundError:
            print("rclpy distribution version: no Python package metadata")
        print("MTE implementation SHA-256:", hashlib.sha256(source.encode()).hexdigest())
        print(source)
        for name, events in self.events.items():
            print(name, list(events))
        self.stack_file.seek(0)
        print("timed thread stacks:", self.stack_file.read().decode("utf-8", errors="replace"))
        faulthandler.dump_traceback()

    def close(self):
        faulthandler.cancel_dump_traceback_later()
        self.runtime.owner.poll = self.poll
        self.runtime._joint_state_intake.snapshot = self.snapshot
        self.runtime.action_port.send_goal = self.send_goal
        self.stack_file.close()
