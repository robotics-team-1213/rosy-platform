"""Wrist-camera closed loop for the two-arm sim grasp: where the container's top face is, from the wrist camera alone.

The grasp half of a step is commanded in reported angles, so a joint-zero error shows as a TCP that is a few mm off the planned place (1 deg: the
jaw closes 11-16 mm above the container). The wrist camera sits rigidly on link5, so the container's top face seen in its image does not depend on
that error: this module segments the face by colour, fits the face's rectangle (known catalogue size, horizontal) to the mask with the camera's own
CAD geometry, and returns the face centre in the TCP frame. No ground truth is read: only the rendered image, the reported-angle rotation, the camera
parameters of the model (CAD mount) and the container's catalogue size. MuJoCo answers geometry only (D-947); no real arm is involved.
Both parts are off unless `--closed-loop` asks. Ported to main from the plateau-1118 experiments, which measured them with --pose-random (not on main): main carries the code and
a smoke test, not those success rates.
"""
import math

import numpy as np

HSV_LO, HSV_HI = (3, 70, 45), (17, 255, 255)  # orange-brown container PLA, lit or shadowed; the yellow table (H ~ 20) and the grey/blue/green surroundings stay out
IMG = (240, 320)
L_OUT = .3  # weight of mask pixels outside the fitted silhouette (a neighbour box in the same colour sits there) against silhouette pixels with no mask


class WristRig:
    """One wrist camera's pinhole model and its pose in the link5 frame (= the TCP frame's axes): R, pos from the model's CAD mount, tcp the TCP in link5, fovy in degrees."""

    def __init__(self, R, pos, tcp, fovy_deg, size=IMG, name=""):
        self.R, self.pos, self.tcp, self.size, self.name = np.asarray(R, float), np.asarray(pos, float), np.asarray(tcp, float), size, name
        self.f = size[0] / 2 / math.tan(math.radians(float(fovy_deg)) / 2)

    @classmethod
    def of_world(cls, world, arm, size=IMG):
        import mujoco
        name = {"arm_a": "a_wrist", "arm_b": "b_wrist"}[arm]
        m = world.model
        cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, name)
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, m.cam_quat[cid].astype(float))
        return cls(R.reshape(3, 3), m.cam_pos[cid], world.layout.sim_arms[arm].tcp, m.cam_fovy[cid], size, name)

    def project(self, pts_tcp):
        """Pixels (u, v) of points in the TCP frame; None when one is behind the camera."""
        c = (np.asarray(pts_tcp, float) + self.tcp - self.pos) @ self.R  # camera frame: x right, y up, looks along -z
        if np.any(c[:, 2] > -.005):
            return None
        return np.stack([self.size[1] / 2 + self.f * c[:, 0] / -c[:, 2], self.size[0] / 2 - self.f * c[:, 1] / -c[:, 2]], 1)


def segment(rgb):
    """Container colour mask of an RGB frame (uint8 0/1), small specks removed."""
    import cv2
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    m = cv2.inRange(hsv, np.array(HSV_LO, np.uint8), np.array(HSV_HI, np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) // 255


def _soft(mask):
    import cv2
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.5)


def _corners(box):
    """The container's 8 corners relative to the centre of its top face (z up): the camera sees the whole box's silhouette, not only the top rectangle."""
    L, W, Hh = box[0], box[1], box[2]
    return np.array([[sx * L / 2, sy * W / 2, -dz] for dz in (0, Hh) for sx in (1, -1) for sy in (1, -1)])


