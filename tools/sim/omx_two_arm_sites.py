"""Two-arm OMX cell layout without MuJoCo: arm bases, belt end, ship cells and the two temporary slot plates, in the fixture frame.

Every number comes from an existing module (mapped_stack_fixture, ship_plate, palletizing_gripper, cell_model_inventory.yaml) or from the
temp_slot_plate v11 SCAD parameters (Confluence 15368863 and set page 23233175: the bridge v7 seats each plate 200 mm from its arm, toward -x). Where CAD and
a measurement both exist the choice is a named entry of CHOICES (D-947 2: candidates compared by results, nothing silently overwritten).
"""
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
    temp_lanes="photo-20261108",  # "photo-20261108": the plates where the 11-08 top frame sees them (the user moves them by hand for now);
                             # "fan": temp_radius_m and temp_direction_deg, where the bridge v7 seats plate v11 (Confluence 23233175; the user keeps
                             # the arm freer without it, 11-09); "photo-20261107": the older loose v7 plates (use temp_radius_m=.214)
    temp_radius_m=.150,      # SCAD arm_r: the printed fan's shape, and with temp_lanes="fan" arm centre to middle-lane centre (v9 to v11: 200;
                             # the 11-08 plates' middle lanes lie 139 and 155 mm from arm_b and arm_a)
    temp_direction_deg=180., # from each arm toward -x, away from the belt (the user's slot plan 2026-10-31)
    temp_source="scad-v11",  # the plate source; "stl" keeps the same collision shape and shows the downloaded STL as the visual
    ship_source="r08-berth",  # "r08-berth": the rated ship v15 (r08) on its berth kit with container v3 (SHIP_ASSETS); "fixture-studs": the old stud plate and 30 mm boxes
    ship_stern_x_m=.155,     # r08: stern end x, bow toward -x as the printed ship lay in the 11-07 top photo; ASSUMED at the table's belt edge (r08 not placed yet)
    ship_centre_y_m=-.014,   # r08: hull centreline y, the middle row of the 11-08 top frame (rows +25/-14/-56 mm; was .007, the 11-07 photo's hull
                             # edges). Its x reading (holds 25 mm toward the belt) would put the stern over the belt end: x stays
    wrist_camera="photo-20261108",  # "photo-20261108": WRIST_PHOTO, fitted to arm_b's real wrist frame; "v21-b": the team's printed D holder r06
                             # (palletizing_gripper.WRIST_CAMERA_B); both draw and collide link5 as the D parts; "stock" (omx-ai-stock, ROBOTIS STEP) or "none"; arm_a ASSUMED the same mount
    tcp_x_arm_b=.0740,       # URDF/STL v2.1 jaw (tip 74.1 mm from the pivot); a touch gave .0885 but that rests on an unchecked table height (OPEN, 14.5 mm FK offset)
    tcp_x_arm_a=.0740,       # same jaw, not confirmed on arm_a separately
    sim_tcp_x_m=.0740,       # the MuJoCo pads are the repo's v2.1 STL, whose TCP is .0740: the teacher grasps with this one (STL may not match the installed jaws)
    roll_floor_norm=-18.,    # usable wrist roll floor in the norm unit (coordinator): a step whose joint5 goes below it is flagged
    ship_pose="assumed",     # "assumed": ship_stern_x_m and ship_centre_y_m above; "snapshot": the hull fitted in cell_snapshot's top frame
    cell_snapshot=None,      # with temp_lanes="snapshot": a rosy.omx-cell-snapshot.v1 file (omx_real2sim.py measure), the lanes the top camera saw then
    wait_pose="side")        # where an arm waits between steps: "side" = home folded but turned to the belt end, out of the middle band
                             # (D-983: the folded home points its jaw at the middle, and arm_a brushed arm_b's jaw at the stand); "home"
# Lane centre (x, y) m and long-axis yaw deg, lanes numbered as printed on the plates. Dark pads in the surveyed top camera, back-projected to the plate top;
# the pads measured 89 x 30 mm against the 90 x 30 container. tmp-a-3 lay under a container: from lanes 1 and 2, its visible end agrees within 0.1 deg.
# The plates are loose: measure again when one moves.
# the plates on 2026-11-08 22:45: lane pads and containers back-projected through the measured top camera (plate a's lane 3 pad was half seen:
# mirrored from its lane 1 like plate b's fan); yaws in degrees of the container's long axis
TEMP_LANES_PHOTO_1108 = dict(a=[((-.0258, -.2176), 16.7), ((-.0394, -.1620), 0.), ((-.0258, -.1064), -16.7)],
                             b=[((-.0302, .0968), 10.7), ((-.0349, .1482), -1.4), ((-.0281, .1990), -14.4)])
TEMP_LANES_PHOTO = dict(a=[((-.0738, -.2167), 15.7), ((-.0818, -.1672), 2.7), ((-.0776, -.1173), -11.3)],
                        b=[((-.0465, .1439), 4.9), ((-.0466, .1958), -9.7), ((-.0378, .2480), -24.7)])
