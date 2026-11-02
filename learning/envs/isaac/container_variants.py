"""Container geometry variants (outer envelope stays N x 30 x 30 mm, grip faces 30 mm); read by Isaac and the MuJoCo release scene.

A variant is a dict: chamfer_mm (equal-leg chamfer on the bottom edges), chamfer_all (also the two short bottom edges),
relief_mm (width of the lowest RELIEF_H_MM, grip faces above stay 30), rail (tongue on top, groove underneath; the tongue
nests, so a layer is NEST_MM lower than 30). Mass follows volume at the effective density of today's 16 g printed 3-cell
container (hollow/infill print: 16 g over 27 cm3 = 593 kg/m3), an assumption, not a measurement.
"""
W, H = .03, .03
RELIEF_H_MM, NEST_MM, TONGUE = 3., 2., ((5., 3.), 2.)  # tongue half-width base/top (mm), height
GROOVE = ((6., 4.), 2.4)  # half-width at the mouth / at the groove roof (mm), depth; 0.4 mm deeper than the tongue is tall
VARIANTS = {'plain': {}}
for _c in (.5, 1., 1.5):
    VARIANTS[f'c{round(_c*10):02d}'] = dict(chamfer_mm=_c)  # long bottom edges
    VARIANTS[f'a{round(_c*10):02d}'] = dict(chamfer_mm=_c, chamfer_all=True)  # all four bottom edges
for _r in (29.4, 29.):
    VARIANTS[f'r{round(_r*10)}'] = dict(relief_mm=_r)
VARIANTS['rail'] = dict(rail=True)
VARIANTS['c10rail'] = dict(chamfer_mm=1., rail=True)


def _hull(pts_mm):
    return [c/1e3 for p in pts_mm for c in p]


def _prism(poly_yz_mm, length_m=.09):
    """Convex prism along the container length from a y-z polygon (mm); returns hull vertices in metres."""
    return _hull([(sx*length_m*500, y, z) for sx in (-1, 1) for y, z in poly_yz_mm])


def pieces(v, length_m=.09):
    """(kind, data) convex pieces about the container centre: ('box', half-size, pos) or ('hull', vertices)."""
    c, relief = v.get('chamfer_mm', 0.), v.get('relief_mm')
    w, h, l = W*500, H*500, length_m*500  # half sizes in mm
    if v.get('rail'):
        (m, g), d = GROOVE
        (tb, tt), th = TONGUE
        out = [('hull', _prism(length_m=length_m, poly_yz_mm=[(-w, -h+d), (w, -h+d), (w, h-th), (-w, h-th)]))]  # roof slab between groove roof and body top
        for s in (-1, 1):  # bottom lips beside the groove: sloped inner wall, optional outer chamfer c
            out.append(('hull', _prism(length_m=length_m, poly_yz_mm=[(s*(w-c), -h), (s*m, -h), (s*g, -h+d), (s*w, -h+d), (s*w, -h+c)])))
        out.append(('hull', _prism(length_m=length_m, poly_yz_mm=[(-tb, h-th), (tb, h-th), (tt, h), (-tt, h)])))
        return out
    if relief:
        r = relief/2
        return [('box', (l, w, (h*2-RELIEF_H_MM)/2), (0, 0, RELIEF_H_MM/2)), ('box', (l, r, RELIEF_H_MM/2), (0, 0, -h+RELIEF_H_MM/2))]
    if c:
        ex = c if v.get('chamfer_all') else 0.
        ring = lambda i, z: [(sx*(l-i*ex), sy*(w-i*c), z) for sx in (-1, 1) for sy in (-1, 1)]  # noqa: E731
        return [('hull', _hull(ring(1, -h)+ring(0, -h+c)+ring(0, h)))]
    return [('box', (l, w, h), (0, 0, 0))]

# Mass over the plain container at equal density, from the MuJoCo hull volumes (3-cell container; test_ship_release_strategies.py
# recomputes it). The 16 g 3-cell container becomes 16 g x ratio; the ratio is the same to 0.1 % for 1 and 2 cells.
MASS_RATIO = {'plain': 1.0, 'c05': .9997, 'a05': .9996, 'c10': .9989, 'a10': .9985, 'c15': .9975, 'a15': .9967,
              'r294': .998, 'r290': .9967, 'rail': .9244, 'c10rail': .9233}


def hull_triangles(points):
    """Outward-facing triangles of the convex hull of a small point set (brute force, n <= 24): for the USD collider mesh."""
    from itertools import combinations
    tris = []
    for i, j, k in combinations(range(len(points)), 3):
        a, b, c = points[i], points[j], points[k]
        u, v = [b[t]-a[t] for t in range(3)], [c[t]-a[t] for t in range(3)]
        n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        length = (n[0]**2+n[1]**2+n[2]**2)**.5
        if length < 1e-12:
            continue
        side = [sum(n[t]*(p[t]-a[t]) for t in range(3))/length for p in points]
        if all(x <= 1e-9 for x in side):
            tris.append((i, j, k))
        elif all(x >= -1e-9 for x in side):
            tris.append((i, k, j))
    return tris
