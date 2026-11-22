"""Is the two-arm cell map one map? Each item's coordinate frame and uncertainty, CAD lengths recomputed from the map, and a verdict.

    python omx_map_gate.py check [--choice key=value ...]      exit 1 when the map is refused

Why (2026-11-14): preset v24-20261114 held the ship, plates and top camera where that day's frame showed them and the arm bases where
the 11-03 arm FK had put them. The overlay agreed, and against the arms everything was 26-44 mm off. So before a map is used:
  - every measured item names the frame it was read in, and two frames in one map is refused,
  - lengths the CAD fixes are recomputed from the map (the dock span between the base plates, the bridge that seats each slot plate),
  - each item carries a sigma, and an item whose 2 sigma exceeds what the step tolerates is "unconfirmed": geometry evidence in the
    sim (D-947), not a basis for a real run until the arm-reference steps narrow it.
No sigma here is measured: each is the reading method's stated size, to be replaced by residuals as the marker path (cell_frame, D-933) takes over.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_two_arm_sites as sites  # noqa: E402

FIXTURE, PHOTO_1114 = "fixture-20261103", "table-edge-20261114"  # the stud-plate/arm-FK survey frame; the 11-14 one-frame fit pinned to the table edge
# (item, choice value) -> (frame, sigma mm, how it was read). frame None = not measured (a design or assumed value): never mixed, always unconfirmed
SOURCES = {
    "top_camera": {"2026-11-03": (FIXTURE, 3., "stud-grid PnP"), "2026-11-10": (FIXTURE, 3., "resurvey"), "2026-11-12": (FIXTURE, 5., "fit to a later frame"),
                   "2026-11-14": (PHOTO_1114, 5., "one-frame fit, 17 edge points"), "snapshot": (FIXTURE, 3., "pad-end PnP refit")},
    "arm_bases": {"surveyed": (FIXTURE, 10., "arm FK fit (arm_b), plate centre (arm_a)"), "plate-centre": (FIXTURE, 5., "plate centres in the top frame"),
                  "snapshot": (FIXTURE, 5., "plate centres in the top frame"), "photo-20261114": (PHOTO_1114, 3., "plate edges picked by eye"),
                  "docks-photo": (PHOTO_1114, 4., "189.8 mm between the plates and 70.4 mm behind the stern, both read in the 11-14 frame; hung on the ship"),
                  "cad-190": (PHOTO_1114, 5., "DL-52 190 mm between the plates, CAD 71.25 axis; x as photo-20261114"),
                  "cad-194": (PHOTO_1114, 5., "user 194 mm between the plates, CAD 71.25 axis; x as photo-20261114"),
                  "measured-194": (None, 10., "CAD-symmetric guess"), "span": (None, 10., "CAD-symmetric guess")},
    "temp_lanes": {"photo-20261107": (FIXTURE, 3., "pads in the top frame"), "photo-20261108": (FIXTURE, 3., "pads in the top frame"),
                   "photo-20261110": (FIXTURE, 3., "pads in the top frame"), "snapshot": (FIXTURE, 3., "pads in the top frame"),
                   "photo-20261114": (PHOTO_1114, 5., "plate fit, too few clean pads"), "fan": (None, 5., "bridge v7 seat from the arm base")},
    "ship_pose": {"photo-20261110": (FIXTURE, 3., "hull fit"), "snapshot": (FIXTURE, 3., "hull fit"), "photo-20261114": (PHOTO_1114, 3., "hull fit, IoU .94"),
                  "assumed": (None, 20., "assumed at the table edge"), "berth-v16": (None, 5., "dock CAD from the arm bases")},
    "belt_pose": {"fixture": (None, 20., "fixture design"), "photo-20261110": (FIXTURE, 10., "strip in the top frame"), "snapshot": (FIXTURE, 10., "strip in the top frame"),
                  "photo-20261114": (PHOTO_1114, 10., "strip middle; the stop was under a container")},
}
TOLERANCE_MM = dict(arm_bases=3., ship_pose=2.7, temp_lanes=5., belt_pose=10., top_camera=3.)  # grasp reach; hold funnel; plate catch; belt pick is seen again; pixel to mm
DOCK_SPAN_MM, BRIDGE_MM = (190., 200.), 200.  # v24/v18 docks between the base plates (BERTH_V16_SPEC); bridge v7: arm axis to the middle lane


def provenance(choices):
    """{item: dict(choice, frame, sigma_mm, source)} for the five items a layout places."""
    out = {}
    for item, table in SOURCES.items():
        value = str(choices[item])
        frame, sigma, how = table.get("span" if value.startswith("span-") else value, (None, 20., "unknown choice"))
        if value == "snapshot" and choices.get("cell_snapshot"):  # a snapshot says which frame its camera read it in (older ones: the survey frame)
            frame = sites.load_snapshot(choices["cell_snapshot"]).get("frame", frame)
        out[item] = dict(choice=value, frame=frame, sigma_mm=sigma, source=how)
    if out["arm_bases"]["choice"] in sites.DOCKS:  # the docks hang the base plates on the hull: the bases are in whatever frame the ship was read in
        out["arm_bases"]["frame"] = out["ship_pose"]["frame"]
    return out


def self_checks(layout):
    """Lengths the printed parts fix, recomputed from the map: [dict(name, value_mm, expected, ok)]."""
    c, out = layout.choices, []
    ya, yb = layout.arms["arm_a"].base[1], layout.arms["arm_b"].base[1]
    inner = sites.BERTH_V16_SPEC["base_inner_from_axis_mm"]
    if "quay" not in str(c["berth_kit"]):  # the docks tie both base plates to the hull
        gap = (yb - ya) * 1000 - 2 * inner
        out.append(dict(name="dock span between the base plates", value_mm=round(float(gap), 1), expected="190-200 +-3", ok=bool(DOCK_SPAN_MM[0] - 3 <= gap <= DOCK_SPAN_MM[1] + 3)))
        off = (c["ship_centre_y_m"] - (ya + yb) / 2) * 1000
        out.append(dict(name="ship centreline against the middle of the plates", value_mm=round(float(off), 1), expected="0 +-5", ok=bool(abs(off) <= 5)))
    if c["temp_bridge"] == "v7" and c["temp_lanes"] != "fan":
        for tag, plate in layout.plates.items():
            d = math.dist(plate["lanes"][1][0], layout.arms[plate["arm"]].base[:2]) * 1000
            out.append(dict(name=f"bridge v7: plate {tag} middle lane to its arm axis", value_mm=round(d, 1), expected="200 +-15", ok=bool(abs(d - BRIDGE_MM) <= 15)))
    return out


def gate(layout):
    """dict(verdict, why, items, checks). "refuse": two frames in one map or a CAD length broken (the map contradicts itself);
    "unconfirmed": one map, but an item is not measured or its 2 sigma is past its tolerance; "ok" otherwise."""
    items, checks = provenance(layout.choices), self_checks(layout)
    frames = sorted({i["frame"] for i in items.values() if i["frame"]})
    why = []
    if len(frames) > 1:
        why.append("two frames in one map: " + "; ".join(f"{f}: {', '.join(k for k, i in items.items() if i['frame'] == f)}" for f in frames))
    why += [f"{k['name']}: {k['value_mm']} mm, expected {k['expected']}" for k in checks if not k["ok"]]
    loose = [f"{k} ({i['source']}, 2 sigma {2 * i['sigma_mm']:.0f} mm > {TOLERANCE_MM[k]} mm)" if i["frame"] else f"{k} (not measured: {i['source']})"
             for k, i in items.items() if not i["frame"] or 2 * i["sigma_mm"] > TOLERANCE_MM[k]]
    return dict(verdict="refuse" if why else "unconfirmed" if loose else "ok", why=why, unconfirmed=loose, frame=frames[0] if len(frames) == 1 else None,
                items=items, checks=checks)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--choice", action="append")
    a = p.parse_args(argv)
    result = gate(sites.Layout(**sites.parse_choices(a.choice)))
    print(json.dumps(result, indent=1))
    return int(result["verdict"] == "refuse")


if __name__ == "__main__":
    raise SystemExit(main())
