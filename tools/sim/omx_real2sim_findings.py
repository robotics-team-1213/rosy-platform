"""What omx_real2sim.diff reports besides moved lanes: the arm bases and the TCP against their evidence, and the twin's findings as gap rows.

A gap row is a candidate for tools/harness/sim2real_gaps.yaml (D-480: it goes in the registry only with its evidence file, by a person):
  dict(id="G-19", item="view.top", status="candidate", finding=str, value=dict(...), limit=number|None, source=[files], next=str)
Rows come from omx_twin's twin.json (camera outline offset G-19, servo lag spread G-23) and omx_carry_sweep's dr_next.json (the TCP
values the sweep kept, G-22). Nothing here relaxes a gate: a base reading in another frame than the layout is listed but not compared
(omx_map_gate refuses a map of two frames), and the camera refit gates stay in omx_real2sim_refit.
"""
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_map_gate as map_gate  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

PLANNER_TCP_M = 0.0885       # cell_directive_compiler's default tcp_x_m (the touch value); the sim's jaw is the CAD .0740/.0741 (G-22)
CAD_TCP_M = 0.0741
TCP_SAME_MM = 0.5            # a kept sweep value this close to the planner's counts as the planner's
SERVO_SPREAD_S = 0.05        # real lag per joint differing more than this from joint to joint: one sim gain cannot match (G-23)
READINGS = ("plate-centre", "photo-20261114", "docks-photo", "cad-190", "cad-194")  # base placements that name a frame in omx_map_gate.SOURCES


def _bases(layout):
    ya, yb = layout.arms["arm_a"].base[1], layout.arms["arm_b"].base[1]
    gap = round((yb - ya) * 1000 - 2 * sites.BERTH_V16_SPEC["base_inner_from_axis_mm"], 1)
    return {n: [round(float(v), 4) for v in a.base[:2]] for n, a in layout.arms.items()}, gap


def arm_bases(preset=None, snapshot=None, **choices):
    """The preset's arm bases against every reading of them. Readings in another frame than the layout's are listed, never compared."""
    layout = sites.Layout(**(dict(preset=preset) if preset else {}), **choices)
    frame = map_gate.provenance(layout.choices)["arm_bases"]["frame"]
    xy, gap = _bases(layout)
    readings = {}
    for name in READINGS:
        kw = dict(preset=preset) if preset else {}
        kw.update(choices, arm_bases=name)
        got_xy, got_gap = _bases(sites.Layout(**kw))
        readings[name] = (map_gate.SOURCES["arm_bases"][name][0], got_xy, got_gap)
    plate = ((snapshot or {}).get("items") or {}).get("arm_bases", {}).get("plate_centre")
    if plate:  # what measure recorded; the snapshot names its own frame
        got = {n: [round(v["xy"][0], 4), round(v["xy"][1], 4)] for n, v in plate.items()}
        readings["snapshot"] = (snapshot.get("frame") or map_gate.FIXTURE, got, round((got["arm_b"][1] - got["arm_a"][1]) * 1000 - 2 * sites.BERTH_V16_SPEC["base_inner_from_axis_mm"], 1))
    tol = map_gate.TOLERANCE_MM["arm_bases"]
    against = {}
    for name, (rf, rxy, rgap) in readings.items():
        row = dict(frame=rf, comparable=bool(rf and rf == frame), inner_gap_mm=rgap)
        if row["comparable"]:
            row["delta_mm"] = {n: round(math.dist(xy[n], rxy[n]) * 1000, 1) for n in xy}
            row["within_tolerance"] = max(row["delta_mm"].values()) <= tol
        against[name] = row
    return dict(preset=preset, frame=frame, bases=xy, inner_gap_mm=gap, tolerance_mm=tol, against=against)


def tcp(layout_choices=None, dr_next=None):
    """The planner's jaw TCP against the sim's and the evidence (CAD .0741, touch .0885, the sweep's kept values)."""
    c = dict(layout_choices or sites.CHOICES)
    out = dict(planner_m=PLANNER_TCP_M, cad_m=CAD_TCP_M, touch_m=0.0885, sim_m=c["sim_tcp_x_m"],
               layout_m={a: c[f"tcp_x_{a}"] for a in ("arm_a", "arm_b")}, planner_minus_sim_mm=round((PLANNER_TCP_M - c["sim_tcp_x_m"]) * 1000, 1),
               status="open: the touch rests on an unchecked table height (G-22), the sim keeps the CAD jaw")
    if dr_next and dr_next.get("tcp_m"):
        kept = sorted(dr_next["tcp_m"])
        out["sweep_kept_m"] = kept
        out["planner_kept"] = any(abs(v - PLANNER_TCP_M) * 1000 <= TCP_SAME_MM for v in kept)
    return out