def fit_top_face(rgb, rig, R_tcp, box, seed_top, yaw0, mask=None):
    """Fit the container (box L x W x H, upright, its top face centre at world offset e from the TCP) by its silhouette to the colour mask.

    R_tcp: the TCP frame's rotation in the world as the reported angles give it. seed_top: expected face centre relative to the TCP, world axes (m).
    Returns dict(e=face centre relative to the TCP in world axes (m), yaw (rad), score = matched fraction, area_px) or None."""
    import cv2
    mask = segment(rgb) if mask is None else mask
    area = int(mask.sum())
    if area < 400:
        return None
    soft = _soft(mask)
    c0, H, W = _corners(box), *rig.size
    R_tcp = np.asarray(R_tcp, float)

    def render(p):
        cy, sy = math.cos(p[3]), math.sin(p[3])
        pts_w = c0 @ np.array([[cy, sy, 0], [-sy, cy, 0], [0, 0, 1]]) + p[:3]  # row vectors: Rz(yaw) c, then the offset, in world axes
        uv = rig.project(pts_w @ R_tcp)  # world offset -> TCP frame (R^T v as a row vector is v @ R)
        if uv is None:
            return None
        img = np.zeros((H, W), np.uint8)
        hull = cv2.convexHull(np.round(uv * 16).astype(np.int32))
        cv2.fillPoly(img, [hull], 255, lineType=cv2.LINE_AA, shift=4)
        return img.astype(np.float32) / 255

    def cost(p):
        img = render(p)
        return 1e9 if img is None else float(np.maximum(img - soft, 0).sum() + L_OUT * np.maximum(soft - img, 0).sum())

    p = np.array([*seed_top, yaw0], float)
    best = cost(p)
    for step_mm, step_deg in ((8, 4), (4, 2), (2, 1), (1, .5), (.5, .25), (.25, .12)):
        improved = True
        while improved:
            improved = False
            for k in range(4):
                for sgn in (1, -1):
                    q = p.copy()
                    q[k] += sgn * (step_mm / 1000 if k < 3 else math.radians(step_deg))
                    c = cost(q)
                    if c < best - 1e-3:
                        p, best, improved = q, c, True
    img = render(p)
    inter = float((np.minimum(img, soft)).sum())
    return dict(e=p[:3].copy(), yaw=float(p[3]), score=inter / max(1., float(img.sum())), area_px=area, cost=best, _cost=cost)


# ---- the closed loop itself: generators the Teacher's step_gen drives when teacher.closed_loop names a part (off by default) ----
PARTS = ("wrist", "contact")  # teacher.closed_loop: "wrist" re-aims the close pose from the face the wrist camera sees (at most MAX_ITER times); "contact" lowers slowly, stops on a pad that stands on the deck or the target's top, feels sideways, and retries an empty jaw once
E_REF = {"arm_a": (-.0025, 0., .0126), "arm_b": (-.0025, 0., .0126)}  # face centre relative to the TCP (world axes, m) of a grasp that closes well: the reference image the loop steers to
MAX_ITER, CLIP_M, SCORE_MIN, UP_M, LIFT_MARGIN_M = 2, .015, .90, .004, .003  # at most 2 corrections of at most 15 mm (per axis)
DEAD_M = np.array([.003, .0012, .0015])  # world x, y, z: nothing moves inside this (x runs along the container, where the jaw does not care)
PLAUSIBLE_M = np.array([.025, .015, .030])  # an estimate further than this from the reference is not believed
SLOW_STEP_M, HOVER_M, FLOOR_M = .001, .010, .005  # slow descent: 1 mm a frame from HOVER_M above the target, alone down to FLOOR_M below it
FEEL_OFFS_M, FEEL_LIFT_M, ARRIVED_M = (.0015, -.0015, .003, -.003), .003, .0025  # cell_feel: shifts along the closing axis after a pad lands on something; a stop within ARRIVED_M of the target is an arrival
EMPTY_FRAC, WATCH = .95, 18  # a jaw this far along its close (0 open, 1 the held-box gap) holds nothing; a box in the jaw stopped it at 0.89 at most (11-18 runs)
_RIGS = {}


def rig_for(T, arm):
    if (id(T.world), arm) not in _RIGS:
        _RIGS[id(T.world), arm] = WristRig.of_world(T.world, arm)
    return _RIGS[id(T.world), arm]


def pad_contact(T, data, arm, c):
    """What a pad of this arm stands on (the deck, a neighbour's or the target's top face: contact normal up), or None: the sim's stand-in for cell_feel's contact current."""
    w, p = T.world, {"arm_a": "a_", "arm_b": "b_"}[arm]
    for ct in data.contact[:data.ncon]:
        names = [w.geom_name[g] for g in (ct.geom1, ct.geom2)]
        for k in (0, 1):
            if names[k].startswith(p + "pad"):
                other = names[1 - k] or w.body_name[w.model.geom_bodyid[(ct.geom1, ct.geom2)[1 - k]]]
                if abs(float(ct.frame[2])) > .7 and not other.startswith("bar-") or other == c and abs(float(ct.frame[2])) > .7:  # the deck or the target's top face under the pad; a neighbour (grazed in a cramped lane) or a side touch does not stop the descent
                    return other
    return None


def slow_down(T, data, step, ik_arm, q, p, yaw, g, z_stop, pos0, log, stop=True):
    """Lower the TCP (reported angles) from p, 1 mm a frame, until z_stop or a pad stands on something."""
    arm, c, w, why, p = step["arm"], step["container"], T.world, "floor", np.array(p, float)
    while p[2] > z_stop + 1e-9:
        what = pad_contact(T, data, arm, c) if stop else None
        if what:
            why, log["touched"] = "contact", what
            break
        p = p - np.array([0., 0., min(SLOW_STEP_M, p[2] - z_stop)])
        q = ik_arm.ik(q, p, yaw, 30)[0]
        yield np.append(q[:5], g)
    return q, p, why


