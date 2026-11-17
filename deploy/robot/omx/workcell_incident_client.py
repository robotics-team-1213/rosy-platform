"""Authenticated Fleet REST client for workcell USB device reports, arm incidents, holds, and intake readings."""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import logging
from pathlib import Path
import ssl
import sys
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

import yaml

from core_common.protocol.arm_incidents import ArmIncidentAccepted, ArmIncidentHold
from core_common.protocol.workcell_observations import UsbCameraDecisions, WorkcellObservationManifest
from load_report_bridge import _NoRedirect
from rosy_vision import protocol
import usb_camera_report


def secure_url(value, scheme):
    url = urlsplit(value)
    if (
        any(char.isspace() or ord(char) < 32 for char in value)
        or url.scheme != scheme
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or (scheme == "https" and url.path not in ("", "/"))
        or (scheme == "wss" and url.path not in ("", "/", protocol.WS_PATH))
    ):
        raise ValueError("explicit HTTPS Fleet origin and WSS Vision ingress are required")
    url.port
    return value.rstrip("/")


def _verified(context):
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("verified TLS is required")
    return context


def _resolve_opener(opener_fn=None):
    if opener_fn is not None:
        return opener_fn
    bridge_mod = sys.modules.get("workcell_observation_bridge")
    if bridge_mod is not None and hasattr(bridge_mod, "build_opener"):
        return bridge_mod.build_opener
    return build_opener


