"""Execute an incident-bound transfer onto a measured, empty, fixed support."""
from __future__ import annotations

import json
import math
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import cell_envelope
import cell_objects
import cell_params
from cell_auto_setup import load_config
from cell_recovery_cargo import fixed_base_geometry, fixed_site as _fixed_site
from cell_route_surface import contact_evidence


SEQUENCE = ("goto above_place", "run descend_place", "run release_place", "run lift_place")
SEATING_BAND_M = 0.0025  # cell_control_core.evaluate_tactile_place_compliance


def _number(x):
    return type(x) in (int, float) and math.isfinite(x)


def _point(point, n):
    return isinstance(point, (tuple, list)) and len(point) == n and all(_number(x) for x in point)


def _body_near(actual, planned, tolerance):
    return (_point(actual, 6) and _point(planned, 6)
            and max(abs(a - b) for a, b in zip(actual[:5], planned[:5])) <= tolerance)


def _seating_limits(cargo, surface):
    """TCP z interval supported under both measured height bounds and inside the existing seating band."""
    error = cargo.get("source_height_evidence_error_m")
    spread = surface.get("repeatability_m")
    grasp = cargo.get("grasp_above_base_m")
    z = surface.get("measured_z_m")
    source = cargo.get("source_contact")
    if (not isinstance(source, dict) or source.get("source_tier") != 1
            or source.get("object_id") != cargo.get("object_id")
            or (source.get("surface") or {}).get("status") != "matched_contact"
            or surface.get("status") != "matched_contact" or not all(_number(v) for v in (error, spread, grasp, z))
            or min(error, spread) < 0 or grasp <= 0):
        return None
    err = error + spread
    lower, upper = z + grasp + err - SEATING_BAND_M, z + grasp - err
    return [lower, upper] if lower <= upper else None


def _seated(xyz, candidate, tilt_error_m=0.0):
    nominal = candidate["target_xyz_m"]
    bounds = candidate["seated_z_m"]
    return (_number(tilt_error_m) and tilt_error_m >= 0 and math.dist(xyz[:2], nominal[:2]) <= SEATING_BAND_M
            and bounds[0] + tilt_error_m <= xyz[2] <= bounds[1] - tilt_error_m)


def build_backend(args, cell, kw, status):
    cargo = kw.get("placement_context")
    if not isinstance(cargo, dict) or "destination" not in cargo:
        raise ValueError("PLACEMENT_CARGO_UNKNOWN")
    return LivePlacement(args, cell, kw, status, cargo)