def descend(T, data, ctx, step, ik_arm, q, p, yaw, g, z_stop, pos0, log, feel=True):
    """Slow descent to z_stop that feels its way: a pad that lands more than ARRIVED_M above z_stop lifts FEEL_LIFT_M, slides along the closing axis (FEEL_OFFS_M in turn, the side
    away from the nearest neighbour first) and goes down again; when no shift finds the way the jaw presses on to z_stop as the plain descent does. Returns q, p, why."""
    axis, cur = np.array([-math.sin(yaw), math.cos(yaw), 0.]), 0.
    width, free = float(T.layout.box[1]), {1: 1., -1: 1.}  # room (m) to a neighbour on each side along the closing axis: the jaw feels only into free space
    for v in pos0.values():
        d = v - p
        if abs(float(d[:2] @ np.array([math.cos(yaw), math.sin(yaw)]))) < float(T.layout.box[0]):  # same stretch of the lane
            s = float(axis @ d)
            free[1 if s > 0 else -1] = min(free[1 if s > 0 else -1], abs(s) - width)
    for k, off in enumerate((0., *FEEL_OFFS_M)):
        if off and abs(off) > free[1 if off > 0 else -1] - .001:
            continue
        if off != cur:
            up = p + np.array([0., 0., FEEL_LIFT_M])
            q = (yield from T.tcp_move_g(ctx, ik_arm, q, p, up, yaw, yaw, g, .4))[0]
            p = up + axis * (off - cur)
            q = (yield from T.tcp_move_g(ctx, ik_arm, q, up, p, yaw, yaw, g, .5))[0]
            cur = off
        q, p, why = yield from slow_down(T, data, step, ik_arm, q, p, yaw, g, z_stop, pos0, log)
        log["feel_shifts"] = k
        if why != "contact":
            return q, p, why
        if p[2] - z_stop < ARRIVED_M:
            return q, p, "arrived"
        if not feel:
            return q, p, why
    p_end = np.array([p[0], p[1], z_stop])
    q = (yield from T.tcp_move_g(ctx, ik_arm, q, p, p_end, yaw, yaw, g, .8))[0]
    return q, p_end, "pressed"


def measure(T, data, ik_arm, q, arm, yaw):
    """The top face's centre relative to the TCP (world axes) from the wrist image alone, or None."""
    rig = rig_for(T, arm)
    fit = fit_top_face(T.world.render(data, rig.name, size=IMG), rig, ik_arm.frames(q)[2], T.layout.box, E_REF[arm], yaw)
    return fit if fit is not None and fit["score"] >= SCORE_MIN else None


def aim(T, data, ctx, step, ik_arm, q, p, yaw, g, pos0, log):
    """Wrist loop from the pose the arm stands in (p, reported): measure, correct (at most MAX_ITER times). A correction first lifts the jaw clear of the box top it may be pressing on
    (the command stands h below the jaw when the jaw is h too high), slides sideways, then goes down slowly with the contact part. Returns q, p, whether it descended."""
    arm, down, cl2 = step["arm"], False, "contact" in T.closed_loop
    for it in range(MAX_ITER):
        fit = measure(T, data, ik_arm, q, arm, yaw)
        if fit is None:
            log["wrist"].append(dict(it=it, skip="no_fit"))
            break
        err = fit["e"] - np.array(E_REF[arm])
        ent = dict(it=it, e_mm=(fit["e"] * 1000).round(1).tolist(), score=round(fit["score"], 3))
        log["wrist"].append(ent)
        if bool(np.any(np.abs(err) > PLAUSIBLE_M)):
            ent["skip"] = "implausible"
            break
        d = np.clip(err, -CLIP_M, CLIP_M)
        ent["move_mm"] = (d * 1000).round(1).tolist()
        if bool(np.all(np.abs(d) < DEAD_M)):
            break
        h, p_new = max(0., -float(d[2])), p + d
        if float(np.linalg.norm(d[:2])) > .001:
            p_up = p + np.array([0., 0., max(UP_M, h + LIFT_MARGIN_M)])
            q = (yield from T.tcp_move_g(ctx, ik_arm, q, p, p_up, yaw, yaw, g, .6))[0]
            p_side = p_up + np.array([d[0], d[1], 0.])
            q = (yield from T.tcp_move_g(ctx, ik_arm, q, p_up, p_side, yaw, yaw, g, .8))[0]
            p = p_side
        if p_new[2] < p[2] - 1e-6:
            down = True
            if cl2:
                q, p_end, log["contact"] = yield from descend(T, data, ctx, step, ik_arm, q, p, yaw, g, p_new[2], pos0, log)
            else:
                q = (yield from T.tcp_move_g(ctx, ik_arm, q, p, p_new, yaw, yaw, g, 1.0))[0]
                p_end = p_new
        else:
            q = (yield from T.tcp_move_g(ctx, ik_arm, q, p, p_new, yaw, yaw, g, 1.0))[0]
            p_end = p_new
        yield from T.settle_g(data, arm, q, g, p_end)
        p = p_end
    return q, p, down


