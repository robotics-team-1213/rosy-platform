"""Two-arm OMX cell layout without MuJoCo: arm bases, belt end, ship cells and the two temporary slot plates, in the fixture frame.

Every number comes from an existing module (mapped_stack_fixture, ship_plate, palletizing_gripper, cell_model_inventory.yaml) or from the
temp_slot_plate v11 SCAD parameters (Confluence 15368863 and set page 23233175: the bridge v7 seats each plate 200 mm from its arm, toward -x). Where CAD and
a measurement both exist the choice is a named entry of CHOICES (D-947 2: candidates compared by results, nothing silently overwritten).
"""
import copy
import functools
import json
import math
from pathlib import Path
import sys

import numpy as np

ISAAC = Path(__file__).resolve().parents[2] / "learning/envs/isaac"
sys.path.insert(0, str(ISAAC))
import mapped_stack_fixture as fx  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402
import ship_plate  # noqa: E402

CHOICES = dict(
    fixture_case="nominal-palletizing-v21-ship-surveyed",  # measured arm bases (arm_b FK, arm_a plate centre); "nominal-palletizing-v21-ship" = CAD bases
    base_z="measured",       # "measured": table + 12 mm base plate (ruler, arm_b; arm_a ASSUMED the same); "cad": the fixture's arm base z
    belt_height="ruler",     # "ruler": belt end surface 55 mm under the table (inventory, D435 says 56); "fixture": the surveyed case's belt_drop face
    temp_lanes="fan",        # "fan": bridge v7 seats plate v12 at temp_radius_m (.200) and temp_direction_deg (180); "photo-20261108"/"photo-20261107"/"photo-20261110"/"snapshot"
    temp_radius_m=.200,      # SCAD arm_r: the printed fan's shape (v12: 200 mm -> 13.77 deg), and with temp_lanes="fan" arm centre to middle-lane centre
    temp_direction_deg=180., # from each arm toward -x, away from the belt (the user's slot plan 2026-10-31)
    temp_source="scad-v12",  # two-color plate v12 CAD STLs ("navy"+"sky"); "scad-v11" keeps monochrome v11 STL; "procedural" shows collision walls
    ship_source="r08-berth",  # "r08-berth": the rated ship v15 (r08) on its berth kit with container v3 (SHIP_ASSETS); "fixture-studs": the old stud plate and 30 mm boxes
    ship_stern_x_m=.155,     # r08: stern end x, bow toward -x as the printed ship lay in the 11-07 top photo; ASSUMED at the table's belt edge (r08 not placed yet)
    ship_centre_y_m=0.0,     # r08: hull centreline y centred symmetrically between the 194 mm base plates (modular berth locks port/starboard)   # r08: hull centreline y, the middle row of the 11-08 top frame (rows +25/-14/-56 mm; was .007, the 11-07 photo's hull
                             # edges). Its x reading (holds 25 mm toward the belt) would put the stern over the belt end: x stays
    wrist_camera="photo-20261108",  # "photo-20261108": WRIST_PHOTO (fitted to arm_b); "photo-20261110": WRIST_PHOTO_A on arm_a, WRIST_PHOTO on arm_b (G-24);
                             # "v21-b": the team's printed D holder r06 (palletizing_gripper.WRIST_CAMERA_B); "stock" or "none"
    tcp_x_arm_b=.0740,       # URDF/STL v2.1 jaw (tip 74.1 mm from the pivot); a touch gave .0885 but that rests on an unchecked table height (OPEN, 14.5 mm FK offset)
    tcp_x_arm_a=.0740,       # same jaw, not confirmed on arm_a separately
    sim_tcp_x_m=.0740,       # the MuJoCo pads are the repo's v2.1 STL, whose TCP is .0740: the teacher grasps with this one (STL may not match the installed jaws)
    roll_floor_norm=-18.,    # usable wrist roll floor in the norm unit (coordinator): a step whose joint5 goes below it is flagged
    arm_bases="measured-194", # "measured-194": 194.0 mm nominal inner gap between PR33_C02_BASE plates (|y_arm|=168.25 mm); "surveyed": fixture_case bases; "plate-centre": top-frame centres; "photo-20261114": 11-14 frame (ARM_BASES_PHOTO_1114); "snapshot"
    belt_pose="fixture",     # "fixture": BELT_STOP_X and the fixture's pickup line; "photo-20261110", "photo-20261114" or "snapshot": belt strip in the top frame
    ship_pose="assumed",     # "assumed": ship_stern_x_m and ship_centre_y_m above; "photo-20261110", "photo-20261114" or "snapshot": hull fitted in the top frame
    cell_snapshot=None,      # with temp_lanes="snapshot": a rosy.omx-cell-snapshot.v1 file (omx_real2sim.py measure), the lanes the top camera saw then
    top_camera="2026-11-10", # "2026-11-10": resurveyed top camera (cell_model_inventory.yaml); "2026-11-03": initial stud-grid PnP; "2026-11-12", "2026-11-14": fitted to later frames; "snapshot": the refit in the cell_snapshot
    container_colours="orange",  # "orange": standard v3 containers; "multi": cycle orange/green/red/purple across containers
    berth_kit="v24-docks",   # "v24-docks": printed black v20 cradle + v24 docks on PR33_C02_BASE + v24 belt stopper; "v18-modular-adjustable"/"v16-modular"/"v17-modular-tight": orange v16 berth; "v15-quay": legacy quay block # "v18-modular-adjustable": 190-200 mm adjustable tight U-cradles (stern+mid+bow side cheeks, 24x13.4 mm adjustable socket + reversible gauge sleeves & 1:10 wedges, HULL_CLR=0.12 mm) + OMX base-plate spacer bridges + 2 cm concave belt stopper (Confluence 23592971/23234388); "v15-quay": loose quay fenders
    ship_spacer_dy_mm=32.0,  # nominal lateral gap at 194.0 mm inner wall span (97.0 - 65.0 = 32.0 mm); v18 adjustable bridges span 30.0..35.0 mm (190..200 mm)
    ship_spacer_dx_mm=0.0,   # v18 berth-spacer-bridge-a/b fore-aft alignment (-2 / 0 / +2 mm)
    ship_stern_hook_mm=0.0,  # v18 berth-stern-hook-set table-edge setback (0 / 5 / 10 mm)
    temp_bridge="v7",        # "v7": temp_slot_bridge_a/b 3-prong alignment bridges on PR33_C02_BASE (Confluence 23232928/23233175); "none"
    physics="design",        # a candidate of learning/envs/isaac/cell_physics.yaml (omx_physics.py): servo gains, joint damping, container mass and friction
    preset=None,             # a named bundle of choices, PRESETS (explicit choices win)
    wait_pose="side")        # where an arm waits between steps: "side" = home folded but turned to the belt end, out of the middle band
                             # (D-983: the folded home points its jaw at the middle, and arm_a brushed arm_b's jaw at the stand); "home"
