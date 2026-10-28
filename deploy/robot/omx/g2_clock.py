"""SDK-pinned SIM-only clock composition; no owner authority or freshness policy."""
import hashlib
import importlib
import math
from pathlib import Path
import threading
import time
from types import SimpleNamespace

SDK_PINS = {
    "rclpy.node": "8b7fe0ea64e0de12cc1d5d01ebf56c202fa6e153251eb71dfff93e35eb5b3c80",
    "rclpy.time_source": "9aacb85102019116edc6eb74a6993ca7efa3296273bfa53c30cebbb792d446f5",
    "rclpy.clock": "ff541d1386ab52115ba23413eb0a9b3ca6773d15e06129a53ca3b657c4f934f6",
}
LIMIT = 2**63 - 1


def verify_sdk_sources():
    """Bind private handoff semantics to the actual imported installed source files."""
    result = {}
    try:
        for name, expected in SDK_PINS.items():
            path = Path(importlib.import_module(name).__file__).resolve(strict=True)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError("unsupported source")
            result[name] = {"origin": str(path), "sha256": actual}
    except (OSError, TypeError, ValueError, AttributeError) as error:
        raise RuntimeError("CLOCK_SDK_UNSUPPORTED") from error
    return result


def _load_sdk():
    from rclpy.node import Node
    from rclpy.time_source import TimeSource
    from rclpy.parameter import Parameter
    from rclpy.executors import SingleThreadedExecutor
    from rcl_interfaces.msg import ParameterDescriptor
    return SimpleNamespace(Node=Node, TimeSource=TimeSource, Parameter=Parameter,
        SingleThreadedExecutor=SingleThreadedExecutor, ParameterDescriptor=ParameterDescriptor)


def _write_record(path, record):
    from g2_ports import write_json
    write_json(path, record)


def _old_source(node):
    source = getattr(node, "_time_source", None)
    try:
        if (source._node_weak_ref() is not node or source._clock_sub is None
                or type(source._associated_clocks) is not set
                or source._associated_clocks != {node.get_clock()}
                or node.get_parameter("use_sim_time").value is not True):
            raise ValueError("unexpected automatic source")
        for method in (source.detach_node, node.remove_on_set_parameters_callback,
                       node.set_descriptor, node.describe_parameter):
            if not callable(method):
                raise ValueError("missing public API")
    except (AttributeError, TypeError, ValueError) as error:
        raise RuntimeError("CLOCK_SDK_UNSUPPORTED") from error
    return source


def _retire(node, source):
    source.detach_node()
    node.remove_on_set_parameters_callback(source._on_parameter_event)
    # Jazzy detach_node leaves clocks and parameter callback attached. A queued old
    # callback must have no clocks left to mutate, even after its subscription dies.
    source._associated_clocks.clear()


def _text(value):
    if type(value) is not str or len(value) > 128:
        raise ValueError("unsupported graph field")
    return value


def _publisher(info):
    gid = bytes(info.endpoint_gid)
    if not 1 <= len(gid) <= 32 or info.topic_type != "rosgraph_msgs/msg/Clock":
        raise ValueError("unsupported clock publisher")
    qos = info.qos_profile
    if type(qos.depth) is not int or not 0 <= qos.depth <= 10000:
        raise ValueError("unsupported QoS")
    return {"node_name": _text(info.node_name), "namespace": _text(info.node_namespace),
        "topic_type": info.topic_type, "gid": gid.hex(), "qos": {"depth": qos.depth,
        **{key: _text(getattr(qos, key).name) for key in ("reliability", "durability", "history")}}}


