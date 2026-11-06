"""Snap-together container ship v11 hold (3 x 6 rated layout) and team container v2 (1x3), as convex collision pieces.

Source of the numbers: ROSY workspace docs/research/ship-modular-2026-11-03 (ship_modular.scad v11 pocket/pins/rows,
container_v2_bottom.py sockets, layouts.CT stacking height); the container body is the team KAN-109 1x3 measured from STL.
Pure geometry in metres, no simulator import, so MuJoCo (tools/sim/ship_v11_scene.py) and Isaac can share it.
Frames: deck — x along the ship (slot centre 0), y across (rows), z up from the hull bottom; container — origin at the body
centre, bottom face at z = -HEIGHT/2. Each piece is (kind, data, guide): kind 'box' -> data (half sizes, centre), 'mesh' -> vertex
list (convex hull). guide: None for flat pieces, 'cone' for pins and top cones, 'socket' for socket wedges (a wedge only
ever needs to touch a cone).
"""
import math

MM = 1e-3
CELL, GAP, DECK, DEPTH = 30., 8., 8., 5.          # deck height, pocket depth -> pocket floor at z 3
CLR, CLR_X, LEAD, SEAT = .8, .6, 2.7, .6           # side gap across / along, slope lead, vertical wall height
PIN_R, PIN_H, INSET = 2.5, 2., 7.                  # 45 degree truncated cone pins, 7 in from each cell corner
WIDTH, LENGTH, HEIGHT = 29.98, 90., 32.4           # container v2 1x3 body; HEIGHT is the stacking height (CT)
SOCKET_R, SOCKET_D = 2.8, 2.3                      # 45 degree socket: mouth r 2.8 -> r 0.5 at depth 2.3
CONE_R, CONE_H = 2.5, 2.                           # top cones (ends only), 45 degrees
ROWS = (-38., 0., 38.)                             # row centres, pitch cell + gap
FLOOR = DECK-DEPTH
SEGMENTS = 24                                      # facets per round; corners of the socket squares fall on facet edges


def _frustum(x, y, z, r0, r1, h, outer=False):
    """Truncated cone, base r0 at z, top r1 at z + h. outer=False: vertices on the circle (faceted body never larger)."""
    k = 1/math.cos(math.pi/SEGMENTS) if outer else 1.
    pts = []
    for i in range(SEGMENTS):
        a = 2*math.pi*i/SEGMENTS
        for r, zz in ((r0, z), (r1, z+h)):
            pts.append(((x+k*r*math.cos(a))*MM, (y+k*r*math.sin(a))*MM, zz*MM))
    return pts


def pin_centres(y0=0.):
    """Pocket-floor pins of one 1x3 slot (slot centre x 0): x 6 places x y 2 places."""
    xs = [-LENGTH/2+k*CELL+e for k in range(3) for e in (INSET, CELL-INSET)]
    return [(x, y0+s*(WIDTH/2-INSET)) for x in xs for s in (-1, 1)]


def deck_pieces():
    """Pocket floor, pocket walls (0.6 vertical, then the slope) for the three rows, and the 36 pins."""
    out = [('box', (((LENGTH/2+20)*MM, 80*MM, FLOOR/2*MM), (0., 0., FLOOR/2*MM)), None)]
    a, b = LENGTH/2+CLR_X, WIDTH/2+CLR
    half_gap = (ROWS[1]-ROWS[0])/2
    for i, y0 in enumerate(ROWS):
        for s in (-1, 1):  # side walls (across): to the midpoint between rows, wider on the outer sides
            u = half_gap if (s < 0 and i > 0) or (s > 0 and i < 2) else 25.
            prof = [(b, FLOOR), (b, FLOOR+SEAT), (b+LEAD, DECK), (u, DECK), (u, FLOOR)]
            out.append(('mesh', [(x*MM, (y0+s*v)*MM, z*MM) for v, z in prof for x in (-a-LEAD-1, a+LEAD+1)], None))
        for s in (-1, 1):  # end walls (along)
            prof = [(a, FLOOR), (a, FLOOR+SEAT), (a+LEAD, DECK), (a+LEAD+4, DECK), (a+LEAD+4, FLOOR)]
            out.append(('mesh', [(s*v*MM, (y0+w)*MM, z*MM) for v, z in prof for w in (-half_gap, half_gap)], None))
        out += [('mesh', _frustum(x, y, FLOOR, PIN_R, PIN_R-PIN_H, PIN_H), 'cone') for x, y in pin_centres(y0)]
    return out