BERTH_V16_SPEC = dict(
    berth_kit="v24-docks",   # "v24-docks": printed black v20 cradle + v24 docks on PR33_C02_BASE + v24 belt stopper; "v18-modular-adjustable"/"v16-modular"/"v17-modular-tight": orange v16 berth; "v15-quay": legacy quay block
    confluence_pages=("23592971", "23234388", "23233175"),
    lift_mm=3.0,
    hull_half_beam_mm=65.0,
    hull_in_cradle_clearance_mm=0.12,
    base_inner_from_axis_mm=71.25,
    base_front_from_axis_mm=75.0,
    base_hole_from_axis_x_mm=62.5,
    base_plate_inner_span_mm=(190.0, 192.0, 194.0, 195.0, 196.0, 198.0, 200.0),
    spacer_dy_nominal_mm=32.0,
    spacer_dy_steps_mm=(30.0, 31.0, 32.0, 32.5, 33.0, 34.0, 35.0),
    spacer_dx_steps_mm=(-2.0, 0.0, 2.0),
    stern_hook_steps_mm=(0.0, 5.0, 10.0),
    big_key_socket_mm=(24.0, 13.4),
    repeatability_rss_mm=0.22,
    max_hull_yaw_deg=0.07,
    belt_concave_stopper=dict(drop_mm=20.0, mouth_mm=62.0, flat_mm=44.0, depth_mm=9.0, wall_mm=3.5, x_back_mm=-7.5, x_front_mm=-16.5),
)
TOP_CAMERA_20261110 = dict(eye=[-.0334, .0493, .6613], focus=[.0804, .0086, .1762], up=[.9737, .0296, .226],
                           f_px=615., width=640, height=480)
TOP_CAMERA_20261112 = dict(eye=[-.056, .075, .6429], focus=[.0437, .0687, .1762], up=[.9735, .0674, .2185],
                           f_px=615., width=640, height=480)
# 2026-11-14 00:57 top frame, one frame: pose fitted (scratch fit, 1.6 px rms over 17 edge points, camera x/y/height/tilt free, f 615 kept, ship yaw 0) to the table's belt-end edge
# (x .155) and left edge (y .277) and the hull's two side edges and stern edge (130 mm beam, z .095). It is not a survey: the same frame puts the hull stern at x .147, y +.0015.
# Restated at the D435 factory f 618.5 (memory d435-depth-via-v4l2) instead of the f 615 the scratch fit kept: the eye moved 3.5 mm up the optical axis, so the
# magnification at the cell plane is unchanged (landmarks at z .017-.095 project within 0.25 px of the f 615 pose), and the refit (omx_real2sim_refit) starts from the same K.
TOP_CAMERA_20261114 = dict(eye=[-.0050, .0869, .6973], focus=[.0469, .0401, .2022], up=[.9943, -.015, .1055],
                           f_px=618.5, width=640, height=480)
# preset="v24-20261114": the cell as the 00:57 and 02:56 top frames show it with the rated v24 berth (Confluence 23234388 v40); explicit choices still win.
# Every item of it is read through TOP_CAMERA_20261114, whose frame hangs on the table's belt-end edge (x .155). Until 11-14 evening the arm bases stayed
# "surveyed" (the 11-03 FK frame, bases .104 / .116): two frames in one map, the ship and plates 26 (arm_b) and 44 mm (arm_a) too far toward -x of the arms.
PRESETS = {"v24-20261114": dict(berth_kit="v24-docks", top_camera="2026-11-14", temp_lanes="photo-20261114", ship_stern_x_m=.1474, ship_centre_y_m=.0015,
                                ship_pose="photo-20261114", arm_bases="docks-photo", belt_pose="photo-20261114")}
