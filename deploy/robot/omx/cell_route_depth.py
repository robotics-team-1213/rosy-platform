"""Paired source and destination observations for named temporary-stack transfers."""
import math
import time

import cell_depth_slots
import cell_route_check
import cell_zone_verification as zones


MAX_RGB_SKEW_S = 1 / 6  # one D435 depth frame at the configured 6 fps


def _binding(config, src, dst):
    checked = cell_route_check.route_check(config, src, dst)
    if not checked["depth_inputs_configured"]:
        return None
    sites = checked["sites"]
    binding = {}
    for role, name in (("source", src), ("destination", dst)):
        floor = cell_route_check.source_floor(config, src) if role == "source" else config["zone_rois"]
        binding[role] = {"site": name, "roi": list(sites[role]["named_top_roi"]),
                         "floor": [list(r) for r in floor["floor"]], "floor_depth_mm": list(floor["floor_depth_mm"])}
    return binding


def _read(binding, depth, top, tier):
    return cell_depth_slots.depth_reference(depth, top["image"], binding["roi"], binding["floor"], tier,
                                           floor_depth_mm=binding["floor_depth_mm"])


def _located(ref):
    edge = (ref or {}).get("local_edge_px")
    return type(edge) in (int, float) and 0 <= edge <= cell_depth_slots.LOCAL_EDGE_MAX_PX


def _tier(ref, tier):
    return bool(_located(ref) and ref.get("ok") and ref.get("occupied") and ref.get("tier_ok") and ref.get("tier") == tier)


def _empty(ref):
    height = (ref or {}).get("median_rel_mm")
    return bool(_located(ref) and ref.get("ok") and ref.get("occupied") is False and
                type(height) in (int, float) and abs(height) <= cell_depth_slots.TOL_MM)


def _receipt(top, side, depth, start, end):
    try:
        first = depth.get("first_exposure_wall_estimate_s", depth["exposure_wall_estimate_s"])
        last = depth["exposure_wall_estimate_s"]
        stamps = [first, last, top["source_stamp"], side["source_stamp"]]
        if not (depth["raw_sha256"] and first <= last and all(
                first - MAX_RGB_SKEW_S <= stamp <= last + MAX_RGB_SKEW_S for stamp in stamps[2:]) and all(
                math.isfinite(t) and start <= t <= end and end - t <= zones.MAX_FRAME_AGE_S for t in stamps)):
            return None
        return {"depth_sha256": depth["raw_sha256"], "first_stamp": first, "last_stamp": last,
                "top": zones._stamp(top), "side": zones._stamp(side), "judged_at": end}
    except (KeyError, AttributeError, TypeError):
        return None


def before_error(before):
    prior = (before or {}).get("route_depth")
    if prior:
        receipt = prior["receipt"]
        oldest = min(receipt["first_stamp"], receipt["top"]["source_stamp"], receipt["side"]["source_stamp"])
        if not 0 <= time.time() - oldest <= zones.MAX_FRAME_AGE_S:
            return "pre-motion route observations expired"
    return None


class FreshStart:
    """Apply the freshness limit at dispatch even when recorder, planner or model startup takes time."""
    def __init__(self, cell, before):
        self._cell, self._before = cell, before

    def __getattr__(self, key):
        return getattr(self._cell, key)

    def act(self, command):
        words = command.split()
        verb = words[3] if words[0] == "checked" else words[0]
        if self._before and verb not in ("state", "load", "human-hold"):
            if error := before_error(self._before):
                return {"ok": False, "error": error}
            self._before = None
        return self._cell.act(command)


def motion_cell(cell, before):
    return FreshStart(cell, before) if (before or {}).get("route_depth") else cell