def post_usb_devices(fleet_url, workcell_id, token, report, *, context, opener_fn=None):
    """D-963: the unregistered-camera report; the reply carries the operator's role decisions."""
    url = secure_url(fleet_url, "https") + "/api/fleet/workcell-observations/" + quote(workcell_id, safe="") + "/usb-devices"
    request = Request(
        url,
        data=report.model_dump_json().encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Workcell-Observation-Token": token},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=2) as response:
        if response.status != 200:
            raise OSError("usb camera report was not accepted")
        return UsbCameraDecisions.model_validate_json(response.read(16385))


def _arm_url(fleet_url, source_id):
    return secure_url(fleet_url, "https") + "/api/fleet/workcell-observations/arms/" + quote(source_id, safe="")


def post_arm_incident(fleet_url, source_id, token, report, *, context, opener_fn=None):
    """D-971: one ended session's incident (facts and up to two frames); the reply carries the arm's hold."""
    request = Request(
        _arm_url(fleet_url, source_id) + "/incidents",
        data=report.model_dump_json().encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Workcell-Observation-Token": token},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise OSError("arm incident was not accepted")
        return ArmIncidentAccepted.model_validate_json(response.read(16385))


def post_arm_incident_evidence(fleet_url, source_id, token, incident_id, frame, *, context, opener_fn=None):
    """One frame of the seconds around the stop, after the report and on its own (each within the frame limit)."""
    request = Request(
        _arm_url(fleet_url, source_id) + f"/incidents/{incident_id}/evidence",
        data=frame.model_dump_json().encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Workcell-Observation-Token": token},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise OSError("arm incident evidence was not accepted")


def get_arm_hold(fleet_url, source_id, token, *, context, opener_fn=None):
    """D-971: whether Fleet holds this arm (an incident not cleared by a person)."""
    request = Request(
        _arm_url(fleet_url, source_id) + "/hold",
        method="GET",
        headers={"X-Workcell-Observation-Token": token},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=3) as response:
        if response.status != 200:
            raise OSError("arm hold was not answered")
        return ArmIncidentHold.model_validate_json(response.read(16385))


def post_workcell(fleet_url, workcell_id, token, tail, body, *, context, opener_fn=None):
    """D-996: one intake reading (tail 'intake-readings') or port event ('port-events') of this workcell; a resend of
    the same body is the same ledger row."""
    url = secure_url(fleet_url, "https") + "/api/fleet/workcell-observations/" + quote(workcell_id, safe="") + "/" + tail
    request = Request(
        url,
        data=body.model_dump_json().encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Workcell-Observation-Token": token},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise OSError(tail + " was not accepted")
        return json.loads(response.read(4097))


def clear_arm_incident(
    fleet_url,
    source_id,
    operator_token,
    incident_id,
    note,
    *,
    context,
    cause=None,
    basis=None,
    opener_fn=None,
):
    """D-971: a named operator's clear over the API; the operator's own bearer, never the arm's source token."""
    payload = {"note": note, **({"cause": cause} if cause else {}), **({"basis": basis} if basis else {})}
    request = Request(
        _arm_url(fleet_url, source_id) + f'/incidents/{quote(incident_id, safe="")}/clear',
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + operator_token, "Content-Type": "application/json"},
    )
    opener = _resolve_opener(opener_fn)(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=5) as response:
        return ArmIncidentHold.model_validate_json(response.read(16385))


class ArmIncidentLink:
    """One arm's incident channel to Fleet, from the manifest and token variables the bridge already uses."""

    def __init__(self, fleet_url, source_id, token, *, context):
        self.fleet_url, self.source_id, self.token, self.context = (
            secure_url(fleet_url, "https"),
            source_id,
            token,
            context,
        )

    @classmethod
    def from_environment(cls, arm_id, environ):
        """None when this PC has no observation configuration; ValueError when it is wrong."""
        names = ("ROSY_WORKCELL_OBSERVATIONS", "ROSY_OBSERVATION_WORKCELL", "ROSY_OBSERVATION_FLEET_URL")
        if not all(environ.get(name) for name in names):
            return None
        manifest = WorkcellObservationManifest.model_validate(
            yaml.safe_load(Path(environ[names[0]]).read_text(encoding="utf-8"))
        )
        cell = next((c for c in manifest.workcells if c.workcell_id == environ[names[1]]), None)
        arm = (
            next((a for a in cell.arms if arm_id in (a.arm_id, a.source_id, a.arm_id.removesuffix("_follower"))), None)
            if cell
            else None
        )
        token = environ.get(arm.token_env) if arm else None
        if not token or not hmac.compare_digest(sha256(token.encode()).hexdigest(), arm.credential_sha256):
            raise ValueError("arm credential missing or fingerprint mismatch")
        link = cls(
            environ[names[2]],
            arm.source_id,
            token,
            context=ssl.create_default_context(cafile=environ.get("ROSY_OBSERVATION_CA_FILE") or None),
        )
        link.workcell_id = environ[names[1]]
        return link

    def post(self, report):
        return post_arm_incident(self.fleet_url, self.source_id, self.token, report, context=self.context)

    def post_intake_reading(self, reading):
        return post_workcell(
            self.fleet_url, self.workcell_id, self.token, "intake-readings", reading, context=self.context
        )

    def post_evidence(self, incident_id, frame):
        return post_arm_incident_evidence(
            self.fleet_url, self.source_id, self.token, incident_id, frame, context=self.context
        )

    def hold(self):
        return get_arm_hold(self.fleet_url, self.source_id, self.token, context=self.context)

    def clear(self, incident_id, note, operator_token, *, cause=None, basis=None):
        return clear_arm_incident(
            self.fleet_url,
            self.source_id,
            operator_token,
            incident_id,
            note,
            context=self.context,
            cause=cause,
            basis=basis,
        )


def run_usb_reports(stop, post, workcell_id, *, interval=20):
    """Independent of arm delivery: a Fleet or camera error here is logged and retried, never raised."""
    bridge_mod = sys.modules.get("workcell_observation_bridge")
    report_mod = getattr(bridge_mod, "usb_camera_report", usb_camera_report) if bridge_mod else usb_camera_report
    while True:
        try:
            report_mod.cycle(post, workcell_id)
        except Exception as error:
            logging.getLogger(__name__).warning("usb camera report failed error=%s", type(error).__name__)
        if stop.wait(interval):
            return