# preset "v24-20261114-cad194" (11-14 evening): the same frame and parts, base plates set from the planned 194 mm between the two OMX-AI base plates (user, later that night: the real cell differs, see docks-photo)
# (inner edge to inner edge: the 130 mm hull with its ~32 mm side docks fits only so; as a centre distance the plates would overlap the ship).
PRESETS["v24-20261114-cad194"] = dict(PRESETS["v24-20261114"], arm_bases="cad-194")
# preset "v24-20261114-cad190" (DL-52, 11-14 night): the same, inner gap fixed at 190 mm (the low end of the docks' 190-200 range); cad-190 stays a named preset, not the omx_loop default (the physical cell is 194 mm until the v25 docks are printed).
PRESETS["v24-20261114-cad190"] = dict(PRESETS["v24-20261114"], arm_bases="cad-190")
ARM_BASES_PLATE_CENTRE = dict(arm_a=((.116, -.164), 90.), arm_b=((.107, .164), -90.))  # G-21: top-frame base plate centres vs arm_b FK (.104, .153)
# 2026-11-14 02:56 top frame through TOP_CAMERA_20261114: each PR33_C02_BASE plate's ship-side edge and its two ends along x, picked by eye on 6x crops (+-2 px,
# about +-3 mm), at table + 13 mm; the axis is the edge's middle, 71.25 mm outward. Checks from the same frame: plates 152 and 155 mm long (CAD 150), inner gap
# 189.8 mm (v24 docks 190-200), lane 2 of each plate about 200 mm from its axis (bridge v7: 200); stern minus axis 70 mm (11-10 survey: 74). Yaw nominal.
# x is one value for both arms: each plate's +x edge (.154, .150) less half the CAD length; the 5 mm between the arms is inside the pick error. That edge lies on
# the table edge the camera fit is pinned to, so x is "flush with the table edge", not an independent survey: an arm FK touch on a plate corner would confirm it.
ARM_BASES_PHOTO_1114 = dict(arm_a=((.077, -.1666), 90.), arm_b=((.077, .1656), -90.))
# "cad-194": inner gap 194.0 mm (user) = 2 x (|y_axis| - 71.25 mm, PR33_C02_BASE inner wall from its axis), centred on the hull centreline (ship_centre_y_m .0015); x as photo-20261114
# (plate +x edge flush with the table edge). The 11-14 photo picks gave 189.8 (+-3) by eye, a later row-by-row look about 199 (+-3): 194 is the plan's value, kept as a candidate.
# The docks tie both plates to the hull, so the bases follow the ship wherever it is measured (a snapshot's hull fit too): no marker sheet is on the plates.
# x: the axis lies 70.4 mm toward the bow of the stern end (11-14 frame: stern .1474, plate +x edge flush with the table edge, +-4 mm; the 11-10 survey gave 74).
# "docks-photo" (user, 11-14 night: 194 is the plan, the real cell differs, use what the photo measured): inner gap 189.8 mm read in the 02:56 frame, so the
# axis is 189.8 / 2 + 71.25 = 166.15 mm from the hull centreline. "cad-194" keeps the planned 194 mm as a candidate.
# "cad-190": DL-52 inner gap 190.0 mm, axis 190 / 2 + 71.25 = 166.25 mm from the centreline (docks-photo: 166.15, 0.1 mm apart).
DOCKS = {"cad-190": dict(axis_behind_stern_m=.0704, axis_from_centreline_m=.16625), "cad-194": dict(axis_behind_stern_m=.0704, axis_from_centreline_m=.16825), "docks-photo": dict(axis_behind_stern_m=.0704, axis_from_centreline_m=.16615)}
ARM_BASES_MEASURED_194 = dict(arm_a=((.091, -.16825), 90.), arm_b=((.091, .16825), -90.))  # 193-195 mm (194.0 mm nominal) inner gap between PR33_C02_BASE plates (|y_bp|=97.0 mm -> |y_arm|=168.25 mm)
TEMP_LANES_PHOTO_1110 = dict(a=[((-.0842, -.2271), 17.2), ((-.0933, -.1676), .2), ((-.0846, -.1081), -16.8)],
                             b=[((-.0818, .1073), 16.9), ((-.0906, .1668), -.1), ((-.0817, .2263), -17.1)])
SHIP_PHOTO_1110 = dict(stern_x_m=.178, centre_y_m=-.001)
BELT_PHOTO_1110 = dict(end_x_m=.2115, centre_y_m=-.0226)
# 2026-11-14 02:56 frame: the dark strip's middle between its rails (two rows, -.004 and -.002). The stop is under a container there, so its x stays the fixture's
BELT_PHOTO_1114 = dict(end_x_m=.158, centre_y_m=-.003)
# Lane centre (x, y) m and long-axis yaw deg, lanes numbered as printed on the plates. Dark pads in the surveyed top camera, back-projected to the plate top;
# the pads measured 89 x 30 mm against the 90 x 30 container. tmp-a-3 lay under a container: from lanes 1 and 2, its visible end agrees within 0.1 deg.
# The plates are loose: measure again when one moves.
# the plates on 2026-11-08 22:45: lane pads and containers back-projected through the measured top camera (plate a's lane 3 pad was half seen:
# mirrored from its lane 1 like plate b's fan); yaws in degrees of the container's long axis
# the plates in the 2026-11-14 00:57 top frame through TOP_CAMERA_20261114 (plate shape from the 11-12 snapshot; a: lanes 1-2 from the plate fit, 3 a container; b: lane 2 a container, 1 and 3 plate fit;
# the camera pose is a one-frame fit, so the pad-size check (worst_mm) found too few clean pads to confirm it: treat these as +-5 mm)
TEMP_LANES_PHOTO_1114 = dict(a=[((-.1264, -.2299), 17.6), ((-.1357, -.1711), .4), ((-.1273, -.1121), -16.8)],
                             b=[((-.1116, .1268), 14.6), ((-.1179, .1860), -2.6), ((-.1064, .2445), -19.8)])