def _twin_paths(twin):
    p = Path(twin)
    return sorted(p.rglob("twin.json")) if p.is_dir() else [p]


def twin_rows(twin):
    """Gap rows from the twin.json at/under `twin`: cameras whose outline offset is past its limit (G-19), servo lag that differs by joint (G-23)."""
    paths = _twin_paths(twin)
    results = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    rows, over = [], {}
    for r in results:
        for cam, v in (r.get("view") or {}).items():
            if not v.get("within", True):
                over.setdefault(cam, []).append((r.get("episode"), v))
    for cam, found in sorted(over.items()):
        vs = [v for _, v in found]
        rows.append(dict(id="G-19", item=f"view.{cam}", status="candidate", source=[str(p) for p in paths], limit=vs[0].get("limit_px"),
                         finding=f"{cam} outline offset median {statistics.median(v['median_px'] for v in vs):.1f} px over the limit in {len(vs)} episode(s)",
                         value=dict(episodes=[e for e, _ in found], median_px=round(statistics.median(v["median_px"] for v in vs), 2),
                                    median_dx=round(statistics.median(v["median_dx"] for v in vs), 1), median_dy=round(statistics.median(v["median_dy"] for v in vs), 1)),
                         next="refit the camera from a fresh capture (omx_twin fit-camera); the 3 mm / 6 mm hold-out / pad-count gates still decide whether it is adopted"))
    lags = [r["tracking"]["real_lag_s"] for r in results if (r.get("tracking") or {}).get("real_lag_s")]
    if lags:
        mean = [statistics.mean(col) for col in zip(*lags)]
        if max(mean) - min(mean) > SERVO_SPREAD_S:
            rows.append(dict(id="G-23", item="tracking.real_lag_s", status="candidate", source=[str(p) for p in paths], limit=SERVO_SPREAD_S,
                             finding=f"real servo lag differs by joint ({min(mean):.2f}-{max(mean):.2f} s): one sim gain cannot match",
                             value=dict(real_lag_s=[round(v, 3) for v in mean], episodes=len(lags)),
                             next="per-joint gains (omx_twin fitted.kp) as a physics candidate; promotion stays task-gated (omx_sysid task)"))
    return rows


def dr_rows(dr_next, source="dr_next.json"):
    """Gap rows from the sweep's next domain randomisation: a TCP set that left the planner's value out is G-22 evidence."""
    if not isinstance(dr_next, dict) or "tcp_m" not in dr_next:
        raise SystemExit(f"{source} is not a dr_next.json (no tcp_m)")
    t = tcp(dr_next=dr_next)
    if t.get("planner_kept", True):
        return []
    return [dict(id="G-22", item="tcp.dr_next", status="candidate", source=[source], limit=TCP_SAME_MM,
                 finding=f"the sweep kept TCP {t['sweep_kept_m']} m and none is the planner's {PLANNER_TCP_M}",
                 value=dict(planner_m=PLANNER_TCP_M, sweep_kept_m=t["sweep_kept_m"]),
                 next="touch-measure the jaw on a known table height (person); until then the planner and the sim differ by %.1f mm" % t["planner_minus_sim_mm"])]


def gap_rows(twin=None, dr_next=None):
    """Gap rows from a twin.json (or folder) and a dr_next.json path; both optional."""
    dr = json.loads(Path(dr_next).read_text(encoding="utf-8")) if dr_next else None
    return (twin_rows(twin) if twin else []) + (dr_rows(dr, str(dr_next)) if dr is not None else [])


def findings(snapshot=None, preset=None, twin=None, dr_next=None):
    """dict(arm_bases, tcp, gap_rows) for omx_real2sim diff."""
    dr = json.loads(Path(dr_next).read_text(encoding="utf-8")) if dr_next else None
    return dict(arm_bases=arm_bases(preset, snapshot), tcp=tcp(dr_next=dr), gap_rows=gap_rows(twin, dr_next))