def socket_centres():
    """Container v2 bottom sockets in the container frame (x 7, 23, 37, 53, 67, 83 and y 7, 23 from the corner)."""
    return pin_centres()  # same pattern: one socket over every pin of the slot


def container_pieces(ends_only=False):
    """Body above the socket layer, the bottom slab around the 12 sockets, 24 wedges per socket, 4 top cones.

    ends_only: only the 4 end sockets, the ones over the top cones of a container below (the middle sockets of an upper
    container face a flat lid, so modelling them solid changes no contact and saves collision work)."""
    z0, z1 = -HEIGHT/2, -HEIGHT/2+SOCKET_D
    out = [('box', ((LENGTH/2*MM, WIDTH/2*MM, (HEIGHT-SOCKET_D)/2*MM), (0., 0., (z1+HEIGHT/2)/2*MM)), None)]
    k = 1/math.cos(math.pi/SEGMENTS)
    sq = SOCKET_R*k  # socket square half side: the faceted hole is never smaller than the CAD cone
    socks = socket_centres()
    ys = sorted({y for _, y in socks})
    xs = sorted({x for x, _ in socks})

    def slab(xa, xb, ya, yb):
        out.append(('box', (((xb-xa)/2*MM, (yb-ya)/2*MM, SOCKET_D/2*MM), ((xa+xb)/2*MM, (ya+yb)/2*MM, (z0+z1)/2*MM)), None))

    edges = [-WIDTH/2]+[v for y in ys for v in (y-sq, y+sq)]+[WIDTH/2]
    for j in range(0, len(edges), 2):  # full-length bands between the socket rows
        slab(-LENGTH/2, LENGTH/2, edges[j], edges[j+1])
    holes = (xs[0], xs[-1]) if ends_only else xs  # ends_only: the middle sockets face a flat lid, solid is the same there
    for y in ys:  # strips through the socket rows, cut around each socket square
        xe = [-LENGTH/2]+[v for x in holes for v in (x-sq, x+sq)]+[LENGTH/2]
        for j in range(0, len(xe), 2):
            slab(xe[j], xe[j+1], y-sq, y+sq)
    r0, r1 = SOCKET_R*k, (SOCKET_R-SOCKET_D)*k
    for x, y in socks:
        if x not in holes:
            continue
        for i in range(SEGMENTS):
            pts = []
            for a in (2*math.pi*i/SEGMENTS, 2*math.pi*(i+1)/SEGMENTS):
                c, s = math.cos(a), math.sin(a)
                edge = sq/max(abs(c), abs(s))
                for r, z in ((r0, z0), (r1, z1)):
                    pts.append(((x+r*c)*MM, (y+r*s)*MM, z*MM))
                for z in (z0, z1):
                    pts.append(((x+edge*c)*MM, (y+edge*s)*MM, z*MM))
            out.append(('mesh', pts, 'socket'))
    for x in (xs[0], xs[-1]):
        for y in ys:
            out.append(('mesh', _frustum(x, y, HEIGHT/2, CONE_R, CONE_R-CONE_H, CONE_H), 'cone'))
    return out


def target(row, layer):
    """Container centre seated in row 0..2 (y -38, 0, +38) at layer 0..2, slot centre x 0, in metres."""
    return (0., ROWS[row]*MM, (FLOOR+HEIGHT/2+layer*HEIGHT)*MM)


def self_check():
    socks, pins = socket_centres(), pin_centres()
    assert len(socks) == 12 and sorted(socks) == sorted(pins), 'every v2 socket sits over a pocket pin'
    assert abs((SOCKET_R-PIN_R)-.3) < 1e-9, 'seated pin to socket radial gap is 0.3 mm (pins locate, walls stay clear)'
    assert math.isclose(CLR+LEAD, 3.5) and math.isclose(CLR_X+LEAD, 3.3),'the pocket mouth catches +-3.5 across and +-3.3 along'
    assert WIDTH/2+CLR+LEAD < (ROWS[1]-ROWS[0])/2, 'neighbouring pocket mouths do not meet'
    return True