class DedicatedSimClock:
    """One clock subscription/executor; shared ROSClock, unchanged TimeSource delivery."""

    def __init__(self, owner):
        self.sdk = verify_sdk_sources()
        sdk = _load_sdk()
        old_owner = _old_source(owner)
        self.owner = owner
        self.node = sdk.Node("rosy_g2_sim_clock", parameter_overrides=[
            sdk.Parameter("use_sim_time", value=True)])
        self.thread = None
        self.executor = None
        self.source = None
        self.closed = False
        self.telemetry = {"count": 0, "advance_count": 0, "backward_count": 0,
                          "telemetry_error_count": 0, "last_stamp_ns": None,
                          "last_received_steady": None, "min_delta_ns": None, "max_delta_ns": None}
        try:
            old_clock = _old_source(self.node)
            # Validate both automatic sources before either relinquishes ownership.
            _retire(owner, old_owner)
            _retire(self.node, old_clock)
            observer = self

            class ObservedSource(sdk.TimeSource):
                def clock_callback(self, message):
                    try:
                        observer._observe(message)
                    except Exception:
                        observer.telemetry["telemetry_error_count"] = min(
                            LIMIT, observer.telemetry["telemetry_error_count"] + 1)
                    # Exactly once, including backwards frames and diagnostic failures.
                    super().clock_callback(message)

            self.source = ObservedSource(node=self.node)
            self.source.attach_clock(owner.get_clock())
            self.source.attach_clock(self.node.get_clock())
            for node in (owner, self.node):
                node.set_descriptor("use_sim_time", sdk.ParameterDescriptor(
                    type=sdk.Parameter.Type.BOOL.value, read_only=True))
                if not node.describe_parameter("use_sim_time").read_only:
                    raise RuntimeError("CLOCK_SDK_UNSUPPORTED")
            self.executor = sdk.SingleThreadedExecutor()
            self.executor.add_node(self.node)
            self.thread = threading.Thread(target=self.executor.spin, name="g2-sim-clock", daemon=True)
        except Exception:
            self.close(timeout=.2)
            raise

    def _observe(self, message):
        stamp = message.clock.sec * 10**9 + message.clock.nanosec
        if type(stamp) is not int or not -LIMIT <= stamp <= LIMIT:
            raise ValueError("invalid telemetry stamp")
        values = self.telemetry
        previous = values["last_stamp_ns"]
        values["count"] = min(LIMIT, values["count"] + 1)
        if previous is not None:
            delta = max(-LIMIT, min(LIMIT, stamp - previous))
            key = "backward_count" if delta < 0 else "advance_count" if delta > 0 else None
            if key:
                values[key] = min(LIMIT, values[key] + 1)
            values["min_delta_ns"] = delta if values["min_delta_ns"] is None else min(delta, values["min_delta_ns"])
            values["max_delta_ns"] = delta if values["max_delta_ns"] is None else max(delta, values["max_delta_ns"])
        values["last_stamp_ns"] = stamp
        values["last_received_steady"] = time.monotonic()

    def snapshot(self):
        """Non-atomic diagnostic view; graph queries and callers' disk I/O stay off callback."""
        telemetry = dict(self.telemetry)
        age = None if telemetry["last_received_steady"] is None else time.monotonic() - telemetry["last_received_steady"]
        graph_error = None
        publishers = []
        try:
            raw = self.node.get_publishers_info_by_topic("/clock")
            if len(raw) != 1:
                raise ValueError("publisher count")
            publishers = [_publisher(raw[0])]
        except Exception:
            graph_error = "CLOCK_GRAPH_UNSUPPORTED"
        frozen = all(node.get_parameter("use_sim_time").value is True
                     and node.describe_parameter("use_sim_time").read_only for node in (self.owner, self.node))
        alive = self.thread is not None and self.thread.is_alive()
        return {"schema": "rosy.omx-g2-dedicated-clock/1", "sdk": self.sdk,
            "snapshot": "NONATOMIC_OBSERVATION", "scheduling_experiment": True,
            "publishers": publishers, "graph_error": graph_error, "telemetry": telemetry,
            "receipt_age_s": age, "thread_alive": alive, "parameters_frozen_true": frozen,
            "ready": bool(not graph_error and alive and frozen and telemetry["advance_count"] > 0
                          and age is not None and math.isfinite(age) and 0 <= age <= .5)}

    def start(self, *, timeout=10):
        if self.closed or self.thread is None or self.thread.ident is not None:
            raise RuntimeError("CLOCK_NOT_READY")
        self.thread.start()
        deadline = time.monotonic() + min(30., max(0., timeout))
        while True:
            record = self.snapshot()
            if record["ready"]:
                return record
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("CLOCK_NOT_READY")
            time.sleep(.01)

    def persist_terminal(self, path, *, timeout=.5):
        """Best effort diagnostic I/O cannot prolong owner/clock cleanup."""
        saved = threading.Event()
        def save():
            try:
                _write_record(path, self.snapshot())
                saved.set()
            except Exception:
                pass
        worker = threading.Thread(target=save, name="g2-clock-record", daemon=True)
        worker.start()
        worker.join(max(0., min(1., timeout)))
        return saved.is_set()

    def close(self, *, timeout=2):
        if self.closed:
            return True
        deadline = time.monotonic() + max(0., min(5., timeout))
        stopped = True
        if self.executor is not None:
            stopped = self.executor.shutdown(timeout_sec=max(0., deadline - time.monotonic())) is True
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(max(0., deadline - time.monotonic()))
        if not stopped or (self.thread is not None and self.thread.is_alive()):
            return False
        if self.source is not None:
            _retire(self.node, self.source)
        self.node.destroy_node()
        self.closed = True
        return True
