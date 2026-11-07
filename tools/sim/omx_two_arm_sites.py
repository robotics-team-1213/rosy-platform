"""Two-arm OMX cell layout without MuJoCo: arm bases, belt end, ship cells and the two temporary slot plates, in the fixture frame.

Every number comes from an existing module (mapped_stack_fixture, ship_plate, palletizing_gripper, cell_model_inventory.yaml) or from the
temp_slot_plate v7 SCAD parameters (Confluence 15368863; arm-to-plate 214 mm is a photo estimate, candidates 155 to 273 mm). Where CAD and
a measurement both exist the choice is a named entry of CHOICES (D-947 2: candidates compared by results, nothing silently overwritten).
"""
import json
import math
from pathlib import Path
import sys

ISAAC = Path(__file__).resolve().parents[2] / "learning/envs/isaac"
sys.path.insert(0, str(ISAAC))
import mapped_stack_fixture as fx  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402
import ship_plate  # noqa: E402

CHOICES = dict(
    fixture_case="nominal-palletizing-v21-ship-surveyed",  # measured arm bases (arm_b FK, arm_a plate centre); "nominal-palletizing-v21-ship" = CAD bases
    base_z="measured",       # "measured": table + 12 mm base plate (ruler, arm_b; arm_a ASSUMED the same); "cad": the fixture's arm base z
    belt_height="ruler",     # "ruler": belt end surface 55 mm under the table (inventory, D435 says 56); "fixture": the surveyed case's belt_drop face
    temp_lanes="photo-20261107",  # "photo-20261107": TEMP_LANES_PHOTO, the plates where the top camera saw them; "fan": temp_radius_m and temp_direction_deg
    temp_radius_m=.214,      # SCAD arm_r: the printed fan's shape, and with temp_lanes="fan" arm centre to plate centre
    temp_direction_deg=180., # from each arm toward -x, away from the belt (the user's slot plan 2026-10-31)
    temp_source="scad-v7",   # the plate source; "stl" keeps the same collision shape and shows the downloaded STL as the visual
    ship_source="r08-berth",  # "r08-berth": the rated ship v15 (r08) on its berth kit with container v3 (SHIP_ASSETS); "fixture-studs": the old stud plate and 30 mm boxes
    ship_stern_x_m=.155,     # r08: stern end x, bow toward -x as the printed ship lay in the 11-07 top photo; ASSUMED at the table's belt edge (r08 not placed yet)
    ship_centre_y_m=.007,    # r08: hull centreline y, the printed ship's hull edges back-projected from the same photo (125 mm wide against 130)
    wrist_camera="v21-b",    # "v21-b": the team's printed D holder r06 (palletizing_gripper.WRIST_CAMERA_B, link5 drawn and collided as its parts); "stock" (omx-ai-stock, ROBOTIS STEP) or "none"; arm_a ASSUMED the same mount
    tcp_x_arm_b=.0740,       # URDF/STL v2.1 jaw (tip 74.1 mm from the pivot); a touch gave .0885 but that rests on an unchecked table height (OPEN, 14.5 mm FK offset)
    tcp_x_arm_a=.0740,       # same jaw, not confirmed on arm_a separately
    sim_tcp_x_m=.0740,       # the MuJoCo pads are the repo's v2.1 STL, whose TCP is .0740: the teacher grasps with this one (STL may not match the installed jaws)
    roll_floor_norm=-18.)    # usable wrist roll floor in the norm unit (coordinator): a step whose joint5 goes below it is flagged
# Lane centre (x, y) m and long-axis yaw deg, lanes numbered as printed on the plates. Dark pads in the surveyed top camera, back-projected to the plate top;
# the pads measured 89 x 30 mm against the 90 x 30 container. tmp-a-3 lay under a container: from lanes 1 and 2, its visible end agrees within 0.1 deg.
# The plates are loose: measure again when one moves.
TEMP_LANES_PHOTO = dict(a=[((-.0738, -.2167), 15.7), ((-.0818, -.1672), 2.7), ((-.0776, -.1173), -11.3)],
                        b=[((-.0465, .1439), 4.9), ((-.0466, .1958), -9.7), ((-.0378, .2480), -24.7)])