TEMP_LANES_PHOTO_1108 = dict(a=[((-.0258, -.2176), 16.7), ((-.0394, -.1620), 0.), ((-.0258, -.1064), -16.7)],
                             b=[((-.0302, .0968), 10.7), ((-.0349, .1482), -1.4), ((-.0281, .1990), -14.4)])
TEMP_LANES_PHOTO = dict(a=[((-.0738, -.2167), 15.7), ((-.0818, -.1672), 2.7), ((-.0776, -.1173), -11.3)],
                        b=[((-.0465, .1439), 4.9), ((-.0466, .1958), -9.7), ((-.0378, .2480), -24.7)])
SCAD = dict(lanes=3, cont_w=.030, cont_l=.090, pk_l=.096, deck_t=.008, clr=.0004, clr_l=.001, seat_h=.0006, catch=.005, gap_min=.0006, rim=.003, yaw_tol_deg=3.)
BELT_STOP_X = .158
ARMS = ("arm_a", "arm_b")  # fixture arm index 0 (y -) and 1 (y +); arm_a does not move in reality (motor 11), it does here
SHIP_ASSETS = ISAAC / "assets/ship_r08_berth"  # made by Rosy/docs/research/ship-modular-2026-11-03/proposals/ship-berth/sim_assets.py (SOURCE.json)
CONTAINER = {"fixture-studs": (.09, .03, .03), "r08-berth": (.09, .02998, .0324)}  # v3 body: 34.4 tall with the top cones, which nest 2 mm: 32.4 per tier
# r08 hold pocket measured on hold-print.stl (top profile): floor z 3, a 0.6 vertical seat at half width 15.7 / half length 45.6 around the
# pocket centre, then a slope rising 4.4 over 2.7 to the deck at 8, ridge 0.5 wide between rows, deck to |y| 63, bulwark to z 11 out to 65 (mm).
HOLD = dict(starts=(50., 148.), length=98., centre=49., rows=(-38., 0., 38.), floor=3., hw=15.7, hl=45.6, seat=.6, catch=2.7, rise=4.4, ridge=.5,
            deck=8., deck_y=63., bulwark=11., half_beam=65.)
SHIP_LENGTH_M = .316  # r08 v15 stern to bow (hull.stl bounds)
STERN_BAY = dict(x=25., floor=6.)  # r08 stern_bay centre x and its floor on the berth (pocket floor 3 + lift 3), mm
# r08 stern around the empty bay, from the r08 README table (fender face x 0-5 at deck 8, bay mouth x 6.5-43.5 with floor 3, side rails
# x 12-50 at 11) plus the 3 mm berth lift: boxes (x0, x1, y0, y1, z top) in ship mm; y0 = -y1 is one box across, else mirrored to both sides.
STERN = dict(boxes=((0., 50., -65., 65., 6.), (0., 6.5, -65., 65., 11.), (43.5, 50., -65., 65., 11.), (6.5, 43.5, 45.6, 63., 11.),
                    (12., 50., 63., 65., 14.)))


# Only hold 1 (next to the stern) is in reach with the stern at the table edge: hold 2 lies behind both arms, where no tool-down pose holds a
# container along x (validator, stern x .155 to .215). So the stack is hold 1, 3 rows x 3 tiers, middle row first, in the stud plan's arm order.
# arm_b's wrist camera as the real frame shows it (2026-11-08 22:30, arm at rest, the jaw silhouette traced and matched in MuJoCo with the
# jaw opening fitted too, IoU 0.15 -> 0.68): 16 mm higher and 8 mm to the side of the D r06 CAD, the axis meeting the jaw axis 25 mm further
# out, about the same 34 deg down. One frame at one pose: lens height and aim trade off; refit on frames at other poses.
WRIST_PHOTO = dict(lens_m=[.0338, .008, .0671], axis_hit_x_m=.1328)
WRIST_PHOTO_A = dict(lens_m=[.0528, .005, .0641], axis_hit_x_m=.145)  # arm_a 2026-11-10 wrist frame jaw silhouette fit (IoU 0.18 -> 0.39, G-24)
TEMP_TIERS = 3  # plate v11: 3 lanes x 3 tiers (Confluence 15368863); tier 0 keeps the lane's name, tier k is "<lane>-l<k>"
R08_TIERS = 3 # the cell stacks three high (user, 11-08); the slot map lists tiers 82 and 84, the third sits one container (32.4 mm) higher
R08_TIER_STEP = 32.4
R08_STACK = tuple((f"bar-{3 * layer + k + 1}", f"ship-h1r{row}-l{layer}", arm) for layer in range(R08_TIERS)
                  for k, (row, arm) in enumerate(((1, "arm_b"), (0, "arm_a"), (2, "arm_b"))))
_WAIT_POSE_CACHE: dict[tuple, np.ndarray] = {}
_SNAPSHOT_CACHE: dict[tuple[str, int, int], dict] = {}


