"""MuJoCo twin of the Isaac ship-plate release (D-947: sweep here first, confirm only near the boundaries in Isaac).

A floating jaw (mocap, placed by TCP) holds one 90x30x30 mm / 16 g container 'height' above the stud plate or a lower
layer and opens; the metrics say whether it seated in the channel, rode up a stud, or pushed the neighbour. No arm,
IK or controller: this answers release-and-settle only. Every number comes from the Isaac-side modules (ship_plate,
palletizing_gripper, mapped_stack_fixture, release_cases); nothing is retyped. MuJoCo contact numbers only pick
candidates for Isaac, they are never reported as results (D-947 section 1).
"""
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'learning/envs/isaac'))
import mapped_stack_fixture as fx  # noqa: E402
import palletizing_gripper as jaw  # noqa: E402
import ship_container_variants as variants  # noqa: E402
import ship_plate as plate  # noqa: E402

if os.name == 'nt':  # the wheel needs msvcp140.dll; a bare Windows laptop has none (pip install msvc-runtime puts it in Scripts)
    import ctypes
    import glob
    for _dll in sorted(glob.glob(str(Path(os.environ.get('APPDATA', '.'))/'Python/Scripts/*140*.dll'))):
        try:
            ctypes.WinDLL(_dll)
        except OSError:
            pass
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

CASE = 'nominal-palletizing-v21-ship'
BOX = (.09, .03, .03)  # container 90 x 30 x 30 mm; 3-cell mass comes from the fixture
BOX_BELOW_TCP_M = .00201  # Isaac hold check (result.md): the held box centre sits 2.01 mm under the TCP along the finger
DT, KP, KV, FINGER_NM = .0005, 40., .3, .2  # Isaac drive: stiffness 40, damping 0.3, finger effort cap 0.2 N m
SOLREF, SOLIMP = [.002, 1], [.95, .99, .001, .5, 2]  # stiff contacts, as omx_mujoco_backend.GRIP_SOLREF/SOLIMP
LIFT_M, SETTLE_S = .025, .5
# Link5 frame, top-down wrist: x points down, y across the box width, z along the box length (world +x).
JAW_ROT = [0, 0, 1, 0, 1, 0, -1, 0, 0]


def fixture():
    return fx.container_fixture(layers=3, case=CASE)


def _quat(yaw):
    return [math.cos(yaw/2), 0, 0, math.sin(yaw/2)]


