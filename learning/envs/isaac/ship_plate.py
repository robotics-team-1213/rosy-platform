"""The navy stud plate ("배 모양 판", Harbor main ship) under the container stack: geometry, mesh and the release floor.

Source: the team CAD in Jira KAN-108 (2026-11-01; container_ship_hull_deck.stl, container_ship_dimensions.png). The earlier photo
estimates (pitch 35.1, dot 4.7 mm hemispherical, plate 3 mm) are history: result.md steps 2 and 3. Stdlib only: the Isaac adapter
and the host tests both import it.
"""
import math

SHIP_PLATE = dict(
    pitch_m=.036,            # CAD: cell 30 + 6.02 gap = pitch 36 (drawing); dots at the 36 cell-corner intersections
    stud_diameter_m=.0052,   # CAD dot diameter 5.2: leaves 30.8 mm between dots, 0.41 mm per side around a 30 mm box
    stud_height_m=.003,
    stud_chamfer_m=.0008,    # hull STL: cylinder radius 2.6 to 2.2 mm over the deck, then a 45 deg chamfer to radius 1.8 at 3 mm
    thickness_m=.008,        # CAD plate thickness 8 mm (hull STL deck at z 8)
    columns=6, rows=6,       # dots across (y) and along (x): 5 x 5 cells, cargo area 180 x 180 mm
    margin_m=.001,           # ASSUMED: finger and box bottoms stay this far above a dot top
    # The container cells are the three stern-side cells (coordinator, 2026-11-01: stern faces the belt, bow points away).
    containers_at='stern',
    source=dict(issue='KAN-108', hull_deck_stl_sha256='d545ae5109608774e56430248edfc456d8ba189ae9d3f5047d95417290f88ad5',
                bridge_stl_sha256='07c4f35cc5a3d8ab555e71bf55783bcf7fe5643da89c6095a016b7ebc87931c0'))
# Hull outline in the CAD frame (mm; x from the first dot row toward the bow, y across), counter-clockwise. Cropped, not the CAD
# outline: the real stern lies 50.6 mm behind the first dot row (bridge x -42.6..-18.6, 58 mm tall) but here it stops 16 mm behind,
# where the belt end sits (a longer stern collided with the belt feed spot, run 7913), and the bow stops at x 198 where the bulwark
# starts (the tip to 244.6 would cover the leveling spot at x -0.12, which is unreachable further out). Neither crop touches the
# dots. A layout decision is open: where the real stern, bridge and belt end meet.
OUTLINE_CAD_MM = [(-16., -96.1), (190., -96.1), (198., -92.5), (198., 92.5), (190., 96.1), (-16., 96.1)]
STUD_SIDES = 16


def stack_centre(fixture):
    """x, y of the middle of the three container cells, from the fixture's stack envelope."""
    origin, size = fixture['bin_origin_m'], fixture['bin_size_m']
    return origin[0]+size[0]/2, origin[1]+size[1]/2


def stud_positions(fixture):
    """(x, y) of every stud: lane intersections; the first row is the container end lane on the belt side, then toward -x."""
    spec = fixture['ship_plate']
    cx, cy = stack_centre(fixture)
    p = spec['pitch_m']
    first = cx+1.5*p  # the container's end lane on the belt side: 3 cells of pitch p, centred on the stack
    return [(first-j*p, cy+(k-(spec['columns']-1)/2)*p) for j in range(spec['rows']) for k in range(spec['columns'])]


def outline(fixture):
    """Plate outline, counter-clockwise: flat stern on the belt side (+x), bow away from the belt (-x), from OUTLINE_CAD_MM."""
    first = max(x for x, _ in stud_positions(fixture))
    cy = stack_centre(fixture)[1]
    return [(first-x/1000, cy+y/1000) for x, y in reversed(OUTLINE_CAD_MM)]


def top_z(fixture):
    return fixture['bin_origin_m'][2]  # the plate top is where the containers rest