def wait_pose(arm, kind):
    """Joints an arm waits in: the folded home, or ("side") the same fold with joint1 turned a quarter so the jaw points at the belt end
    (+x) and nothing of the arm stays in the middle band between the arms."""
    key = (arm.name, tuple(arm.limits[4]), tuple(arm.home), kind,
           tuple(arm.base), arm.yaw, tuple(arm.tcp))
    if key in _WAIT_POSE_CACHE:
        return _WAIT_POSE_CACHE[key].copy()
    if kind == "home":
        _WAIT_POSE_CACHE[key] = arm.home.copy()
        return _WAIT_POSE_CACHE[key].copy()
    import palletizing_gripper as jaw
    turned = [arm.home.copy() for _ in (1, -1)]
    for q, sign in zip(turned, (1, -1)):
        q[0] += sign * math.pi / 2
    q = max(turned, key=lambda q: arm.segments(q)[-1][0])
    # the wrist roll that turns the camera holder (55 mm to one side of link5) away from the middle: arm_b's faced it and met arm_a's
    # holder over the stern stand (MuJoCo 2026-11-08)
    lens = np.array(jaw.WRIST_CAMERA_B["lens_m"])
    rolls = [r for r in (q[4], q[4] - math.pi, q[4] + math.pi) if arm.limits[4][0] <= r <= arm.limits[4][1]]

    def outward(r):
        R, p = arm.link_poses(np.r_[q[:4], r, q[5:]])[4]
        return abs((p + R @ lens)[1])
    q[4] = max(rolls, key=outward)
    _WAIT_POSE_CACHE[key] = q.copy()
    return q.copy()


def ship_cell(layout, x_mm, y_mm, z_mm=0.):
    """r08 ship coordinates (mm: x from the stern end, y to port, z from the table) to the fixture frame: the bow points -x."""
    c = layout.choices
    return c["ship_stern_x_m"] - x_mm / 1000, c["ship_centre_y_m"] - y_mm / 1000, layout.table_z + z_mm / 1000


@functools.lru_cache(maxsize=1)
def _r08_slot_groups():
    records = json.loads((SHIP_ASSETS / "slots.json").read_text(encoding="utf-8"))["tier_records"]
    cells = {}
    for r in records:
        cells.setdefault((r["module_index"], r["y_mm"], r["tier"]), []).append(r)
    rows = sorted({y for _, y, _ in cells}, reverse=True)  # fixture y ascends as ship y descends
    tiers = sorted({t for _, _, t in cells})
    holds = sorted({m for m, _, _ in cells})
    groups = []
    for (module, y, tier), group in cells.items():
        assert len(group) == 3, (module, y, tier)
        if tier != tiers[0]:
            continue
        h, row = holds.index(module) + 1, rows.index(y)
        groups.append((h, row, sum(g["x_mm"] for g in group) / 3.0, y, group[0]["z_mm"],
                       tuple(tuple(g["id"][:4] + str(tier + 2 * layer) for g in group) for layer in range(R08_TIERS))))
    return tuple(groups)


def r08_sites(layout):
    """1x3 sites of the berthed r08 ship from its slot map: one per hold, row and tier, the mean of the three 1x1 cells.
    Rows are numbered by fixture y (r0 nearest arm_a, as the stud plate's rows); layer 0, 1, 2 are tiers 82, 84 and 86 (R08_TIERS)."""
    out = {}
    for h, row, mean_x_mm, y, z0_mm, layered_slot_ids in _r08_slot_groups():
        x, cy, z = ship_cell(layout, mean_x_mm, y, z0_mm)
        for layer in range(R08_TIERS):
            out[f"ship-h{h}r{row}-l{layer}"] = dict(kind="ship", xy=(x, cy), z=z + layout.box[2] * (layer + .5), yaw=0., row=row, layer=layer,
                                                    stack=f"h{h}r{row}", slots=list(layered_slot_ids[layer]))
    # The stern bay is not a place (site map decision 2026-11-17); STERN_BAY stays as berth geometry. Outbound is the separate stand
    # (r05 chute, arm_a only), which has no sim place until it is measured.
    return out


def under_hull(layout, site):
    """True when a container seated on `site` would reach over the r08 hull (stern to bow, beam 130 mm): plate v11 where its bridge
    seats it overlaps the estimated ship by up to 20 mm at arm_b (the base plate yaw, arm_b's axis and the ship's place are unmeasured).
    shortcut: container corners against the hull's bounding box, enough while the hull's sides are straight there; upgrade with the hull mesh."""
    c = layout.choices
    x1, y0 = c["ship_stern_x_m"], c["ship_centre_y_m"]
    long, side = (math.cos(site["yaw"]), math.sin(site["yaw"])), (-math.sin(site["yaw"]), math.cos(site["yaw"]))
    for a in (-1, 1):
        for b in (-1, 1):
            x = site["xy"][0] + a * layout.box[0] / 2 * long[0] + b * layout.box[1] / 2 * side[0]
            y = site["xy"][1] + a * layout.box[0] / 2 * long[1] + b * layout.box[1] / 2 * side[1]
            if x1 - SHIP_LENGTH_M <= x <= x1 and abs(y - y0) <= HOLD["half_beam"] / 1000:
                return True
    return False


def lane_geometry(radius):
    """SCAD v11 fan: (pocket width, pocket length, flare, fan angle rad, lane angles). Lane i is rotated by -angle about the arm centre.
    The pocket is three 1x1 cells at pitch 32 (pk_l 96, v9 on), so the fan is 17.3 deg at arm_r 200."""
    s = SCAD
    width, length = s["cont_w"] + 2 * s["clr"], s["pk_l"]
    flare = length / 2 * math.tan(math.radians(s["yaw_tol_deg"]))
    fan = 2 * math.asin((width + 2 * flare + s["gap_min"]) / 2 / (radius - length / 2))
    return width, length, flare, fan, [(i - (s["lanes"] - 1) / 2) * fan for i in range(s["lanes"])]



def parse_choices(items):
    """--choice key=value items into CHOICES overrides, numbers as numbers."""
    out = {}
    for item in items or []:
        key, value = item.split("=", 1)
        try:
            out[key] = json.loads(value) if value[:1] in "0123456789-." else value
        except ValueError:  # a date such as 2026-11-14 is a name, not a number
            out[key] = value
    return out