# Equality data is mjNEQDATA long: 11 in the sim PCs' pinned 3.3.7, 12 in newer MuJoCo; the extra trailing entry is 0 here.
def build(layer, variant='plain', clearance_mm=None, weld=False, cargo=None):
    """Compile the scene. layer 1: boxes rest on the studs; layer 2: three seated boxes below, no studs in play.

    variant: a key of ship_container_variants.VARIANTS; the mass follows its volume at today's 16 g density.
    clearance_mm: side clearance per side around a 30 mm box (CAD 0.4 mm); the dot diameter is changed to match, positions stay.
    weld: the jaw is a free body welded to a mocap target (needed to move a held box: a mocap body has no velocity, so its
    pads would slide over the box without friction). The default keeps the committed Step 3a behaviour."""
    f = fixture()
    if clearance_mm is not None:
        f['ship_plate'] = dict(f['ship_plate'], stud_diameter_m=f['ship_plate']['pitch_m']-BOX[1]-2*clearance_mm/1e3)
    spec = mujoco.MjSpec()
    spec.option.timestep = DT
    spec.compiler.degree = False  # joint ranges in radians
    spec.option.cone, spec.option.impratio = mujoco.mjtCone.mjCONE_ELLIPTIC, 10
    spec.default.geom.solref, spec.default.geom.solimp = SOLREF, SOLIMP
    world, top, p = spec.worldbody, plate.top_z(f), f['ship_plate']['pitch_m']
    thick = f['ship_plate']['thickness_m']
    world.add_geom(name='floor', type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, .1], pos=[0, 0, top-thick])
    outline = plate.outline(f)
    xs, ys = [x for x, _ in outline], [y for _, y in outline]
    world.add_geom(name='plate', type=mujoco.mjtGeom.mjGEOM_BOX, pos=[(min(xs)+max(xs))/2, (min(ys)+max(ys))/2, top-thick/2],
                   size=[(max(xs)-min(xs))/2, (max(ys)-min(ys))/2, thick/2])
    solid, _ = plate.stud_solid(f['ship_plate'])  # the CAD dot: cylinder with a 45 degree chamfer to a flat top (convex hull)
    spec.add_mesh(name='stud', uservert=[c for point in solid for c in point])
    for i, (x, y) in enumerate(plate.stud_positions(f)):
        world.add_geom(name=f'stud{i}', type=mujoco.mjtGeom.mjGEOM_MESH, meshname='stud', pos=[x, y, top])
    mass = f['cargo_mass_kg'][2]
    # cargo: explicit container names (ship_stack_sequence: all nine of a stack); default the one-release scene
    boxes = cargo or ['box', 'neighbour'] + ([f'low{k}' for k in range(3)] if layer == 2 else [])
    for name in boxes:
        body = world.add_body(name=name, pos=[.3+.1*len(world.bodies), 0, .5])
        body.add_freejoint(name=name)
        variants.add_container(spec, body, name, variants.VARIANTS[variant], mass/(BOX[0]*BOX[1]*BOX[2]))
    if weld:
        world.add_body(name='target', mocap=True, pos=[0, 0, 1])
        wrist = world.add_body(name='jaw', pos=[0, 0, 1], gravcomp=1, mass=.05, inertia=[1e-5]*3, explicitinertial=True)
        wrist.add_freejoint(name='jaw')
        spec.add_equality(type=mujoco.mjtEq.mjEQ_WELD, name1='jaw', name2='target', objtype=mujoco.mjtObj.mjOBJ_BODY,
                          data=([0]*6+[1, 0, 0, 0, 1, 0])[:mujoco.mjNEQDATA], solref=[.004, 1])
    else:
        wrist = world.add_body(name='jaw', mocap=True, pos=[0, 0, 1])
    pivots = jaw.description()['pivots']
    for k, side in enumerate((1, -1)):
        finger = wrist.add_body(name=f'finger{k}', pos=pivots[k], gravcomp=1 if weld else 0)
        finger.add_joint(name=f'q{k}', type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 0, 1], range=[-1.2, 1.2], damping=KV, armature=.01)
        centre, size, angle = jaw.pad_box(side)  # the one Isaac pad collider per finger
        finger.add_geom(name=f'pad{k}', type=mujoco.mjtGeom.mjGEOM_BOX, pos=centre, size=[s/2 for s in size], quat=_quat(angle), mass=.004)
    # One lead actuator; the URDF mimic (q1 = -q0) is an equality, so the pads cannot push the box sideways.
    spec.add_actuator(name='a0', target='q0', trntype=mujoco.mjtTrn.mjTRN_JOINT, gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                      gainprm=[KP]+[0]*9, biastype=mujoco.mjtBias.mjBIAS_AFFINE, biasprm=[0, -KP, -KV]+[0]*7,
                      forcelimited=mujoco.mjtLimited.mjLIMITED_TRUE, forcerange=[-FINGER_NM, FINGER_NM])
    spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1='q1', name2='q0', data=([0, -1, 0, 0, 0]+[0]*7)[:mujoco.mjNEQDATA], solref=[.002, 1])
    return spec.compile(), f


def _set_free(model, data, name, pos, yaw=0.):
    a = model.joint(name).qposadr[0]
    data.qpos[a:a+7] = [*pos, *_quat(yaw)]


def _jaw_pose(box_pos, yaw, tcp):
    """Link5 origin and quaternion that hold a box at box_pos/yaw with the Isaac TCP-to-box offset."""
    rot = [[JAW_ROT[3*i+j] for j in range(3)] for i in range(3)]
    local = [sum(rot[i][j]*tcp[j] for j in range(3)) for i in range(3)]  # TCP in the world axes, link5 origin at 0
    origin0 = [-local[0], -local[1], BOX_BELOW_TCP_M-local[2]]  # box centre is at the origin of this frame
    c, s = math.cos(yaw), math.sin(yaw)
    origin = [box_pos[0]+c*origin0[0]-s*origin0[1], box_pos[1]+s*origin0[0]+c*origin0[1], box_pos[2]+origin0[2]]
    q, out = np.zeros(4), np.zeros(4)
    mujoco.mju_mat2Quat(q, np.array(JAW_ROT, float))
    mujoco.mju_mulQuat(out, np.array(_quat(yaw)), q)
    return origin, out


def _pose(data, name):
    b = data.body(name)
    return b.xpos.copy(), math.atan2(2*(b.xquat[0]*b.xquat[3]+b.xquat[1]*b.xquat[2]), 1-2*(b.xquat[2]**2+b.xquat[3]**2))