class LivePlacement:
    def __init__(self, args, cell, kw, status, cargo):
        import omx_tcp
        from cell_auto_evidence import bound_reference_image
        from cell_space import Space
        from grasp_planner import Planner

        config = self.config = load_config(args.config)
        if config.get("arm_id") != args.arm or "_commissioning" in config:
            raise ValueError("PLACEMENT_ARM_OR_MODE_MISMATCH")
        self.commissioning = kw.get("placement_commissioning") is True
        if self.commissioning:
            config["_commissioning"] = {"person_at_switch": True}
        self.cargo, self.cell, self.args, self.kw = cargo, cell, args, kw
        self.catalog = cargo.get("catalog")
        if (not isinstance(self.catalog, list) or cell_envelope.digest(self.catalog) != cargo.get("catalog_sha256")
                or sum(e.get("id") == cargo.get("object_id") for e in self.catalog) != 1):
            raise ValueError("PLACEMENT_CARGO_CATALOG_UNKNOWN")
        self.entry = next(e for e in self.catalog if e["id"] == cargo["object_id"])
        config["_payload"] = cell_objects.payload(self.catalog, cargo["object_id"])
        if (config["_payload"] != cargo.get("payload")
                or any(not _number(cargo.get(k)) for k in ("length_mm", "width_mm", "held_axis_deg", "grasp_above_base_m"))
                or any(cargo[k] <= 0 or cargo[k] != self.entry.get(k) for k in ("length_mm", "width_mm"))
                or not 0 < cargo["grasp_above_base_m"] <= self.entry["top_height_mm"] / 1000):
            raise ValueError("PLACEMENT_CARGO_GEOMETRY_UNKNOWN")
        self.calibration = json.loads(Path(config["calibration_path"]).expanduser().read_bytes())
        ref_path = (config.get("preflight") or {}).get("reference_top")
        self.ref, error = bound_reference_image(self.calibration, config, Path(ref_path).expanduser() if ref_path else None)
        if error:
            raise ValueError(error)
        self.tcp = omx_tcp.config_tcp(config)
        if not _number(self.tcp):
            raise ValueError("PLACEMENT_TCP_UNKNOWN")
        self.library = json.loads(args.library.read_bytes())
        self.lib_sha = cell_envelope.digest(self.library)
        self.session = status.get("operating_context")
        self.start, self.target = status.get("state"), status.get("target")
        if (status.get("library_sha256") != self.lib_sha or not isinstance(self.session, dict)
                or self.session.get("scope") != "hardware" or not isinstance(self.session.get("session_id"), str)
                or len(self.session["session_id"].split()) != 1 or self.session["session_id"].strip() != self.session["session_id"]
                or not _body_near(self.start, self.target, 1) or self.target[5] != self.library["gripper_closed"]):
            raise ValueError("PLACEMENT_START_NOT_BOUND")
        self.planner = Planner({**config["plan"], "tcp_x_m": self.tcp})
        self.space = Space(Path(config.get("space_dir", "~/rosy-omx/space")).expanduser())
        self.diagnostics = {}
        self.before = None

    def candidates(self):
        from chunk_runner_guards import parse_transit
        from grasp_planner import norm_to_rad
        from omx_adapter.chunk_library import transit_path
        from cell_pipeline_io import limit_error

        for name, site in self.config["sites"].items():
            if not _fixed_site(name, self.args.arm):
                self.diagnostics[name] = {"reason": "fixed_support_not_established"}
                continue
            xy = site.get("place")
            if (self.cargo["destination"] is not None and (
                    self.cargo["destination"] != name or self.cargo.get("destination_xy_m") != xy
                    or self.cargo.get("destination_layer") != 0)):
                self.diagnostics[name] = {"reason": "outside_assigned_destination"}
                continue
            if not _point(xy, 2) or not fixed_base_geometry(site) or not site.get("surface_px"):
                self.diagnostics[name] = {"reason": "fixed_surface_geometry_missing"}
                continue
            fine = (self.calibration.get("sites") or {}).get(name)
            if not isinstance(fine, dict) or not fine.get("homography") or fine.get("coarse"):
                self.diagnostics[name] = {"reason": "fine_destination_map_missing"}
                continue
            surface = contact_evidence(self.config, name, self.calibration)
            if surface["status"] != "matched_contact":
                self.diagnostics[name] = {"reason": surface["reason"]}
                continue
            seated_z = _seating_limits(self.cargo, surface)
            if seated_z is None:
                self.diagnostics[name] = {"reason": "source_or_destination_support_height_uncertain"}
                continue
            self.diagnostics[name] = {"reason": "trajectory_unavailable"}
            z = surface["measured_z_m"] + self.cargo["grasp_above_base_m"]
            pose = dict(x=xy[0], y=xy[1], z=z, yaw_deg=site["yaw_deg"])
            closed, opened = self.target[5], self.config["plan"]["grip_open"]
            if opened <= self.start[5] or self.planner.fps != self.library["fps"]:
                continue
            try:
                chunks, _ = self.planner.site("place", pose, closed, opened, norm_to_rad(self.target[4]))
            except (SystemExit, ValueError):
                continue
            lib = {**self.library, "chunks": {**self.library["chunks"], **chunks},
                   "source": {"recovery_start": self.target, "support": name, "place": pose}}
            # A reviewed revision covers the exact starting target as well as the newly generated chunks.
            if lib.get("holding") or limit_error(self.config, lib):
                continue
            travel = transit_path(self.target, chunks["above_place"][0], closed, lib["fps"],
                                  parse_transit(lib), lib.get("transit_speed", 0.85))
            approach = [self.start, *travel, *chunks["descend_place"]]
            frames = [*approach, *chunks["release_place"], *chunks["lift_place"]]
            if any(abs(r[5] - closed) > 0.001 for r in approach[1:]):
                continue
            bound = (self.config.get("keep_out") or self.planner.plan.get("keep_out") or {}).get("x_max_m")
            if bound is not None and any(self.planner.body_x(f) > bound for f in frames):
                continue
            state = self._state(self.lib_sha, True)
            assessment = cell_envelope.assess(self.config, self.calibration, lib, state,
                                              sequence=(*SEQUENCE, "restore-library " + self.lib_sha), check_home=False)
            accepted = assessment.get("status") == "verified" or (
                self.commissioning and assessment.get("status") == assessment.get("mode") == "commissioning")
            if assessment.get("allowed") is not True or not accepted:
                self.diagnostics[name] = {"reason": assessment["reason"], "task_sha256": assessment.get("task_sha256")}
                continue
            self.diagnostics[name] = {"reason": "awaiting_clear_view"}
            xyz_path = [self._xyz(f) for f in approach]
            yield {"target": name, "path_xyz_m": xyz_path,
                   "sweep_xyz_m": xyz_path + [self._xyz(f) for f in chunks["lift_place"]],
                   "frames": frames, "library": lib, "assessment": assessment, "target_xyz_m": [*xy, z],
                   "surface": surface, "seated_z_m": seated_z}

    def _xyz(self, frame):
        from grasp_planner import norm_to_rad

        pose = self.planner.kin.fk([norm_to_rad(v) for v in frame[:5]])
        return [pose.x, pose.y, pose.z]

    def _tilt_error(self, frame):
        from grasp_planner import norm_to_rad
        pose = self.planner.kin.fk([norm_to_rad(v) for v in frame[:5]])
        angle = abs(pose.tool_down_error_rad)
        if not _number(angle) or angle >= math.pi / 2:
            return math.inf
        radius = math.hypot(self.cargo["length_mm"], self.cargo["width_mm"]) / 2000
        return radius * math.sin(angle) + self.cargo["grasp_above_base_m"] * (1 - math.cos(angle))

    def _state(self, sha, holding):
        state = self.cell.act("state")
        if (not cell_envelope._state_current(state, time.time()) or state.get("operating_context") != self.session
                or state.get("library_sha256") != sha or state.get("human_hold_latched") is not False
                or state.get("holding") is not holding or not _point(state.get("state"), 6)
                or not _point(state.get("target"), 6)):
            raise ValueError("PLACEMENT_RUNNER_STATE_CHANGED")
        if holding and (state["target"][5] != self.target[5] or state["state"][5] <= state["target"][5] + 2):
            raise ValueError("PLACEMENT_GRASP_READBACK_LOST")
        return state

    def _empty_view(self, candidate, state, *, after=None):
        from cell_recovery_placement_live_view import camera_aligned, empty_surface
        from cell_zone_verification import _frame

        name = candidate["target"]
        if contact_evidence(self.config, name, self.calibration) != candidate["surface"]:
            self.diagnostics[name] = {"reason": "support_changed"}
            return None
        receipt, unavailable = _frame(self.cell, "top", self.before, after=after)
        if not unavailable and not camera_aligned(self.ref, receipt["image"], self.config["params"]):
            unavailable = "camera_moved"
        if not unavailable:
            unavailable = empty_surface(self.config, self.calibration, name, self.cargo, self.entry,
                                        self.planner.kin, state["state"], receipt["image"])
        if unavailable:
            self.diagnostics[name] = {"reason": unavailable}
            return None
        self.before = receipt
        return receipt

    def available(self, candidate):
        from cell_observe import predicted_pixel
        from cell_recovery_plan import build_multi_site_look
        from cell_zone_verification import MAX_FRAME_AGE_S

        s = self._state(self.lib_sha, True)
        if not _body_near(s["state"], self.start, 1) or s["target"] != self.target:
            return False
        before = self._empty_view(candidate, s)
        if before is None:
            return False
        name = candidate["target"]
        image = before["image"]
        shape = image.shape[:2]
        margin = cell_params.get(self.config["params"], "place.margin_mm")
        frames = candidate["frames"]
        width = math.hypot(self.cargo["length_mm"], self.cargo["width_mm"]) / 2 + margin
        params = dict(self.config["params"])
        params["corridor.half_width_mm"] = max(cell_params.get(params, "corridor.half_width_mm"), width)
        # A load projects below the TCP. Include the base and the object's height in the low-clearance sweep.
        params["corridor.base_m"] = 0
        params["corridor.clear_z_m"] = cell_params.get(params, "corridor.clear_z_m") + self.cargo["grasp_above_base_m"]
        full_roi = [0, 0, shape[1], shape[0]]
        def project(point):
            px = predicted_pixel(self.config, self.calibration, name, point)
            return px if px is not None and 0 <= px[0] < shape[1] and 0 <= px[1] < shape[0] else None

        # An offscreen edge gets clipped when rasterizing a corridor; require its boundary inside the frame too.
        radius = params["corridor.half_width_mm"] / 1000
        if any(project((x + dx, y + dy)) is None for x, y, _ in candidate["sweep_xyz_m"]
               for dx, dy in ((-radius, -radius), (-radius, radius), (radius, -radius), (radius, radius))):
            self.diagnostics[name] = {"reason": "sweep_outside_camera"}
            return False
        look = build_multi_site_look(SimpleNamespace(frame=lambda _: image), self.config, self.calibration,
                                     name, full_roi, params, project, self.tcp)
        load = self.kw.get("load_check")
        ok = (look(frames).get("clear") is True and (load is None or load(frames).get("ok") is True)
              and 0 <= time.time() - before["source_stamp"] <= MAX_FRAME_AGE_S)
        self.diagnostics[name] = {"reason": "clear" if ok else "path_or_load_refused"}
        return ok

    def reserve(self, candidate):
        import numpy as np
        # Existing callers use ROI-local reservation masks. Reserving the whole view avoids equating different origins.
        mask = np.ones(self.before["image"].shape[:2], dtype=bool)
        return self.space.reserve(self.args.arm, mask, ttl_s=360).get("ok") is True

    def release(self, candidate):
        self.space.release(self.args.arm)

    def place(self, candidate):
        from cell_recovery_placement_trial import record_placement
        return record_placement(self, candidate, self._place)

    def _place(self, candidate):
        from cell_zone_verification import _frame, _stamp
        from cell_recovery_placement_live_view import verify_arrival

        result = {"supported": False, "released": False, "retreated": False, "verified": False,
                  "surface": candidate["surface"]}
        lib, gate = candidate["library"], candidate["assessment"]
        if not self.available(candidate):
            return result
        result["before"] = _stamp(self.before)
        self._state(self.lib_sha, True)
        with tempfile.TemporaryDirectory(dir=Path(self.config["work_dir"]).expanduser()) as d:
            path = Path(d) / "place.json"
            path.write_text(json.dumps(lib), encoding="utf-8")
            if self.cell.checked(f"load {path}", gate).get("ok") is not True:
                return result
        revision = gate["library_sha256"]
        for command in SEQUENCE:
            released = command == "run lift_place"
            state = self._state(revision, not released)
            if command == "run descend_place":
                view = self._empty_view(candidate, state, after=time.time())
                if view is None:
                    result["reason"] = self.diagnostics[candidate["target"]]["reason"]
                    return result
                result["before_descent"] = _stamp(view)
            if command == "run release_place" and not _seated(self._xyz(state["state"]), candidate, self._tilt_error(state["state"])):
                result["reason"] = "PLACEMENT_TOUCHDOWN_CHANGED"
                return result
            if not self.reserve(candidate):
                result["reason"] = "PLACEMENT_RESERVATION_LOST"
                return result
            reply = self.cell.checked(command, gate, timeout=120)
            if reply.get("ok") is not True or reply.get("fault") or reply.get("settled") is not True:
                result["reason"] = "PLACEMENT_COMMAND_REFUSED_" + command.split()[-1]
                return result
            state = self._state(revision, command not in SEQUENCE[2:])
            if command == "goto above_place" and not _body_near(state["state"], lib["chunks"]["above_place"][0], 1):
                result["reason"] = "PLACEMENT_APPROACH_MISMATCH"
                return result
            if command == "run descend_place":
                xyz = self._xyz(state["state"])
                tilt = self._tilt_error(state["state"])
                if not _seated(xyz, candidate, tilt):
                    result["reason"] = "PLACEMENT_TOUCHDOWN_MISMATCH"
                    return result
                result.update(supported=True, touchdown_xyz_m=xyz, supported_tcp_z_m=candidate["seated_z_m"],
                              source_height_evidence_error_m=self.cargo["source_height_evidence_error_m"], tilt_error_m=tilt)
            elif command == "run release_place":
                if abs(state["state"][5] - lib["chunks"]["release_place"][-1][5]) > 2:
                    result["reason"] = "PLACEMENT_RELEASE_UNCONFIRMED"
                    return result
                result["released"] = True
            elif command == "run lift_place":
                result["retreated"] = _body_near(state["state"], lib["chunks"]["lift_place"][-1], 1)
        if not result["retreated"]:
            result["reason"] = "PLACEMENT_LIFT_UNCONFIRMED"
            return result
        name = candidate["target"]
        after, error = _frame(self.cell, "top", self.before, after=time.time())
        if error:
            result["reason"] = "PLACEMENT_AFTER_VIEW_UNAVAILABLE"
            return result
        result["after"] = _stamp(after)
        result["verification"] = verify_arrival(self.config, self.calibration, name, self.cargo, self.catalog,
                                                self.ref, self.before, after, self.cell)
        if result["verification"].get("verified") is not True:
            result["reason"] = result["verification"].get("reason") or "PLACEMENT_OBJECT_UNVERIFIED"
            return result
        self._state(revision, False)
        # The checked sequence includes this original content hash. A native load changes only the library.
        restore = f"checked {gate['session_id']} {self.lib_sha} load {self.args.library}"
        if self.cell.act(restore).get("ok") is True:
            self._state(self.lib_sha, False)
            result["verified"] = True
        return result