def load_snapshot(path):
    if not path:
        raise ValueError('a "snapshot" choice needs cell_snapshot=PATH')
    resolved = (Path(__file__).resolve().parents[2] / path).resolve()  # a relative path is from the repo root
    if resolved.exists():
        stat = resolved.stat()
        key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        if key not in _SNAPSHOT_CACHE:
            _SNAPSHOT_CACHE[key] = json.loads(resolved.read_text(encoding="utf-8"))
        return copy.deepcopy(_SNAPSHOT_CACHE[key])
    return json.loads(resolved.read_text(encoding="utf-8"))


def snapshot_lanes(path, tag):
    """[(xy, yaw rad)] of lanes 1..3 of plate `tag` in a cell snapshot (omx_real2sim.py); a plate it could not measure is refused."""
    snap = load_snapshot(path)
    lanes = {l["lane"]: l for l in snap["items"]["temp_plates"]["plates"].get(tag, [])}
    if sorted(lanes) != [1, 2, 3]:
        raise ValueError(f"snapshot {path}: plate {tag} has lanes {sorted(lanes)}, not 1-3")
    return [(tuple(lanes[i]["xy"]), math.radians(lanes[i]["yaw_deg"])) for i in (1, 2, 3)]


def temp_lanes(arm_xy, radius, direction_deg):
    """Lane centres and container yaws of one temporary plate: [(xy, yaw rad)], plate centre. The container long axis points at the arm centre."""
    d = (math.cos(math.radians(direction_deg)), math.sin(math.radians(direction_deg)))
    x_loc = (d[1], -d[0])  # plate x = line of the arms, y = away from the arm; right-handed with z up
    lanes = []
    for angle in lane_geometry(radius)[4]:
        c, s = math.cos(-angle), math.sin(-angle)
        u, v = -s * radius, c * radius  # (0, r) turned by -angle, relative to the arm centre (plate local)
        lanes.append(((arm_xy[0] + u * x_loc[0] + v * d[0], arm_xy[1] + u * x_loc[1] + v * d[1]),
                      math.atan2(-s * x_loc[1] + c * d[1], -s * x_loc[0] + c * d[0])))
    centre = (arm_xy[0] + radius * d[0], arm_xy[1] + radius * d[1])
    return lanes, centre


def hull(points):
    """Convex hull, counter-clockwise (monotone chain)."""
    pts = sorted(set(points))
    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]
    return half(pts) + half(pts[::-1])


def plate_outline(lanes, radius):
    """Deck outline (hull of the three lane rectangles, SCAD ow x ol) around the lane centres."""
    s = SCAD
    width, length, flare, _, _ = lane_geometry(radius)
    ow, ol = width + 2 * flare + 2 * s["catch"] + 2 * s["rim"], length + 2 * s["catch"] + 2 * s["rim"]
    corners = []
    for (x, y), yaw in lanes:
        long, side = (math.cos(yaw), math.sin(yaw)), (-math.sin(yaw), math.cos(yaw))
        corners += [(x + a * ol / 2 * long[0] + b * ow / 2 * side[0], y + a * ol / 2 * long[1] + b * ow / 2 * side[1]) for a in (-1, 1) for b in (-1, 1)]
    return hull(corners)


