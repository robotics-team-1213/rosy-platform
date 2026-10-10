"""D-610 6: the AI PC judges one Fleet case with Qwen3-VL through the local Ollama; analyzers stay the fallback.

A case (``GET /api/fleet/ai/case/{problem_id}``) carries the problem, its context and two views: the Rosy Cam
crop around the robot and one robot front-camera frame (JPEG base64, frame id, captured_at). The model is
called on ``127.0.0.1`` only (the service runs on the AI PC, so the site PC -> AI PC network does not matter),
with a 6 s timeout. Its answer must be one word of the case kind's table (D-610 4) and cite both views; anything
else, a timeout or no model is ``None`` and the caller keeps the deterministic analyzer's proposal (D-610 5 end:
that one still passes every D-577 gate). Frames are never written to disk; the proposal cites frame ids, ages and
sha256 only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.request
from typing import Callable, Optional
from core_common.protocol.situation import DIRECTIONS, TYPES, build_assessment, model_assessment_schema

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3-vl:8b-instruct"           # D-492 model; the digest is pinned in the profile id
PROMPT_ID = "d619-v5"
TIMEOUT_S = 6.0
TTL_S = 6.0
VIEWS = ("rosy_cam", "front")
#: D-610 4: the words the model may choose per problem kind (existing CORE / Fleet commands only).
WORDS = {"stuck": ("WAIT", "BACK_AND_RETRY", "RESUME", "ABORT", "YIELD", "MANUAL"),
         "stalled": ("WAIT", "LINE_OFF", "STOP"),
         "pose_lost": ("WAIT", "IDENTIFY", "STOP"),
         "deadlock": ("REPLAN", "WAIT"),
         "trip_failed": ("STOP", "CANCEL")}
_LOG = logging.getLogger("rosy_situation.vlm")

PROMPT = """You decide what a small lane-following robot should do next. Pictures follow in the labeled order:
ceiling camera crop and front camera per robot. The robot's local safety (body stop, watchdog,
E-stop) and its own sensor re-check stay in force whatever you choose. Answer with one JSON object only:
{{"decision": one of {words}, "reason": short snake_case, "confidence": 0..1, "seen": what in the pictures decided it,
"assessment": {{"type": one of {types}, "direction": one of {directions},
"uncertainties": [what the images cannot confirm]}}}}. Observations concern the chosen robot only.
The direction is advisory, not permission to move. Never claim body clearance, depth, grasp success,
or action completion from pixels or overlays. Do not identify a robot in the ceiling view without evidence.
In seen, describe the visible lane boundaries, wall or corner, and obstruction/free space in one concrete
sentence. Do not just repeat the cause or camera label. If geometry is uncertain, say what cannot be determined.
The context cause is a report, not proof of what the pictures show.
Task objective: resolve the reported problem and recover the intended task while retaining device safety.
For lane following, distinguish a visible bend/corner from an actual obstruction or unseen lane.
White floor tape is a lane boundary; an upright white surface may be a wall. Do not conflate them.
If an annotated front image is supplied, green means the perception system's estimated drivable way,
dimmed areas are rendering, and magenta TARGET/arc is a steering estimate. These are not physical
obstacles, verified free space or execution permission. Raw front images have no such overlays.
Treat operator_report and requested_outcome as requests or hypotheses, not measured facts.
Use state_age_s to assess device state freshness; never guess metric distances from pixels.
Missing/stale sensors or unknown ceiling robot identity must appear in uncertainties.
Observe each image independently before combining views: do not copy an object from one view into another.
Describe visible vertical walls/doorways even when you cannot establish whether they block the route.
Tape attached to a wall is a visual marker, not by itself an obstruction on the floor.
Use context in this order: task intent; timestamped device state and sensor measurements; map/camera
identity and calibration; recent attempted actions and their outcomes; operator reports as hypotheses.
Missing values mean unknown, not zero or clear. Compare view timestamps before combining observations.
clearance_at_open_m is a retained stuck-opening snapshot, not current clearance or permission to move.
route_context is timestamped intent, not motion permission; expired valid_until is historical intent.
Current state_age_s does not refresh that measurement; CORE must check current sensors.
If ceiling target identity is unknown, describe the scene without attributing a position to this robot.
Never infer the intended turn or metric geometry without a supplied route or calibrated map.
An EMERGENCY state requires WAIT; an operator request cannot release E-stop.
Keep each observation and uncertainty to one short sentence; list at most two decisive uncertainties.
Prefer WAIT when the pictures do not show the way clear. Problem and context:
{context}"""


def response_schema(words, robots, deadlock=False):
    assessment = model_assessment_schema(VIEWS)
    del assessment["properties"]["observations"]
    assessment["required"].remove("observations")
    properties = {"decision": {"type": "string", "enum": list(words)},
                  "reason": {"type": "string", "minLength": 1, "maxLength": 64},
                  "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                  "seen": {"type": "string", "maxLength": 200},
                  "assessment": assessment}
    required = list(properties)
    if deadlock:
        properties.update(robot_id={"type": "string", "enum": list(robots)},
                          blocked_edges={"type": "array", "items": {"type": "string"}})
        required.append("robot_id")
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


class Vlm:
    def __init__(self, url: str = OLLAMA_URL, model: str = MODEL, *,
                 post: Callable[[str, dict, float], dict] = _post,
                 get: Callable[[str, float], dict] = _get) -> None:
        self.url, self.model, self._post, self._get = url.rstrip("/"), model, post, get
        self.options = {"temperature": 0, "num_ctx": 8192, "seed": 42}
        configured = json.loads(os.environ.get("ROSY_VLM_OPTIONS", "{}"))
        bounds = {"temperature": (0, 1), "num_ctx": (4096, 16384), "seed": (0, 2147483647),
                  "repeat_penalty": (0.8, 1.2), "top_p": (0.1, 1), "top_k": (1, 100)}
        if not isinstance(configured, dict) or set(configured) - set(bounds):
            raise ValueError("unsupported ROSY_VLM_OPTIONS")
        for key, value in configured.items():
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not bounds[key][0] <= value <= bounds[key][1]
                    or key in ("num_ctx", "seed", "top_k") and type(value) is not int):
                raise ValueError(f"invalid ROSY_VLM_OPTIONS {key}")
        self.options.update(configured)
        self.options_id = hashlib.sha256(json.dumps(self.options, sort_keys=True).encode()).hexdigest()[:8]

    def profile(self) -> Optional[str]:
        """``<model>@<digest12>:<prompt>`` once Ollama reports the model, else None (not loaded)."""
        try:
            models = self._get(f"{self.url}/api/ps", TIMEOUT_S).get("models") or []
        except (OSError, ValueError, AttributeError) as exc:
            _LOG.info("vlm not available: %s", exc)
            return None
        for row in models:
            if row.get("name") == self.model and re.fullmatch(r"[0-9a-f]{64}", str(row.get("digest") or "")):
                return f"{self.model}@{row['digest'][:12]}:{PROMPT_ID}:{self.options_id}"
        return None

    def judge(self, case: dict, now: float) -> Optional[dict]:
        """One proposal for this case, or None (the analyzer's proposal stands)."""
        words = WORDS.get(case.get("kind"), ())
        deadlock = case.get("kind") == "deadlock"
        members = case.get("members") if deadlock else {case.get("robot_id"): case}
        if (not words or not members
                or any(not (member.get("views", {}).get(v) or {}).get("jpeg_b64")
                       for member in members.values() for v in VIEWS)):
            return None                               # D-610 5: both views or no VLM judgement
        profile = self.profile()
        if profile is None:
            return None
        context_data = {k: case.get(k) for k in ("kind", "robot_id", "problem_id", "context")}
        context_data["history"] = (case.get("history") or [])[:3]
        context_data["view_metadata"] = {rid: {view: {key: member["views"][view].get(key) for key in (
            "frame_id", "captured_at", "overlay", "width", "height", "target_robot_id", "map_id",
            "calibration_revision", "crop_map")} for view in VIEWS} for rid, member in members.items()}
        context = json.dumps(context_data, separators=(",", ":"), default=str, ensure_ascii=False)
        if len(context) > 12000:
            _LOG.warning("vlm context too large; not truncated into a partial request")
            return None
        pairs = [(rid, v) for rid in sorted(members) for v in VIEWS]
        images = [members[rid]["views"][v]["jpeg_b64"] for rid, v in pairs]
        prompt = PROMPT.format(words=list(words), context=context, types=list(TYPES), directions=list(DIRECTIONS))
        prompt += "\nPicture order: " + ", ".join(f"{rid}:{view}" for rid, view in pairs)
        if deadlock:
            prompt += ("\nChoose robot_id from the cycle. For REPLAN include blocked_edges, a nonempty list "
                       "from that robot's avoidable edges. Member contexts: "
                       + json.dumps({rid: member.get("context") for rid, member in members.items()}, default=str, ensure_ascii=False))
        if len(prompt) > 20000:
            _LOG.warning("vlm prompt too large")
            return None
        try:
            cited = {}
            for rid, view in pairs:
                image = members[rid]["views"][view]
                captured_at = float(image["captured_at"])
                if not math.isfinite(captured_at):
                    return None
                cited.setdefault(rid, {})[view] = {
                    "frame_id": image.get("frame_id"), "captured_at": captured_at,
                    "age_s": round(now - captured_at, 3),
                    "sha256": hashlib.sha256(base64.b64decode(image["jpeg_b64"], validate=True)).hexdigest()}
            started = time.monotonic()
            descriptions, prompt_calls = {}, []
            for (mid, view), jpeg in zip(pairs, images):
                observation_prompt = (f"Describe only visible physical surfaces and floor markings in this {view} "
                    "image in one short sentence. Do not assume a corner or free path. Do not identify a target "
                    "robot. Answer JSON with observation.")
                remaining = TIMEOUT_S - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("VLM observation deadline")
                observed = self._post(f"{self.url}/api/chat", {
                    "model": self.model, "stream": False, "options": {**self.options, "num_predict": 96},
                    "format": {"type": "object", "additionalProperties": False, "required": ["observation"],
                               "properties": {"observation": {"type": "string", "minLength": 1, "maxLength": 180}}},
                    "messages": [{"role": "user", "content": observation_prompt, "images": [jpeg]}]}, remaining)
                observation = json.loads((observed.get("message") or {}).get("content") or "")
                if (not isinstance(observation, dict) or set(observation) != {"observation"}
                        or not isinstance(observation["observation"], str)
                        or not 1 <= len(observation["observation"].strip()) <= 180):
                    return None
                descriptions.setdefault(mid, {})[view] = observation["observation"].strip()
                prompt_calls.append({"robot_id": mid, "view": view, "text": observation_prompt,
                                     "model_options": {**self.options, "num_predict": 96}})
            prompt += ("\nNo images in this reasoning call. Independent per-view model observations (unverified): "
                       + json.dumps(descriptions, ensure_ascii=False)
                       + ". Use these observations without transferring objects between views.")
            if len(prompt) > 20000:
                return None
            remaining = TIMEOUT_S - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("VLM judgement deadline")
            prompt_calls.append({"text": prompt, "model_options": dict(self.options)})
            reply = self._post(f"{self.url}/api/chat", {
                "model": self.model, "stream": False, "format": response_schema(words, members, deadlock), "options": self.options,
                "messages": [{"role": "user", "content": prompt}]}, remaining)
            answer = json.loads((reply.get("message") or {}).get("content") or "")
            decision = str(answer["decision"]).upper()
            confidence = float(answer.get("confidence", 0.0))
            if not math.isfinite(confidence):
                return None
            confidence = min(1.0, max(0.0, confidence))
            rid = answer["robot_id"] if deadlock else case.get("robot_id")
            if rid not in members:
                return None
            body = {}
            if deadlock and decision == "REPLAN":
                edges = answer.get("blocked_edges")
                avoidable = (case.get("context") or {}).get("avoidable", {}).get(rid, [])
                if (not isinstance(edges, list) or not edges or not all(isinstance(e, str) for e in edges)
                        or not set(edges) <= set(avoidable)):
                    return None
                body = {"blocked_edges": edges}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, binascii.Error) as exc:
            _LOG.warning("vlm judgement dropped: %s", exc)
            return None
        if decision not in words:
            _LOG.warning("vlm word %r not allowed for %s", decision, case.get("kind"))
            return None
        if time.monotonic() - started > TIMEOUT_S:
            return None
        reason = "".join(c if c.isalnum() or c in "_:.-" else "_" for c in str(answer.get("reason") or "vlm").lower())
        evidence = {"views": cited[rid], "map_pose": (members[rid].get("context") or {}).get("map_pose"),
                    "seen": str(answer.get("seen") or "")[:200]}
        evidence["prompt"] = {"id": PROMPT_ID, "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                              "text": prompt, "calls": prompt_calls}
        evidence["inference_s"] = round(time.monotonic() - started, 3)
        evidence["model_options"] = dict(self.options)
        try:
            assessment = answer.get("assessment")
            if isinstance(assessment, dict):
                assessment = {**assessment, "observations": descriptions[rid]}
            evidence["assessment"] = build_assessment(assessment, "mobility", cited[rid])
        except ValueError:
            _LOG.warning("vlm assessment missing or invalid")
            return None
        if deadlock:
            evidence["members"] = {mid: {"views": cited[mid],
                                        "map_pose": (member.get("context") or {}).get("map_pose")}
                                   for mid, member in members.items()}
        return {"robot_id": rid, "stuck_id": case.get("stuck_id") or case.get("problem_id"), "body": body,
                "decision": decision, "reason": reason[:64] or "vlm", "confidence": confidence,
                "evidence": evidence, "source": f"vlm:{profile}", "observed_at": now, "ttl_s": TTL_S}
