"""Release strategies on the MuJoCo ship-plate scene (candidates only, D-947: MuJoCo picks Isaac cases, never a result).

drop      open where commanded, 5 mm above the seat (the Isaac flow until now).
guarded   lower the held box at DESCENT_M_S until the bottom meets the studs or plate (contact force over CONTACT_N), then open.
search    guarded, and if the contact height says the box sits on a stud (more than SEAT_Z_MM above the seat) lower the grip to
          a light pinch (LIGHT_NM, so the pads slip before the stud is crushed), command the jaw SEARCH_PRELOAD_M below the
          contact height and step it sideways through SEARCH_MM; stop when the box drops back to the seat, then open.
Seated = height within SEAT_Z_MM of the seat and roll/pitch within SEAT_TILT_DEG (layer 2 also xy within 1.5 mm). A failed first
release gets one re-grasp, lift, re-place, with the placement command off by each of RETRY_MM (re-placement noise).
The sensor for 'dropped into the channel' is the box height; on the real arm it is the jaw height or motor load.
"""
import math

import numpy as np

import ship_release_scene as sc
from ship_release_scene import DT, mujoco, plate, jaw, fx, variants

DESCENT_M_S, CONTACT_N, SEAT_Z_MM, SEAT_TILT_DEG = .005, .05, .5, .5
LIGHT_NM, SEARCH_PRELOAD_M = .02, .0006
SEARCH_MM = (.25, -.25, .5, -.5, .75, -.75, 1., -1.)
RETRY_MM = (-.2, .2)
START_ABOVE_M = .006  # guarded start height over the seat; studs top out 3 mm above the plate


class Release:
    def __init__(self, model, f, *, layer, variant, row, dx, dy, yaw_deg, mu, gap, start):
        self.m, self.f, self.d = model, f, mujoco.MjData(model)
        self.layer, self.nest = layer, variants.NEST_MM/1e3 if variants.VARIANTS[variant].get('rail') else 0.
        model.geom_friction[:, 0] = mu
        cx, cy = plate.stack_centre(f)
        top, cell, p = plate.top_z(f), sc.BOX[2]/2, f['ship_plate']['pitch_m']
        surface = top+(cell*2-self.nest if layer == 2 else 0.)
        self.target = np.array([cx, cy+row*p, surface+cell])
        self.yaw = math.radians(yaw_deg)
        pos = self.target+[dx, dy, start]
        sc._set_free(model, self.d, 'box', pos, self.yaw)
        sc._set_free(model, self.d, 'neighbour', [cx, cy, surface+cell])
        for k in range(3 if layer == 2 else 0):
            sc._set_free(model, self.d, f'low{k}', [cx, cy+(k-1)*p, top+cell])
        self.contact_q = jaw.angle_for_gap(jaw.GRASP_WIDTH_M)
        self.q = jaw.finger_angles(gap)
        self.accel = f['release_gripper_acceleration_rad_s2']
        for k, sign in enumerate((1, -1)):
            self.d.qpos[model.joint(f'q{k}').qposadr[0]] = sign*self.contact_q
        origin, quat = sc._jaw_pose(pos, self.yaw, jaw.description()['tcp'])
        self.d.mocap_pos[0], self.d.mocap_quat[0] = origin, quat
        a = model.joint('jaw').qposadr[0]  # the welded jaw starts on its target
        self.d.qpos[a:a+7] = [*origin, *quat]
        mujoco.mj_forward(model, self.d)
        box = model.body('box').id
        self.gids = {g for g in range(model.ngeom) if model.geom_bodyid[g] == box}
        self.floor = {g for g in range(model.ngeom) if model.geom(g).name.startswith(('stud', 'plate', 'low'))}
        self.cap = float(model.actuator_forcerange[0][1])

    def step(self, n=1):
        for _ in range(n):
            mujoco.mj_step(self.m, self.d)

    def time(self, s):
        self.step(round(s/DT))

    def ramp_to(self, q_from, q_to):
        for i in range(1, 201):
            self.d.ctrl[0] = q_from+(q_to-q_from)*i/200
            self.step()
        self.time(.25)

    def squeeze(self):
        self.ramp_to(self.contact_q, self.q['close'])

    def force(self):
        total, f6 = 0., np.zeros(6)
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            if (c.geom1 in self.gids) != (c.geom2 in self.gids) and (c.geom2 if c.geom1 in self.gids else c.geom1) in self.floor:
                mujoco.mj_contactForce(self.m, self.d, i, f6)
                total += abs(f6[0])
        return total

    def pose(self):
        """Box centre, roll about the long axis, pitch, yaw (degrees)."""
        b = self.d.body('box')
        r = b.xmat.reshape(3, 3)
        yaw = math.atan2(2*(b.xquat[0]*b.xquat[3]+b.xquat[1]*b.xquat[2]), 1-2*(b.xquat[2]**2+b.xquat[3]**2))
        return b.xpos.copy(), math.degrees(math.asin(r[2, 1])), math.degrees(math.asin(-r[2, 0])), math.degrees(yaw)

    def z_err_mm(self):
        return 1e3*(self.pose()[0][2]-self.target[2])

    def move(self, delta, seconds):
        start, n = self.d.mocap_pos[0].copy(), max(1, round(seconds/DT))
        for i in range(1, n+1):
            self.d.mocap_pos[0] = start+np.array(delta)*i/n
            self.step()

    def descend(self, limit_m):
        """Lower until the box touches studs/plate; returns the height error at contact (mm) or None."""
        for _ in range(round(limit_m/DESCENT_M_S/DT)):
            self.d.mocap_pos[0][2] -= DESCENT_M_S*DT
            self.step()
            if self.force() > CONTACT_N:
                self.time(.05)
                return self.z_err_mm()
        return None

    def search(self):
        """Light pinch, preload down, sideways steps until the box height returns to the seat. Returns steps used."""
        self.m.actuator_forcerange[0] = [-LIGHT_NM, LIGHT_NM]
        self.d.mocap_pos[0][2] -= SEARCH_PRELOAD_M
        y0, used = self.d.mocap_pos[0][1], 0
        self.time(.15)
        for used, s in enumerate(SEARCH_MM, 1):
            if self.z_err_mm() <= SEAT_Z_MM:
                used -= 1
                break
            self.move([0, y0+s*1e-3-self.d.mocap_pos[0][1], 0], .25)
            self.time(.1)
        self.m.actuator_forcerange[0] = [-self.cap, self.cap]
        return used

    def open_lift(self):
        q0 = self.d.qpos[self.m.joint('q0').qposadr[0]]
        steps = round(fx.grip_duration(q0, self.q['release'], self.accel)/DT)
        for i in range(1, steps+1):
            self.d.ctrl[0] = q0+(self.q['release']-q0)*(1-math.cos(math.pi*i/steps))/2
            self.step()
        self.time(.5)
        self.move([0, 0, sc.LIFT_M], .5)
        self.time(.5)

    def regrasp(self, to_y):
        """Jaw (pre-opened wide) over the box, down, squeeze, lift 6 mm, then sideways so the box centre is at to_y."""
        pos, _, _, yaw = self.pose()
        wide = jaw.finger_angles(jaw.PREOPEN_GAP_M)['release']
        self.d.ctrl[0] = wide
        self.time(.3)
        origin, quat = sc._jaw_pose(pos, math.radians(yaw), jaw.description()['tcp'])
        self.d.mocap_quat[0] = quat
        self.move([origin[0]-self.d.mocap_pos[0][0], origin[1]-self.d.mocap_pos[0][1], 0], .3)
        self.move([0, 0, origin[2]-self.d.mocap_pos[0][2]], .5)
        self.ramp_to(wide, self.q['close'])
        self.move([0, 0, .006], .3)
        self.move([0, to_y-self.pose()[0][1], 0], .3)
        self.time(.1)