def grasp(T, data, ctx, step, ik_arm, q, p_from, p_to, yaw, g, here, seconds):
    """The grasp phase under the loop: descend (slowly at the end with the contact part), settle, then the wrist loop. Returns q, worst IK error, the pose it stands in (reported)."""
    arm, c, cl1, cl2 = step["arm"], step["container"], "wrist" in T.closed_loop, "contact" in T.closed_loop
    ctx.cl = log = dict(wrist=[], contact=None, retry=None)
    pos0 = {o: T.world.pose(data, o)[0] for o in here if o != c}
    if cl2:
        p_mid = p_to + np.array([0., 0., HOVER_M])
        q, worst = yield from T.tcp_move_g(ctx, ik_arm, q, p_from, p_mid, yaw, yaw, g, seconds)
        q, p_end, log["contact"] = yield from descend(T, data, ctx, step, ik_arm, q, p_mid, yaw, g, p_to[2] - (0. if cl1 else FLOOR_M), pos0, log, feel=not cl1)  # with the camera it, not a blind feel, decides the shift
    else:
        q, worst = yield from T.tcp_move_g(ctx, ik_arm, q, p_from, p_to, yaw, yaw, g, seconds)
        p_end = p_to
    yield from T.settle_g(data, arm, q, g, p_end)
    if cl1:
        q, p_end, _ = yield from aim(T, data, ctx, step, ik_arm, q, p_end, yaw, g, pos0, log)
    return q, worst, p_end


def lift_watched(T, data, ctx, step, ik_arm, q, p_from, p_to, yaw_from, yaw, g_hold, seconds, g_open, here):
    """The lift with its jaw watched (the real cell's infer_holding after a lift): a box in the jaw stops it short of the closed end, a jaw that runs on to the end holds nothing.
    Once: open, go back to the hover above the close pose, aim (wrist loop) and/or feel down again, close, lift. Returns q, worst IK error, whether it retried."""
    w, arm, jaw_i, cl1 = T.world, step["arm"], T.world.q[step["arm"]][5], "wrist" in T.closed_loop
    gen, cmd = T.tcp_move_g(ctx, ik_arm, q, p_from, p_to, yaw_from, yaw, g_hold, seconds), None
    try:
        for _ in range(WATCH):
            cmd = next(gen)
            yield cmd
            if (float(data.qpos[jaw_i]) - g_open) / (g_hold - g_open) >= EMPTY_FRAC:
                break
        else:
            q, worst = yield from gen
            return q, worst, False
    except StopIteration as stop:
        return stop.value[0], stop.value[1], False
    ctx.cl["retry"] = "empty"
    q, n = cmd.copy(), round(.5 * 15)
    for i in range(1, n + 1):
        yield np.append(q[:5], g_hold + (g_open - g_hold) * i / n)
    hover = p_from + np.array([0., 0., HOVER_M])
    q = (yield from T.tcp_move_g(ctx, ik_arm, q, ik_arm.frames(q)[1], hover, yaw_from, yaw_from, g_open, 1.5))[0]
    pos0 = {o: w.pose(data, o)[0] for o in here if o != step["container"]}
    p, down, rlog = hover, False, {}
    if cl1:
        q, p, down = yield from aim(T, data, ctx, step, ik_arm, q, hover, yaw_from, g_open, pos0, ctx.cl)
    if not down:
        q, p, ctx.cl["retry_contact"] = yield from descend(T, data, ctx, step, ik_arm, q, p, yaw_from, g_open, p_from[2] - (0. if cl1 else FLOOR_M), pos0, rlog)
        yield from T.settle_g(data, arm, q, g_open, p)
    for i in range(1, round(1.5 * 15) + 1):
        yield np.append(q[:5], g_open + (g_hold - g_open) * i / round(1.5 * 15))
    q, worst = yield from T.tcp_move_g(ctx, ik_arm, q, p, p_to, yaw_from, yaw, g_hold, seconds)
    return q, worst, True