def capture_before(cell, config, src, dst, previous=None):
    binding = _binding(config, src, dst)
    if binding is None:
        return None, "named route lacks calibrated slot or support geometry"
    source = getattr(cell, "cell", cell)
    started = time.time()
    with zones._side_camera(source, config) as has_side:
        if not has_side:
            return None, "named route requires before and after side frames"
        depth, receipt, error = zones._depth_after(config, started)
        if error or depth is None:
            return None, error or "missing before depth"
        deadline = time.time() + zones.FRAME_WAIT_S
        top, error = zones._frame(source, "top", previous, started, deadline)
        if error:
            return None, error
        side, error = zones._frame(source, "side", None, started, deadline)
        if error:
            return None, error
    paired = _receipt(top, side, receipt, started, time.time())
    if paired is None:
        return None, "unpaired or stale before depth and camera frames"
    src_ref = _read(binding["source"], depth, top, 2)
    dst_ref = _read(binding["destination"], depth, top, 1)
    if not _tier(src_ref, 2):
        return None, "source depth did not confirm tier 2"
    if not _empty(dst_ref):
        return None, "destination depth did not confirm an empty floor"
    before = {**top, "before_side": side, "route_depth": {"binding": binding, "receipt": paired,
              "source": src_ref, "destination": dst_ref}}
    error = before_error(before)
    return (None, error) if error else (before, None)


def policy_before(cell, config, src, dst):
    if cell_route_check.temp_to_ship(src, dst):
        return capture_before(cell, config, src, dst)
    try:
        return cell.frame_receipt("top", max_age_s=zones.MAX_FRAME_AGE_S), None
    except Exception:
        return None, None  # legacy routes can finish without a before frame; zone verification then refuses


def policy_result(cell, before, config, src, dst, res):
    from cell_policy_entry import park_ack_ok

    named = cell_route_check.temp_to_ship(src, dst)
    result = res.get("result")
    parked = res.get("parked") is True
    if result == "placed" and named:
        steps = res.get("steps") or []
        parked = bool(steps and park_ack_ok(steps[-1], require_command=True))
        res["parked"] = parked
    elif result not in ("released", "chunks_done"):
        return
    if parked:
        sites = config.get("sites") or {}
        roi = (sites.get(dst) or sites.get(dst.rsplit("-l", 1)[0]) or {}).get("auto_roi")
        res["zone_verification"] = zones.measure(cell, before, config, dst, src, roi)
    if named and not (res.get("zone_verification") or {}).get("verified"):
        res.update(result="placement_unverified")


def verify(config, src, dst, before, top, side, depth, receipt, placed_at, judged_at, stack):
    prior = before.get("route_depth") or {}
    binding = _binding(config, src, dst)
    paired = _receipt(top, side, receipt, placed_at, judged_at)
    old = prior.get("receipt") or {}
    reason = None
    if not binding or binding != prior.get("binding"):
        reason = "missing or changed named route depth calibration"
    elif (before.get("_reused") or not old or not paired or not (0 < old.get("judged_at", 0) < placed_at)
          or old.get("top") != zones._stamp(before) or old.get("side") != zones._stamp(before["before_side"])
          or not old.get("depth_sha256") or old["depth_sha256"] == paired["depth_sha256"]):
        reason = "missing, repeated or stale paired route observations"
    src_after = _read(binding["source"], depth, top, 1) if reason is None else None
    source_ok = _tier(prior.get("source"), 2) and _tier(src_after, 1)
    if not source_ok and reason is None:
        reason = "source depth did not confirm a tier 2 to tier 1 transition"
    dst_before = prior.get("destination") or {}
    if reason is None and not (_empty(dst_before) and _tier(stack.get("depth_reference"), 1) and stack.get("verified")
            and (stack.get("z_gate") or {}).get("verdict") == "PASS"):
        reason = "destination did not pass the empty to tier 1 placement check"
    return {**stack, "verified": reason is None, "reason": reason or "source tier 2 to 1 and destination empty to tier 1 verified",
            "pick_slot": {**(stack.get("pick_slot") or {}), "vacated": source_ok},
            "source_transition": {"before": prior, "after": src_after, "after_receipt": paired}}