def seated(r):
    p, roll, pitch, _ = r.pose()
    ok = abs(r.z_err_mm()) <= SEAT_Z_MM and abs(roll) <= SEAT_TILT_DEG and abs(pitch) <= SEAT_TILT_DEG
    if r.layer == 2:
        ok = ok and math.hypot(*(1e3*(p[:2]-r.target[:2]))) <= 1.5
    return ok


def place(r, strategy):
    """One release from the squeezed state; returns (contact error mm or None, search steps)."""
    err, used = None, 0
    if strategy != 'drop':
        err = r.descend(START_ABOVE_M+.006)
        if strategy == 'search' and err is not None and err > SEAT_Z_MM:
            used = r.search()
    r.open_lift()
    return err, used


def attempt(model, f, *, layer, variant='plain', strategy='drop', gap=.0315, dy=0., dx=0., yaw_deg=0., mu=1., row=1, retry=True):
    """One placement with a seat check and, on failure, one re-grasp and re-place for each RETRY_MM command error."""
    start = .005 if strategy == 'drop' else START_ABOVE_M
    kw = dict(layer=layer, variant=variant, row=row, dx=dx, dy=dy, yaw_deg=yaw_deg, mu=mu, gap=gap, start=start)
    r = Release(model, f, **kw)
    r.squeeze()
    err, used = place(r, strategy)
    p, roll, pitch, yaw = r.pose()
    out = dict(seated=bool(seated(r)), z_mm=r.z_err_mm(), y_mm=1e3*(p[1]-r.target[1]), roll=roll, pitch=pitch,
               contact_mm=err, search_steps=used, recovered=None)
    if out['seated'] or not retry:
        return out
    ok = 0
    for delta in RETRY_MM:
        r = Release(model, f, **kw)
        r.squeeze()
        place(r, strategy)  # the sim is deterministic: this reproduces the failed first release
        r.regrasp(r.target[1]+delta*1e-3)
        place(r, strategy)
        ok += seated(r)
    out['recovered'] = ok/len(RETRY_MM)
    return out