SCAD = dict(lanes=3, cont_w=.030, cont_l=.090, pk_l=.096, deck_t=.008, clr=.0004, clr_l=.001, seat_h=.0006, catch=.005, gap_min=.010, rim=.003, yaw_tol_deg=3.)
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
TEMP_TIERS = 3  # plate v11: 3 lanes x 3 tiers (Confluence 15368863); tier 0 keeps the lane's name, tier k is "<lane>-l<k>"
R08_TIERS = 3 # the cell stacks three high (user, 11-08); the slot map lists tiers 82 and 84, the third sits one container (32.4 mm) higher
R08_STACK = tuple((f"bar-{3 * layer + k + 1}", f"ship-h1r{row}-l{layer}", arm) for layer in range(R08_TIERS)
                  for k, (row, arm) in enumerate(((1, "arm_b"), (0, "arm_a"), (2, "arm_b"))))


def wait_pose(arm, kind):
    """Joints an arm waits in: the folded home, or ("side") the same fold with joint1 turned a quarter so the jaw points at the belt end
    (+x) and nothing of the arm stays in the middle band between the arms."""
    if kind == "home":
        return arm.home.copy()
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
    return q


def ship_cell(layout, x_mm, y_mm, z_mm=0.):
    """r08 ship coordinates (mm: x from the stern end, y to port, z from the table) to the fixture frame: the bow points -x."""
    c = layout.choices
    return c["ship_stern_x_m"] - x_mm / 1000, c["ship_centre_y_m"] - y_mm / 1000, layout.table_z + z_mm / 1000


def r08_sites(layout):
    """1x3 sites of the berthed r08 ship from its slot map: one per hold, row and tier, the mean of the three 1x1 cells.
    Rows are numbered by fixture y (r0 nearest arm_a, as the stud plate's rows); layer 0, 1, 2 are tiers 82, 84 and 86 (R08_TIERS)."""
    records = json.loads((SHIP_ASSETS / "slots.json").read_text(encoding="utf-8"))["tier_records"]
    cells = {}
    for r in records:
        cells.setdefault((r["module_index"], r["y_mm"], r["tier"]), []).append(r)
    rows = sorted({y for _, y, _ in cells}, reverse=True)  # fixture y ascends as ship y descends
    tiers = sorted({t for _, _, t in cells})
    holds = sorted({m for m, _, _ in cells})
    out = {}
    for (module, y, tier), group in cells.items():
        assert len(group) == 3, (module, y, tier)
        if tier != tiers[0]:
            continue
        h, row = holds.index(module) + 1, rows.index(y)
        x, cy, z = ship_cell(layout, sum(g["x_mm"] for g in group) / 3, y, group[0]["z_mm"])
        for layer in range(R08_TIERS):
            out[f"ship-h{h}r{row}-l{layer}"] = dict(kind="ship", xy=(x, cy), z=z + layout.box[2] * (layer + .5), yaw=0., row=row, layer=layer,
                                                    stack=f"h{h}r{row}", slots=[g["id"][:4] + str(tier + 2 * layer) for g in group])
    # The stern bay, kept low (the low kit: no funnel tile, nothing standing in it), is one more ship place: one 1x3 across the beam that
    # both arms reach. The outbound place is a lane of a temporary plate (set page 23233175, 2026-11-08), not this bay.
    x, cy, z = ship_cell(layout, STERN_BAY["x"], 0, STERN_BAY["floor"])
    out["ship-stern-l0"] = dict(kind="ship", xy=(x, cy), z=z + layout.box[2] / 2, yaw=math.pi / 2, row=1, layer=0, stack="stern", slots=[])
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
        out[key] = json.loads(value) if value[:1] in "0123456789-." else value
    return out


def load_snapshot(path):
    if not path:
        raise ValueError('a "snapshot" choice needs cell_snapshot=PATH')
    return json.loads((Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8"))  # a relative path is from the repo root


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
        self.choices = dict(CHOICES, **choices)
        c = self.choices
        self.fixture = f = fx.container_fixture(layers=3, case=c["fixture_case"])
        self.table_z = f["workplate_center_m"][2] + f["workplate_size_m"][2] / 2
        self.deck_z = ship_plate.top_z(f)
        self.arms, self.sim_arms, self.plates = {}, {}, {}
        self.roll_floor = float(kin.norm_to_rad(c["roll_floor_norm"]))
        for k, name in enumerate(ARMS):
            z = self.table_z + .012 if c["base_z"] == "measured" else f["arm_bases_m"][k][2]
            for table, tcp in ((self.arms, c["tcp_x_" + name[-5:]]), (self.sim_arms, c["sim_tcp_x_m"])):
                table[name] = arm = kin.Arm(name, (*f["arm_bases_m"][k][:2], z), f["arm_base_yaws_rad"][k], tcp_x=tcp)
                arm.wait = wait_pose(arm, c["wait_pose"])
        belt_top = self.table_z - .055 if c["belt_height"] == "ruler" else f["pickup_center_m"][2] - .015
        self.belt_top = belt_top
        self.box = CONTAINER[c["ship_source"]]
        self.sites = {"belt": dict(kind="belt", xy=tuple(f["pickup_center_m"][:2]), z=belt_top + self.box[2] / 2 + .0005, yaw=0.)}
        if c["ship_pose"] == "snapshot":
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
                photo = TEMP_LANES_PHOTO_1108 if c["temp_lanes"] == "photo-20261108" else TEMP_LANES_PHOTO
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