def run(model, f, *, layer, row=1, dx=0., dy=0., yaw_deg=0., height_m=.005, mu=1., open_gap_m=.033):
    """One release. row +1/-1: outer row beside the centre neighbour; row 2: the free channel (no neighbour).

    dx along the box length, dy across the channel, yaw about z, all of the held box against the channel centre.
    Returns metrics in metres/degrees; displacements are xy norms.
    """
    data = mujoco.MjData(model)
    model.geom_friction[:, 0] = mu
    cx, cy = plate.stack_centre(f)
    p, top, cell = f['ship_plate']['pitch_m'], plate.top_z(f), BOX[2]/2
    surface = top+(cell*2 if layer == 2 else 0.)
    target = [cx, cy+(row if abs(row) == 1 else 2)*p, surface+cell]
    yaw = math.radians(yaw_deg)
    box_pos = [target[0]+dx, target[1]+dy, target[2]+height_m]
    _set_free(model, data, 'box', box_pos, yaw)
    if row == 2:
        _set_free(model, data, 'neighbour', [cx+.3, cy+.3, top+cell])
    else:
        _set_free(model, data, 'neighbour', [cx, cy, surface+cell])
    for k in range(3 if layer == 2 else 0):
        _set_free(model, data, f'low{k}', [cx, cy+(k-1)*p, top+cell])
    contact = jaw.angle_for_gap(jaw.GRASP_WIDTH_M)  # the jaw starts just touching the box, then squeezes
    close, release = jaw.finger_angles(open_gap_m)['close'], jaw.finger_angles(open_gap_m)['release']
    for k, sign in enumerate((1, -1)):
        data.qpos[model.joint(f'q{k}').qposadr[0]] = sign*contact
    origin, quat = _jaw_pose(box_pos, yaw, jaw.description()['tcp'])
    data.mocap_pos[0], data.mocap_quat[0] = origin, quat
    mujoco.mj_forward(model, data)

    def drive(q):
        data.ctrl[0] = q

    def advance(seconds, track=None):
        for _ in range(round(seconds/DT)):
            mujoco.mj_step(model, data)
            if track is not None:
                track.append(math.dist(_pose(data, 'neighbour')[0][:2], rest[:2]))

    for i in range(1, 201):  # 0.1 s squeeze ramp, then 0.25 s hold
        drive(contact+(close-contact)*i/200)
        advance(DT)
    advance(.25)
    held = _pose(data, 'box')[0]
    q_hold = data.qpos[model.joint('q0').qposadr[0]]
    rest = _pose(data, 'neighbour')[0]
    peak = []
    steps = round(fx.grip_duration(q_hold, release, f['release_gripper_acceleration_rad_s2'])/DT)
    for i in range(1, steps+1):  # same open profile length as Isaac, smooth start and stop
        drive(q_hold+(release-q_hold)*(1-math.cos(math.pi*i/steps))/2)
        advance(DT, peak)
    advance(SETTLE_S, peak)
    after_open, after_pos = _pose(data, 'box'), _pose(data, 'neighbour')[0]
    nb_open = math.dist(after_pos[:2], rest[:2])
    lift = round(.5/DT)
    for i in range(1, lift+1):
        data.mocap_pos[0][2] = origin[2]+LIFT_M*i/lift
        advance(DT, peak)
    advance(SETTLE_S, peak)
    end, end_yaw = _pose(data, 'box')
    return dict(z_mm=1e3*(end[2]-target[2]), y_mm=1e3*(end[1]-target[1]), x_mm=1e3*(end[0]-target[0]),
                end_yaw_deg=math.degrees(end_yaw), drop_mm=1e3*(box_pos[2]-held[2]),
                slide_mm=1e3*math.dist(end[:2], held[:2]), settle_mm=1e3*math.dist(after_open[0], end),
                nb_open_mm=1e3*nb_open, nb_peak_mm=1e3*max(peak), nb_end_mm=1e3*math.dist(_pose(data, 'neighbour')[0][:2], rest[:2]),
                speed_mm_s=1e3*float(abs(data.qvel[model.joint('box').dofadr[0]:model.joint('box').dofadr[0]+3]).max()))


def verdict(m, layer, dy_mm=0.):
    """Pass rules from the Isaac runs: z within 0.3 mm of the seat, neighbour moved 0.3 mm or less on opening.

    Layer 1: the studs guide the box, so it must also end within 0.25 mm across the channel (clear width 30.4 mm).
    Layer 2: no guide; the box must stay within 1.5 mm of the target (Isaac xy_tolerance_m)."""
    reasons = []
    if abs(m['z_mm']) > .3:
        reasons.append('rode-up' if layer == 1 and m['z_mm'] > 0 else 'z')
    if layer == 1 and abs(m['y_mm']) > .25:
        reasons.append('not-in-channel')
    if layer == 2 and math.hypot(m['x_mm'], m['y_mm']) > 1.5:
        reasons.append('xy>1.5')
    if m['nb_peak_mm'] > .3:
        reasons.append('neighbour')
    return reasons