class Layout:
    """Arms and sites for one set of CHOICES. sites[name] = dict(kind, xy, z (container centre when seated), yaw, ...)."""

    def __init__(self, **choices):
        self.choices = dict(CHOICES, **dict(PRESETS.get(choices.get("preset"), {}), **choices))
        c = self.choices
        self.fixture = f = fx.container_fixture(layers=3, case=c["fixture_case"])
        if c["top_camera"] == "snapshot":  # the pose omx_real2sim.py measure refitted (camera_fit gated), never an unfitted one
            snap_cam = load_snapshot(c["cell_snapshot"])
            fit = snap_cam.get("camera_fit")  # None: the pad check passed and the camera had not moved, so the snapshot's pose stands
            if (fit and not fit.get("ok")) or (fit is None and (snap_cam.get("camera_motion") or {}).get("moved")) or not isinstance(snap_cam.get("camera", {}).get("top"), dict):
                raise ValueError(f"snapshot {c['cell_snapshot']}: no accepted top camera fit ({(fit or {}).get('why', 'camera moved, not refitted')})")
            f["real_cameras"] = dict(f["real_cameras"], top=dict(snap_cam["camera"]["top"]))
        elif c["top_camera"] == "2026-11-14":
            f["real_cameras"] = dict(f["real_cameras"], top=dict(TOP_CAMERA_20261114))
        elif c["top_camera"] == "2026-11-12":
            f["real_cameras"] = dict(f["real_cameras"], top=dict(TOP_CAMERA_20261112))
        elif c["top_camera"] == "2026-11-10" and ("top_camera" in choices or c["temp_lanes"] != "photo-20261107"):
            f["real_cameras"] = dict(f["real_cameras"], top=dict(TOP_CAMERA_20261110))
        self.table_z = f["workplate_center_m"][2] + f["workplate_size_m"][2] / 2
        self.deck_z = ship_plate.top_z(f)
        self.arms, self.sim_arms, self.plates = {}, {}, {}
        self.roll_floor = float(kin.norm_to_rad(c["roll_floor_norm"]))
        if c["arm_bases"] in DOCKS:  # the bases hang on the ship: a measured ship pose is needed before the arms are placed (set again below, the same values)
            if c["ship_pose"] == "photo-20261110":
                c["ship_stern_x_m"], c["ship_centre_y_m"] = SHIP_PHOTO_1110["stern_x_m"], SHIP_PHOTO_1110["centre_y_m"]
            elif c["ship_pose"] == "snapshot":
                ship = load_snapshot(c["cell_snapshot"])["items"].get("ship") or {}
                if "stern_x_m" in ship:
                    c["ship_stern_x_m"], c["ship_centre_y_m"] = ship["stern_x_m"], ship["centre_y_m"]
        for k, name in enumerate(ARMS):
            z = self.table_z + .012 if c["base_z"] == "measured" else f["arm_bases_m"][k][2]
            xy, yaw_rad = f["arm_bases_m"][k][:2], f["arm_base_yaws_rad"][k]
            if c["arm_bases"] == "plate-centre":
                xy, yaw_deg = ARM_BASES_PLATE_CENTRE[name]
                yaw_rad = math.radians(yaw_deg)
            elif c["arm_bases"] in DOCKS:
                d = DOCKS[c["arm_bases"]]
                sign = -1. if name == "arm_a" else 1.
                xy, yaw_rad = (c["ship_stern_x_m"] - d["axis_behind_stern_m"], c["ship_centre_y_m"] + sign * d["axis_from_centreline_m"]), -sign * math.pi / 2
            elif c["arm_bases"] in ("measured-194", "photo-20261114"):
                xy, yaw_deg = dict({"measured-194": ARM_BASES_MEASURED_194, "photo-20261114": ARM_BASES_PHOTO_1114})[c["arm_bases"]][name]
                yaw_rad = math.radians(yaw_deg)
            elif str(c["arm_bases"]).startswith("span-"):
                span_mm = float(str(c["arm_bases"]).split("-", 1)[1])
                y_arm_m = (span_mm / 2.0 + BERTH_V16_SPEC["base_inner_from_axis_mm"]) / 1000.0
                sgn = -1.0 if name == "arm_a" else +1.0
                xy = (.091, sgn * y_arm_m)
                yaw_rad = math.radians(90.0 if name == "arm_a" else -90.0)
            elif c["arm_bases"] == "snapshot":
                ab = (load_snapshot(c["cell_snapshot"])["items"].get("arm_bases") or {}).get("plate_centre", {}).get(name)
                if not ab or "xy" not in ab:
                    raise ValueError(f"snapshot {c['cell_snapshot']}: no arm_bases for {name}")
                xy, yaw_rad = tuple(ab["xy"]), math.radians(ab["yaw_deg"])
            for table, tcp in ((self.arms, c["tcp_x_" + name[-5:]]), (self.sim_arms, c["sim_tcp_x_m"])):
                table[name] = arm = kin.Arm(name, (*xy, z), yaw_rad, tcp_x=tcp)
                arm.wait = wait_pose(arm, c["wait_pose"])
        belt_top = self.table_z - .055 if c["belt_height"] == "ruler" else f["pickup_center_m"][2] - .015
        self.belt_top = belt_top
        self.belt_stop_x, self.belt_y = BELT_STOP_X, f["pickup_center_m"][1]
        if c["belt_pose"] in ("photo-20261110", "photo-20261114"):
            photo = BELT_PHOTO_1110 if c["belt_pose"] == "photo-20261110" else BELT_PHOTO_1114
            self.belt_stop_x, self.belt_y = photo["end_x_m"], photo["centre_y_m"]
        elif c["belt_pose"] == "snapshot":
            belt = load_snapshot(c["cell_snapshot"])["items"].get("belt") or {}
            if "end_x_m" not in belt:
                raise ValueError(f"snapshot {c['cell_snapshot']}: no measured belt ({belt.get('error', 'item missing')})")
            self.belt_y = belt["centre_y_m"]
            if not belt.get("end_occluded"):  # a container at the stop hid the strip's end: the stop keeps the fixture's x
                self.belt_stop_x = belt["end_x_m"]
        self.box = CONTAINER[c["ship_source"]]
        pick_x = self.belt_stop_x + f["pickup_center_m"][0] - BELT_STOP_X  # the container waits as far past the stop as in the fixture
        self.sites = {"belt": dict(kind="belt", xy=(pick_x, self.belt_y), z=belt_top + self.box[2] / 2 + .0005, yaw=0.)}
        if c["ship_pose"] == "photo-20261110":
            c["ship_stern_x_m"], c["ship_centre_y_m"] = SHIP_PHOTO_1110["stern_x_m"], SHIP_PHOTO_1110["centre_y_m"]
        elif c["ship_pose"] == "berth-v16":
            y_inner_a = self.arms["arm_a"].base[1] + BERTH_V16_SPEC["base_inner_from_axis_mm"] / 1000.0
            y_inner_b = self.arms["arm_b"].base[1] - BERTH_V16_SPEC["base_inner_from_axis_mm"] / 1000.0
            c["ship_centre_y_m"] = round((y_inner_a + y_inner_b) / 2.0, 4)
            c["ship_stern_x_m"] = round(.155 + (float(c["ship_spacer_dx_mm"]) - float(c["ship_stern_hook_mm"])) / 1000.0, 4)
        elif c["ship_pose"] == "snapshot":
            ship = load_snapshot(c["cell_snapshot"])["items"].get("ship") or {}
            if "stern_x_m" not in ship:
                raise ValueError(f"snapshot {c['cell_snapshot']}: no measured ship ({ship.get('error', 'item missing')})")
            c["ship_stern_x_m"], c["ship_centre_y_m"] = ship["stern_x_m"], ship["centre_y_m"]
        if c["ship_source"] == "r08-berth":
            self.sites.update(r08_sites(self))
        else:
            for item in fx.plan(True, fixture=f):
                row, layer = item["cell"][1], item["cell"][2]
                self.sites[f"ship-r{row}-l{layer}"] = dict(kind="ship", xy=tuple(item["target"][:2]), z=item["target"][2], yaw=0.,
                                                           arm=ARMS[item["arm"]], item=item["id"], row=row, layer=layer, stack=f"r{row}")
        for tag, name in (("a", "arm_a"), ("b", "arm_b")):
            if c["temp_lanes"] == "fan":
                lanes, centre = temp_lanes(self.arms[name].base[:2], c["temp_radius_m"], c["temp_direction_deg"])
            elif c["temp_lanes"] == "snapshot":
                lanes = snapshot_lanes(c["cell_snapshot"], tag)
                centre = lanes[1][0]
            else:
                photo = (TEMP_LANES_PHOTO_1114 if c["temp_lanes"] == "photo-20261114" else TEMP_LANES_PHOTO_1110 if c["temp_lanes"] == "photo-20261110"
                         else TEMP_LANES_PHOTO_1108 if c["temp_lanes"] == "photo-20261108" else TEMP_LANES_PHOTO)
                lanes = [(xy, math.radians(yaw)) for xy, yaw in photo[tag]]
                centre = lanes[1][0]
            self.plates[tag] = dict(arm=name, centre=centre, lanes=lanes, outline=plate_outline(lanes, c["temp_radius_m"]))
            for i, (xy, yaw) in enumerate(lanes, 1):
                for layer in range(TEMP_TIERS):
                    self.sites[f"tmp-{tag}-{i}" + (f"-l{layer}" if layer else "")] = dict(
                        kind="temp", xy=xy, z=self.deck_z + self.box[2] * (layer + .5), yaw=yaw, plate=tag, lane=i, layer=layer, stack=f"tmp-{tag}-{i}")
        self.ship_xy = {n: s["xy"] for n, s in self.sites.items() if s["kind"] == "ship"}
        self.stack_at = {(s["stack"], s["layer"]): n for n, s in self.sites.items() if "stack" in s}  # what stands on what, ship and plates
        if c["ship_source"] == "r08-berth":
            for s in self.sites.values():
                if s["kind"] == "temp" and under_hull(self, s):
                    s["blocked"] = "under the ship hull"

    def containers(self):
        """The container ids of the stack plan, in plan order, with the arm the plan gave each."""
        return [(c, arm) for c, _, arm in self.plan_order()]

    def plan_order(self):
        """Stack plan order as (container, ship site, arm): the fixture plan on the stud plate, R08_STACK on the r08 ship."""
        if self.choices["ship_source"] == "r08-berth":
            return list(R08_STACK)
        return [(i["id"], f"ship-r{i['cell'][1]}-l{i['cell'][2]}", ARMS[i["arm"]]) for i in fx.plan(True, fixture=self.fixture)]

    @property
    def hold_below(self):
        """Held container centre under the TCP: 2.01 mm for the 30 mm box (Isaac hold check), held as deep under its top for a taller one
        (v3 at the old centre lifted its top 1.2 mm nearer link5, which hit it in the carry)."""
        return .00201 + (self.box[2] - .03) / 2

    def hold_z(self, site):
        """TCP height that centres a held container on the site."""
        return self.sites[site]["z"] + self.hold_below

    def ship_fixation(self, ship_yaw_deg=0.0):
        """v16 berth-modular fixation geometry between OMX-AI base plates (PR33_C02_BASE), r08 hull, and concave belt stopper."""
        c, spec = self.choices, BERTH_V16_SPEC
        hb, bi, steps, stp = spec["hull_half_beam_mm"] / 1000.0, spec["base_inner_from_axis_mm"] / 1000.0, spec["spacer_dy_steps_mm"], spec["belt_concave_stopper"]
        gap_a = round(((c["ship_centre_y_m"] - hb) - (self.arms["arm_a"].base[1] + bi)) * 1000.0, 2)
        gap_b = round(((self.arms["arm_b"].base[1] - bi) - (c["ship_centre_y_m"] + hb)) * 1000.0, 2)
        flat_x = round(c["ship_stern_x_m"] - stp["x_back_mm"] / 1000.0, 4)
        tip_x = round(c["ship_stern_x_m"] - stp["x_front_mm"] / 1000.0, 4)
        return dict(
            berth_kit=c.get("berth_kit", "v16-modular"), temp_bridge=c.get("temp_bridge", "v7"),
            spacer_dy_nominal_mm=float(c.get("ship_spacer_dy_mm", 39.0)), spacer_dx_mm=float(c.get("ship_spacer_dx_mm", 0.0)),
            stern_hook_mm=float(c.get("ship_stern_hook_mm", 0.0)), arm_a_gap_dy_mm=gap_a, arm_b_gap_dy_mm=gap_b,
            nearest_spacer_step_mm=dict(arm_a=min(steps, key=lambda s: abs(s - gap_a)), arm_b=min(steps, key=lambda s: abs(s - gap_b))),
            hull_yaw_deg=round(float(ship_yaw_deg), 2), within_v16_yaw_budget=abs(float(ship_yaw_deg)) <= spec["max_hull_yaw_deg"] + 0.5,
            stopper_flat_x_m=flat_x, stopper_tip_x_m=tip_x, belt_to_stopper_flat_mm=round((self.belt_stop_x - flat_x) * 1000.0, 1),
            repeatability_rss_mm=spec["repeatability_rss_mm"],
        )
