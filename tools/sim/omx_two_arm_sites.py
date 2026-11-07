"""Two-arm OMX cell layout without MuJoCo: arm bases, belt end, ship cells and the two temporary slot plates, in the fixture frame.

Every number comes from an existing module (mapped_stack_fixture, ship_plate, palletizing_gripper, cell_model_inventory.yaml) or from the
temp_slot_plate v7 SCAD parameters (Confluence 15368863; arm-to-plate 214 mm is a photo estimate, candidates 155 to 273 mm). Where CAD and
a measurement both exist the choice is a named entry of CHOICES (D-947 2: candidates compared by results, nothing silently overwritten).
"""
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
    temp_radius_m=.214,      # arm centre to temp plate centre; SCAD arm_r, a photo estimate (candidates .155 to .273)
    temp_direction_deg=180., # from each arm toward -x, away from the belt (the user's slot plan 2026-10-31)
    temp_source="scad-v7",   # the plate source; "stl" keeps the same collision shape and shows the downloaded STL as the visual
    ship_source="fixture-studs",  # the plate the stack sits on: the fixture's stud plate (the physical ship is only partly built)
    wrist_camera="none",     # "none", "v21-b" (palletizing_gripper.WRIST_CAMERA_B) or "stock" (the cell example's omx-ai-stock)
    tcp_x_arm_b=.0740,       # URDF/STL v2.1 jaw (tip 74.1 mm from the pivot); a touch gave .0885 but that rests on an unchecked table height (OPEN, 14.5 mm FK offset)
    tcp_x_arm_a=.0740,       # same jaw, not confirmed on arm_a separately
    sim_tcp_x_m=.0740,       # the MuJoCo pads are the repo's v2.1 STL, whose TCP is .0740: the teacher grasps with this one (STL may not match the installed jaws)
    roll_floor_norm=-18.)    # usable wrist roll floor in the norm unit (coordinator): a step whose joint5 goes below it is flagged
SCAD = dict(lanes=3, cont_w=.030, cont_l=.090, deck_t=.008, clr=.0004, clr_l=.001, seat_h=.0006, catch=.005, gap_min=.010, rim=.003, yaw_tol_deg=3.)
BOX_H, BELT_STOP_X = .03, .158
ARMS = ("arm_a", "arm_b")  # fixture arm index 0 (y -) and 1 (y +); arm_a does not move in reality (motor 11), it does here


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
        self.sites = {"belt": dict(kind="belt", xy=tuple(f["pickup_center_m"][:2]), z=belt_top + BOX_H / 2 + .0005, yaw=0.)}
        for item in fx.plan(True, fixture=f):
            row, layer = item["cell"][1], item["cell"][2]
            self.sites[f"ship-r{row}-l{layer}"] = dict(kind="ship", xy=tuple(item["target"][:2]), z=item["target"][2], yaw=0.,
                                                       arm=ARMS[item["arm"]], item=item["id"], row=row, layer=layer)
        for tag, name in (("a", "arm_a"), ("b", "arm_b")):
            lanes, centre = temp_lanes(self.arms[name].base[:2], c["temp_radius_m"], c["temp_direction_deg"])
            self.plates[tag] = dict(arm=name, centre=centre, lanes=lanes, outline=plate_outline(lanes, c["temp_radius_m"]))
            for i, (xy, yaw) in enumerate(lanes, 1):
                self.sites[f"tmp-{tag}-{i}"] = dict(kind="temp", xy=xy, z=self.deck_z + BOX_H / 2, yaw=yaw, plate=tag, lane=i)
        self.ship_xy = {n: s["xy"] for n, s in self.sites.items() if s["kind"] == "ship"}

    def containers(self):
        """The nine container ids of the fixture plan, in plan order, with the arm the plan gave each."""
        return [(i["id"], ARMS[i["arm"]]) for i in fx.plan(True, fixture=self.fixture)]

    def plan_order(self):
        """Fixture plan order as (container, ship site, arm)."""
        return [(i["id"], f"ship-r{i['cell'][1]}-l{i['cell'][2]}", ARMS[i["arm"]]) for i in fx.plan(True, fixture=self.fixture)]

    def hold_z(self, site):
        """TCP height that centres a held container on the site: the held centre sits 2.01 mm under the TCP (Isaac hold check)."""
        return self.sites[site]["z"] + .00201