def stud_solid(spec):
    """One dot as points about its base centre (deck top at z 0) and triangles: a cylinder, then the CAD 45 degree chamfer to a flat top.

    Convex, so it doubles as the PhysX collider (convex hull) and the visual."""
    radius, height, chamfer = spec['stud_diameter_m']/2, spec['stud_height_m'], spec['stud_chamfer_m']
    rings = [(radius, 0.), (radius, height-chamfer), (radius-chamfer, height)]
    points = [(r*math.cos(2*math.pi*k/STUD_SIDES), r*math.sin(2*math.pi*k/STUD_SIDES), z) for r, z in rings for k in range(STUD_SIDES)]
    points += [(0., 0., 0.), (0., 0., height)]
    tris = []
    for low in (0, STUD_SIDES):
        for k in range(STUD_SIDES):
            t = (k+1) % STUD_SIDES
            tris += [(low+k, low+t, low+STUD_SIDES+t), (low+k, low+STUD_SIDES+t, low+STUD_SIDES+k)]
    for k in range(STUD_SIDES):
        t = (k+1) % STUD_SIDES
        tris += [(3*STUD_SIDES+1, 2*STUD_SIDES+k, 2*STUD_SIDES+t), (3*STUD_SIDES, t, k)]
    return points, tris


def mesh(fixture):
    """(points, triangle indices, number of plate triangles before the stud triangles) of one static triangle mesh."""
    spec = fixture['ship_plate']
    base, top = top_z(fixture)-spec['thickness_m'], top_z(fixture)
    points, tris = [], []
    polygon = outline(fixture)
    low = len(points)
    points += [(x, y, base) for x, y in polygon]
    high = len(points)
    points += [(x, y, top) for x, y in polygon]
    n = len(polygon)
    for i in range(1, n-1):  # convex polygon: fan from vertex 0
        tris += [(high, high+i, high+i+1), (low, low+i+1, low+i)]
    for i in range(n):
        j = (i+1) % n
        tris += [(low+i, low+j, high+j), (low+i, high+j, high+i)]
    plate_faces = len(tris)
    solid, solid_tris = stud_solid(spec)
    for x, y in stud_positions(fixture):
        base = len(points)
        points += [(x+px, y+py, top+pz) for px, py, pz in solid]
        tris += [tuple(base+i for i in t) for t in solid_tris]
    return points, tris, plate_faces


def release_floor_z(fixture, finger_bottom_below_box_center_m):
    """Lowest box-centre z at release: the box bottom and the finger bottom both stay above the stud tops plus a margin.

    finger_bottom_below_box_center_m is the lowest finger point minus the box centre z (negative: the finger reaches
    below the box centre); the finger plate is wider than a stud pitch, so it always overlaps a stud in the lane.
    """
    spec = fixture['ship_plate']
    stud_top = top_z(fixture)+spec['stud_height_m']+spec['margin_m']
    return max(stud_top+.015, stud_top-finger_bottom_below_box_center_m)


def finger_clearance_m(fixture, finger_bottom_z):
    """Finger bottom height above the stud tops (negative: it would hit a stud)."""
    return finger_bottom_z-(top_z(fixture)+fixture['ship_plate']['stud_height_m'])


def place(value):
    """Put the stack on the plate: the container floor is the plate top, on the work table, and the lane is the stud lane."""
    spec = value['ship_plate']
    table_top = value['workplate_center_m'][2]+value['workplate_size_m'][2]/2
    value['bin_origin_m'][2] = table_top+spec['thickness_m']
    spec['x_limit_m'] = round(value['workplate_center_m'][0]+value['workplate_size_m'][0]/2, 6)  # the stern stays on the table
    return value


def free_channels(fixture):
    """Stud channels beside the stack (user decision 2026-11-01: the stack fills the centre three of the five cells across).

    One per arm: the side cell on that arm's side, running along x. Returns arm -> dict(y_m, x_cells_m, clear_width_m);
    x_cells_m are the cell centres along the plate, clear_width_m the gap between stud surfaces (pitch minus stud diameter).
    """
    spec = fixture['ship_plate']
    p, cy = spec['pitch_m'], stack_centre(fixture)[1]
    rows = sorted({round(x, 6) for x, _ in stud_positions(fixture)})
    cells = [round((a+b)/2, 6) for a, b in zip(rows, rows[1:])]
    side = (spec['columns']-2)/2*p  # centre of the outer cell: two pitches from the middle one
    return {arm: dict(y_m=round(cy+sign*side, 6), x_cells_m=cells, clear_width_m=round(p-spec['stud_diameter_m'], 6))
            for arm, sign in enumerate((-1, 1))}  # arm 0 stands at -y, arm 1 at +y
