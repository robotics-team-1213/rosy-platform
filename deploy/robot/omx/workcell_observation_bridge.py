"""Native local observations to authenticated Fleet and Vision ingress.

Single Responsibility:
  - Authenticated Fleet HTTPS & Vision WSS delivery workers (`post_arm`, `ArmSender`, `CameraSender`, `SourceWorker`, `main`).
  - Local observation sample buffers and ROS decoders live in `workcell_observation_sources.py` and are re-exported.
  - Incident & USB camera HTTP clients live in `workcell_incident_client.py` and are re-exported.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import signal
import ssl
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener
from uuid import uuid4

import yaml

from core_common.motor_health import read_motor_health_snapshot  # noqa: F401
from core_common.observation_snapshot import SnapshotChannel, interrupt_on_termination  # noqa: F401
from core_common.protocol.arm_incidents import ArmIncidentAccepted, ArmIncidentHold  # noqa: F401
from core_common.protocol.motor_health import MotorHealthResponse  # noqa: F401
from core_common.protocol.workcell_observations import (  # noqa: F401
    ArmObservation,
    UsbCameraDecisions,
    WorkcellObservationManifest,
)
from rosy_vision import protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_report_bridge import _NoRedirect  # noqa: E402
import usb_camera_report  # noqa: E402,F401
from workcell_incident_client import (  # noqa: E402,F401
    ArmIncidentLink,
    _arm_url,
    _verified,
    clear_arm_incident,
    get_arm_hold,
    post_arm_incident,
    post_arm_incident_evidence,
    post_usb_devices,
    post_workcell,
    run_usb_reports,
    secure_url,
)
from workcell_observation_sources import (  # noqa: E402,F401
    ArmHealthSource,
    LatestSource,
    NativeSource,
    Sample,
    _REGISTER_WOB_GLOBALS,
    encode_image,
    joint_values,
    sample_age,
    select_sources,
    source_stamp,
)
_REGISTER_WOB_GLOBALS(globals())


_DEFAULT_BUILD_OPENER = build_opener
_ARM_CONNECTIONS: dict = {}
_ARM_CONN_LOCK = threading.Lock()


def post_arm(fleet_url, source_id, token, observation, *, context):
    base = secure_url(fleet_url, "https")
    path = "/api/fleet/workcell-observations/arms/" + quote(source_id, safe="")
    url = base + path
    verified = _verified(context)
    payload = observation.model_dump_json().encode()
    headers = {
        "Content-Type": "application/json",
        "X-Workcell-Observation-Token": token,
        "Connection": "keep-alive",
    }
    if build_opener is not _DEFAULT_BUILD_OPENER:
        request = Request(url, data=payload, method="POST", headers=headers)
        opener = build_opener(HTTPSHandler(context=verified), _NoRedirect())
        with opener.open(request, timeout=2) as response:
            if response.status != 202:
                raise OSError("observation was not accepted")
        return
    import http.client
    import socket as _socket

    parsed = urlsplit(base)
    key = (parsed.hostname, parsed.port or 443, id(verified))
    for attempt in range(2):
        with _ARM_CONN_LOCK:
            conn = _ARM_CONNECTIONS.pop(key, None)
        try:
            if conn is None:
                conn = http.client.HTTPSConnection(key[0], key[1], context=verified, timeout=2)
                conn.connect()
                if conn.sock is not None:
                    conn.sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
            conn.request("POST", path, body=payload, headers=headers)
            response = conn.getresponse()
            response.read()
            status, reason, resp_headers = response.status, response.reason, response.headers
            with _ARM_CONN_LOCK:
                _ARM_CONNECTIONS[key] = conn
            if 400 <= status < 600:
                raise HTTPError(url, status, reason, resp_headers, None)
            if status != 202:
                raise OSError("observation was not accepted")
            return
        except HTTPError:
            raise
        except (OSError, http.client.HTTPException):
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            if attempt == 1:
                raise


class ArmSender:
    def __init__(self, fleet_url, source_id, token, *, context):
        self.url, self.source_id, self.token = secure_url(fleet_url, "https"), source_id, token
        self.context = _verified(context)
        self.epoch, self.sequence, self.conflict_stamp = uuid4().hex, 0, None

    def send(self, sample):
        if self.conflict_stamp is not None:
            if sample.captured_at <= self.conflict_stamp:
                raise ValueError("conflict recovery requires a newer capture")
            self.epoch, self.sequence, self.conflict_stamp = uuid4().hex, 0, None
        observation = ArmObservation(
            epoch=self.epoch,
            sequence=self.sequence + 1,
            captured_at=sample.captured_at,
            positions=sample.value,
            motor_health=sample.motor_health,
        )
        try:
            post_arm(self.url, self.source_id, self.token, observation, context=self.context)
        except HTTPError as error:
            if error.code == 409:
                self.conflict_stamp = sample.captured_at
            raise
        self.sequence += 1


def camera_hello(source_id, width, height):
    message = {
        "type": "hello",
        "proto": protocol.PROTO,
        "source": source_id,
        "sensor": {"width": width, "height": height, "rotation_deg": 0},
    }
    protocol.validate_hello(message)
    return message


def camera_packet(sample, *, wall=None, monotonic=None):
    age = sample_age(
        sample,
        time.time() if wall is None else wall,
        time.monotonic() if monotonic is None else monotonic,
    )
    jpeg, width, height = sample.value
    if not isinstance(jpeg, bytes) or not jpeg or len(jpeg) > protocol.DEFAULT_CONFIG["max_bytes"]:
        raise ValueError("invalid or oversized camera JPEG")
    return protocol.pack_header(protocol.FrameHeader(sample.sequence, math.ceil(age * 1000), width, height, 0)) + jpeg


class CameraSender:
    def __init__(self, vision_url, source_id, token, *, context):
        self.url = secure_url(vision_url, "wss")
        if urlsplit(self.url).path in ("", "/"):
            self.url += protocol.WS_PATH
        self.source_id, self.token, self.context = source_id, token, _verified(context)
        self.connection = None

    def close(self):
        if self.connection is not None:
            connection, self.connection = self.connection, None
            try:
                connection.close()
            except Exception:
                pass

    def send(self, sample):
        from websockets.sync.client import connect

        try:
            if self.connection is None:
                self.connection = connect(
                    self.url,
                    ssl=self.context,
                    compression=None,
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    open_timeout=2,
                    close_timeout=1,
                    max_queue=1,
                    max_size=65536,
                )
                self.connection.socket.settimeout(2)
                try:
                    import socket as _socket

                    self.connection.socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
                except (AttributeError, OSError):
                    pass
                self.connection.send(json.dumps(camera_hello(self.source_id, sample.value[1], sample.value[2])))
            for _ in range(8):
                try:
                    self.connection.recv(timeout=0)
                except TimeoutError:
                    break
            self.connection.send(camera_packet(sample))
        except Exception:
            self.close()
            raise


class SourceWorker:
    def __init__(self, source, send):
        self.source, self.send = source, send

    def run(self, stop):
        last, backoff = 0, 0.1
        while not stop.is_set():
            sample = self.source.latest()
            if sample is None or sample.sequence == last:
                stop.wait(0.02)
                continue
            try:
                self.send(sample)
                last, backoff = sample.sequence, 0.1
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "observation delivery failed source=%s error=%s",
                    threading.current_thread().name,
                    type(error).__name__,
                )
                if stop.wait(backoff):
                    return
                backoff = min(5, backoff * 2)


def main(argv=None):
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workcell", required=True)
    parser.add_argument("--fleet-url", required=True)
    parser.add_argument("--vision-url", required=True)
    parser.add_argument("--domain-id", type=int, help="unused legacy registration value; no DDS is started")
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument(
        "--arm-health-file",
        action="append",
        metavar="SOURCE_ID=/absolute/file",
        default=os.environ.get("ROSY_OBSERVATION_ARM_HEALTH", "").split(),
        help="private trusted health file for a registered arm; owner derives from its arm_id",
    )
    args = parser.parse_args(argv)
    try:
        manifest = WorkcellObservationManifest.model_validate(
            yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
        )
        cell, tokens = select_sources(manifest, args.workcell, os.environ)
        health_files = {}
        for binding in args.arm_health_file:
            source, separator, file = binding.partition("=")
            path = Path(file)
            if (
                not separator
                or source not in {arm.source_id for arm in cell.arms}
                or source in health_files
                or not path.is_absolute()
                or path.resolve() != path
                or path.is_symlink()
            ):
                raise ValueError("health file must be bound once to a registered source and canonical path")
            health_files[source] = path
        secure_url(args.fleet_url, "https")
        secure_url(args.vision_url, "wss")
        context = ssl.create_default_context(cafile=args.ca_file)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(f"observation configuration invalid: {type(error).__name__}")
    stop, workers, senders = threading.Event(), [], []
    previous = signal.signal(signal.SIGTERM, interrupt_on_termination)

    def deliver(source, buffer, sender, *, health_file=None):
        delivery = ArmHealthSource(buffer, health_file, source.arm_id) if health_file is not None else buffer
        worker = threading.Thread(
            target=SourceWorker(delivery, sender.send).run, args=(stop,), name=source.source_id, daemon=True
        )
        worker.start()
        workers.append(worker)
        senders.append(sender)

    try:
        for arm in cell.arms:
            deliver(
                arm,
                NativeSource(arm.joint_topic, joint_names=arm.joint_names),
                ArmSender(args.fleet_url, arm.source_id, tokens[arm.source_id], context=context),
                health_file=health_files.get(arm.source_id),
            )
        for camera in cell.cameras:
            deliver(
                camera,
                NativeSource(camera.image_topic),
                CameraSender(args.vision_url, camera.source_id, tokens[camera.source_id], context=context),
            )
        workers.append(
            threading.Thread(
                target=run_usb_reports,
                name="usb-cameras",
                daemon=True,
                args=(
                    stop,
                    lambda report: post_usb_devices(
                        args.fleet_url,
                        cell.workcell_id,
                        tokens[cell.arms[0].source_id],
                        report,
                        context=context,
                    ),
                    cell.workcell_id,
                ),
            )
        )
        workers[-1].start()
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        stop.set()
        for sender in senders:
            if isinstance(sender, CameraSender):
                sender.close()
        for worker in workers:
            worker.join(timeout=3)


if __name__ == "__main__":
    main()