SCAD = dict(lanes=3, cont_w=.030, cont_l=.090, deck_t=.008, clr=.0004, clr_l=.001, seat_h=.0006, catch=.005, gap_min=.010, rim=.003, yaw_tol_deg=3.)
BELT_STOP_X = .158
ARMS = ("arm_a", "arm_b")  # fixture arm index 0 (y -) and 1 (y +); arm_a does not move in reality (motor 11), it does here
SHIP_ASSETS = ISAAC / "assets/ship_r08_berth"  # made by Rosy/docs/research/ship-modular-2026-11-03/proposals/ship-berth/sim_assets.py (SOURCE.json)
CONTAINER = {"fixture-studs": (.09, .03, .03), "r08-berth": (.09, .02998, .0324)}  # v3 body: 34.4 tall with the top cones, which nest 2 mm: 32.4 per tier
# r08 hold pocket measured on hold-print.stl (top profile): floor z 3, a 0.6 vertical seat at half width 15.7 / half length 45.6 around the
# pocket centre, then a slope rising 4.4 over 2.7 to the deck at 8, ridge 0.5 wide between rows, deck to |y| 63, bulwark to z 11 out to 65 (mm).
HOLD = dict(starts=(50., 148.), length=98., centre=49., rows=(-38., 0., 38.), floor=3., hw=15.7, hl=45.6, seat=.6, catch=2.7, rise=4.4, ridge=.5,
            deck=8., deck_y=63., bulwark=11., half_beam=65.)


# Only hold 1 (next to the stern) is in reach with the stern at the table edge: hold 2 lies behind both arms, where no tool-down pose holds a
# container along x (validator, stern x .155 to .215). So the stack is hold 1, 3 rows x 2 tiers, middle row first, in the stud plan's arm order.
R08_STACK = (("bar-1", "ship-h1r1-l0", "arm_b"), ("bar-2", "ship-h1r0-l0", "arm_a"), ("bar-3", "ship-h1r2-l0", "arm_b"),
             ("bar-4", "ship-h1r1-l1", "arm_b"), ("bar-5", "ship-h1r0-l1", "arm_a"), ("bar-6", "ship-h1r2-l1", "arm_b"))


def ship_cell(layout, x_mm, y_mm, z_mm=0.):
    """r08 ship coordinates (mm: x from the stern end, y to port, z from the table) to the fixture frame: the bow points -x."""
    c = layout.choices
    return c["ship_stern_x_m"] - x_mm / 1000, c["ship_centre_y_m"] - y_mm / 1000, layout.table_z + z_mm / 1000


def r08_sites(layout):
    """1x3 sites of the berthed r08 ship from its slot map: one per hold, row and tier, the mean of the three 1x1 cells.
    Rows are numbered by fixture y (r0 nearest arm_a, as the stud plate's rows); layer 0 and 1 are tiers 82 and 84."""
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
        h, row, layer = holds.index(module) + 1, rows.index(y), tiers.index(tier)
        x, cy, z = ship_cell(layout, sum(g["x_mm"] for g in group) / 3, y, group[0]["z_mm"])
        out[f"ship-h{h}r{row}-l{layer}"] = dict(kind="ship", xy=(x, cy), z=z + layout.box[2] / 2, yaw=0., row=row, layer=layer, stack=f"h{h}r{row}",
                                                slots=[g["id"] for g in group])
    return out


def lane_geometry(radius):
    """SCAD v7 fan: (pocket width, pocket length, flare, fan angle rad, lane angles). Lane i is rotated by -angle about the arm centre."""
    s = SCAD
    width, length = s["cont_w"] + 2 * s["clr"], s["cont_l"] + 2 * s["clr_l"]
    flare = length / 2 * math.tan(math.radians(s["yaw_tol_deg"]))
    fan = 2 * math.asin((width + 2 * flare + s["gap_min"]) / 2 / (radius - length / 2))
    return width, length, flare, fan, [(i - (s["lanes"] - 1) / 2) * fan for i in range(s["lanes"])]



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
                table[name] = kin.Arm(name, (*f["arm_bases_m"][k][:2], z), f["arm_base_yaws_rad"][k], tcp_x=tcp)
        belt_top = self.table_z - .055 if c["belt_height"] == "ruler" else f["pickup_center_m"][2] - .015
        self.belt_top = belt_top
        self.box = CONTAINER[c["ship_source"]]
        self.sites = {"belt": dict(kind="belt", xy=tuple(f["pickup_center_m"][:2]), z=belt_top + self.box[2] / 2 + .0005, yaw=0.)}
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
            else:
                lanes = [(xy, math.radians(yaw)) for xy, yaw in TEMP_LANES_PHOTO[tag]]
                centre = lanes[1][0]
            self.plates[tag] = dict(arm=name, centre=centre, lanes=lanes, outline=plate_outline(lanes, c["temp_radius_m"]))
            for i, (xy, yaw) in enumerate(lanes, 1):
                self.sites[f"tmp-{tag}-{i}"] = dict(kind="temp", xy=xy, z=self.deck_z + self.box[2] / 2, yaw=yaw, plate=tag, lane=i)
        self.ship_xy = {n: s["xy"] for n, s in self.sites.items() if s["kind"] == "ship"}

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
