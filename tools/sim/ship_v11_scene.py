"""MuJoCo scene of the v11 snap-together ship hold with team container v2, the v2.1 jaw and the wrist camera B holder.

Geometry: learning/envs/isaac/ship_v11.py (pocket walls, 45 degree pins, container sockets and top cones as convex pieces).
Jaw, contacts and release drive: ship_release_scene (same as the stud-plate twin). The camera holder is
b12-u18-span-B (rosy-docs hardware/omx-wrist-camera-mount): a box proxy whose lowest point sits 32.3 mm above the TCP
in the top-down pose, plus a camera at the measured lens pose. Candidates for Isaac only (D-947 section 1).
"""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ship_release_scene as base  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'learning/envs/isaac'))
import ship_v11 as v11  # noqa: E402

mujoco = base.mujoco
GUIDE = 2  # contype bit shared by pins, top cones and socket wedges; flat faces stay on bit 1
# Wrist camera B (results.json b12-u18-span-B), link5 mm: lens, optical axis to the jaw axis at x 119.1, vertical FOV 69.6
LENS_MM, AXIS_HIT_X_MM, VFOV_DEG, LOWEST_ABOVE_TCP_MM = (37.8, 0., 53.1), 119.1, 69.6, 32.3
HOLDER_HALF_MM = (4., 16., 16.)  # along the axis, across (y), along the board (proxy for board + plate)


def camera_frame():
    """Optical axis d, board axis e (both in the link5 x-z plane) and the holder proxy centre in metres."""
    d = (AXIS_HIT_X_MM-LENS_MM[0], 0., -LENS_MM[2])
    n = math.hypot(d[0], d[2])
    d = (d[0]/n, 0., d[2]/n)
    e = (-d[2], 0., d[0])  # the board direction away from the jaw tip has e_x > 0 here
    hd, _, he = HOLDER_HALF_MM
    tcp_x = base.jaw.description()['tcp'][0]*1e3
    reach = hd*abs(d[0])+he*abs(e[0])  # lowest corner along x (down in the top-down pose)
    centre = (tcp_x-LOWEST_ABOVE_TCP_MM-reach, 0., LENS_MM[2]-hd*d[2])
    return d, e, [c/1e3 for c in centre]


def _add_pieces(spec, body, prefix, pieces, meshes):
    for k, (kind, data, guide) in enumerate(pieces):
        bits = {'cone': dict(contype=GUIDE | 1, conaffinity=GUIDE | 1), 'socket': dict(contype=GUIDE, conaffinity=GUIDE)}.get(guide, {})
        if kind == 'box':
            body.add_geom(name=f'{prefix}{k}', type=mujoco.mjtGeom.mjGEOM_BOX, size=list(data[0]), pos=list(data[1]), **bits)
            continue
        if spec.mesh(f'{meshes}{k}') is None:  # the nine containers share one set of mesh assets
            spec.add_mesh(name=f'{meshes}{k}', uservert=[c for p in data for c in p])
        body.add_geom(name=f'{prefix}{k}', type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f'{meshes}{k}', **bits)


def build(cargo, camera=True, upper=()):
    """Compile the hold (three rows, pocket floor at z 3 mm) with the named containers parked off the deck.

    upper: names that only ever sit on another container (wedges in the end sockets only).
    Containers start weightless (gravcomp 1; MuJoCo only applies gravcomp to bodies that had it when compiled): the caller
    sets body_gravcomp to 0 when it releases one."""
    f = base.fixture()
    spec = base.new_spec()
    world = spec.worldbody
    world.add_geom(name='floor', type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, .1])  # parked containers wait here
    _add_pieces(spec, world, 'deck', v11.deck_pieces(), 'deck_m')
    mass = f['cargo_mass_kg'][2]
    lx, ly, lz = v11.LENGTH*1e-3, v11.WIDTH*1e-3, v11.HEIGHT*1e-3
    inertia = [mass*(ly**2+lz**2)/12, mass*(lx**2+lz**2)/12, mass*(lx**2+ly**2)/12]
    pieces = {False: v11.container_pieces(), True: v11.container_pieces(ends_only=True)}
    for name in cargo:
        body = world.add_body(name=name, pos=[.3+.1*len(world.bodies), 0, .5], mass=mass, inertia=inertia, ipos=[0, 0, 0],
                              explicitinertial=True, gravcomp=1)
        body.add_freejoint(name=name)
        _add_pieces(spec, body, name+'_', pieces[name in upper], 'v2e_m' if name in upper else 'v2_m')
    wrist = base.add_jaw(spec)
    if camera:
        d, e, centre = camera_frame()
        quat = base.np.zeros(4)
        mujoco.mju_mat2Quat(quat, base.np.array([d[0], 0., e[0], 0., 1., 0., d[2], 0., e[2]], float))  # columns d, y, e
        wrist.add_geom(name='camera_holder', type=mujoco.mjtGeom.mjGEOM_BOX, size=[h/1e3 for h in HOLDER_HALF_MM],
                       pos=centre, quat=list(quat))
        cam = wrist.add_camera(name='wrist_b', pos=[c/1e3 for c in LENS_MM], fovy=VFOV_DEG)
        cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
        cam.alt.xyaxes = [0., 1., 0., -e[0], 0., -e[2]]  # looks along -z = d; image up points back to the wrist
    return spec.compile(), f


def holder_contacts(model, data):
    """Contacts of the camera holder proxy right now (it should never touch a container or the deck)."""
    g = model.geom('camera_holder').id
    return sum(1 for c in data.contact[:data.ncon] if g in (c.geom1, c.geom2))
