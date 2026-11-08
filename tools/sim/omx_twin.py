#!/usr/bin/env python3
"""The real OMX cell beside its MuJoCo twin: where the simulator and the real arm part ways (sim2real, D-480 tiers M/R).

Two gaps, measured on the real cell's own episodes (deploy/robot/omx/episode_recorder.py) and on its live state:
  tracking  the real action stream replayed open loop into the MuJoCo cell for a grid of joint gains, with and without
            the sim's ideal gravity compensation; per joint RMS and lag against what the real servos did. The gain that
            follows the real arm best is the candidate correction (D-877 says the sim gains are not tuned to the arm).
  view      at sampled ticks the real joint state is posed in the sim and each mapped camera's arm silhouette is laid
            over the real frame; the shift (px) where the silhouette sits on the real edges is the camera/kinematics gap
            (D-947: 3 px top/side, 5 px wrist). A low score at every shift means the frame shows no arm there: another
            arm's episode, a moved camera or a wrong camera role.

Run on a lab PC (MuJoCo + EGL, never the operator laptop, D-584); the site PC only serves files (D-571):
  omx_twin.py replay EP_DIR --cell CELL --out DIR
  omx_twin.py batch --site HOST --root ROOT --episodes A,B,.. --cell CELL --out DIR [--jobs N]    resumable
  omx_twin.py live --site HOST --live LIVE_JSON --cell CELL --out DIR [--period 2] [--minutes M]
  omx_twin.py report DIR [DIR ..]                                                               no MuJoCo needed
Geometry and servo following only: contact and image photometry are Isaac's (D-947).
"""
import argparse
import base64
import io
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import shlex
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "deploy/robot/omx")]
import numpy as np  # noqa: E402

KPS = (10.0, 15.0, 20.0, 30.0, 40.0, 60.0, 80.0)  # 40 is omx_cell_sim's actuator gain
ARM_LINKS = ("link1", "link2", "link3", "link4", "link5", "link6", "link7")
LIMIT_PX = {"top": 3, "side": 3, "wrist": 5}  # D-947 proposed camera match
SEARCH_PX, STEP_PX = 24, 2
GRID_HZ = 50
SCHEMA = "rosy.omx-twin-episode.v2"


# -- tracking -------------------------------------------------------------------------------------------------------------------
def lag_s(t, reference, follower, max_s=.6):
    """Delay (s) of follower behind reference on one joint, by least squares over shifts of the 50 Hz grid."""
    shifts = range(int(max_s * GRID_HZ) + 1)
    errors = [np.mean((follower[k:] - reference[:len(reference) - k]) ** 2) if k < len(t) - 10 else np.inf for k in shifts]
    return int(np.argmin(errors)) / GRID_HZ


def grid(ticks, key):
    t = np.array([r["t"] for r in ticks])
    g = np.arange(t[0], t[-1], 1 / GRID_HZ)
    v = np.array([r[key] for r in ticks])
    return g, np.stack([np.interp(g, t, v[:, j]) for j in range(v.shape[1])], 1)


def set_kp(cell, kp):
    """One gain for joint1-5, or one per joint."""
    m = cell.model
    for a, k in zip(cell.act[:5], np.broadcast_to(kp, 5)):
        m.actuator_gainprm[a, 0], m.actuator_biasprm[a, 1] = k, -k


def track(cell, ticks, kp, gravity_comp):
    """Sim joint1-5 (rad) on the 50 Hz grid when the real actions drive it from the real start state."""
    import mujoco
    import omx_cell_sim as cs
    set_kp(cell, kp)
    data = mujoco.MjData(cell.model)
    data.qpos[cell.qadr] = cs.real_q(ticks[0]["state"])
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]
    cell.model.body_gravcomp[cell.model.body("box").id] = 1  # the box stays out of the way, not falling for minutes
    mujoco.mj_forward(cell.model, data)
    dt = cell.model.opt.timestep
    g, actions = grid(ticks, "action")
    out = np.empty((len(g), 5))
    for k in range(len(g)):
        data.ctrl[cell.act] = cs.real_q(actions[k])
        for _ in range(round(1 / GRID_HZ / dt)):
            if gravity_comp:
                data.qfrc_applied[cell.arm_dof] = data.qfrc_bias[cell.arm_dof]
            mujoco.mj_step(cell.model, data)
        out[k] = data.qpos[cell.qadr[:5]]
    return out


def tracking(cell, ticks):
    import omx_cell_sim as cs
    g, state = grid(ticks, "state")
    _, action = grid(ticks, "action")
    real = cs.norm_to_rad(state[:, :5])
    cmd = cs.norm_to_rad(action[:, :5])
    real_lag = [lag_s(g, cmd[:, j], real[:, j]) for j in range(5)]
    rows = []
    for gc in (True, False):
        for kp in KPS:
            sim = track(cell, ticks, kp, gc)
            err = np.degrees(sim - real)
            rows.append(dict(kp=kp, gravity_comp=gc, rms_deg=np.sqrt((err ** 2).mean(0)).round(2).tolist(),
                             p95_deg=np.percentile(np.abs(err), 95, 0).round(2).tolist(),
                             mean_deg=err.mean(0).round(2).tolist(),
                             lag_s=[lag_s(g, cmd[:, j], sim[:, j]) for j in range(5)]))
    best = min(rows, key=lambda r: float(np.mean(r["rms_deg"])))
    per_joint = [min(rows, key=lambda r: r["rms_deg"][j]) for j in range(5)]  # the real servos do not share one gain
    kp = [r["kp"] for r in per_joint]
    sim = track(cell, ticks, np.array(kp), best["gravity_comp"])  # the joints are coupled: check the combination itself
    err = np.degrees(sim - real)
    fitted = dict(kp=kp, gravity_comp=best["gravity_comp"], rms_deg=np.sqrt((err ** 2).mean(0)).round(2).tolist(),
                  lag_s=[lag_s(g, cmd[:, j], sim[:, j]) for j in range(5)])
    return dict(fitted=fitted,seconds=round(float(g[-1] - g[0]), 1), real_lag_s=real_lag,
                real_follow_rms_deg=np.sqrt((np.degrees(real - cmd) ** 2).mean(0)).round(2).tolist(),
                grid=rows, best=dict(kp=best["kp"], gravity_comp=best["gravity_comp"], rms_deg=best["rms_deg"]),
                best_per_joint=[dict(kp=r["kp"], gravity_comp=r["gravity_comp"], rms_deg=r["rms_deg"][j]) for j, r in enumerate(per_joint)])


# -- view -----------------------------------------------------------------------------------------------------------------------
def arm_geoms(cell):
    m = cell.model
    bodies = {m.body(n).id for n in ARM_LINKS}
    return np.array([g for g in range(m.ngeom) if m.geom_bodyid[g] in bodies and m.geom_rgba[g, 3] > 0])


def silhouette(cell, renderer, data, camera, geoms):
    import mujoco
    opt = cell.show_link5 if camera != "wrist" else None
    renderer.enable_segmentation_rendering()
    renderer.update_scene(data, camera=camera, scene_option=opt)
    seg = renderer.render()
    renderer.disable_segmentation_rendering()
    mask = (seg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & np.isin(seg[..., 0], geoms)
    renderer.update_scene(data, camera=camera, scene_option=opt)
    return mask, renderer.render().copy()


def outline(mask):
    inner = mask & np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1)
    return mask & ~inner


def edge_strength(rgb):
    gray = rgb.astype(float).mean(2)
    gy, gx = np.gradient(gray)
    g = np.hypot(gx, gy)
    return g / (g.mean() + 1e-6)


def offset(strength, edge):
    """Shift (dx, dy) px of the sim outline that lands on the strongest real edges; score = mean edge there / frame mean."""
    ys, xs = np.nonzero(edge)
    if len(ys) < 40:
        return None
    h, w = strength.shape
    best = (-1, 0, 0)
    for dy in range(-SEARCH_PX, SEARCH_PX + 1, STEP_PX):
        for dx in range(-SEARCH_PX, SEARCH_PX + 1, STEP_PX):
            s = strength[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)].mean()
            if s > best[0]:
                best = (s, dx, dy)
    return dict(dx=best[1], dy=best[2], px=round(math.hypot(best[1], best[2]), 1), score=round(float(best[0]), 2),
                score0=round(float(strength[ys, xs].mean()), 2), outline_px=int(len(ys)))


def overlay(real, sim, edge, o):
    """Real frame with the sim outline where the model puts it (green) and where the real edges are (magenta), sim beside."""
    from PIL import Image
    img = real.copy()
    ys, xs = np.nonzero(edge)
    h, w = edge.shape
    img[ys, xs] = (0, 255, 0)
    if o:
        img[np.clip(ys + o["dy"], 0, h - 1), np.clip(xs + o["dx"], 0, w - 1)] = (255, 0, 255)
    return Image.fromarray(np.concatenate([img, sim], 1))


def load_rgb(blob, shape=(480, 640)):
    from PIL import Image
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    if im.size != (shape[1], shape[0]):
        im = im.resize((shape[1], shape[0]))
    return np.asarray(im)


def view_one(cell, renderer, geoms, state, frames, cams):
    """{sim camera: offset dict} for one real state and its real frames ({episode camera: jpeg bytes})."""
    import mujoco
    import omx_cell_sim as cs
    data = mujoco.MjData(cell.model)
    data.qpos[cell.qadr] = cs.real_q(state)
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]
    mujoco.mj_forward(cell.model, data)
    out, pictures = {}, {}
    for real_name, sim_name in cams.items():
        if real_name not in frames:
            continue
        real = load_rgb(frames[real_name])
        mask, sim = silhouette(cell, renderer, data, sim_name, geoms)
        edge = outline(mask)
        o = offset(edge_strength(real), edge)
        out[sim_name] = o
        pictures[sim_name] = (real, sim, edge, o)
    return out, pictures


def parse_cams(text):
    return dict(pair.split("=") for pair in text.split(",") if pair)


# -- episodes -------------------------------------------------------------------------------------------------------------------
def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def samples(folder, every_s, cams):
    """(tick, {camera: seq}) every `every_s` seconds, each with the latest frame at or before it (episode_recorder.aligned)."""
    from episode_recorder import aligned
    ticks = read_jsonl(folder / "ticks.jsonl")
    frames = {c: read_jsonl(folder / f"{c}.jsonl") for c in cams if (folder / f"{c}.jsonl").exists()}
    out, last = [], -1e9
    for row, seqs in aligned(ticks, frames):
        if row["t"] - last >= every_s:
            out.append((row, seqs))
            last = row["t"]
    return ticks, out


def replay(folder, cell_path, out, cams, every_s=2.0, worst=4):
    """twin.json (+ worst overlays) for one episode folder. Resumable: an existing twin.json is the result."""
    import mujoco
    import omx_cell_sim as cs
    folder, out = Path(folder), Path(out)
    if (out / "twin.json").exists():
        done = json.loads((out / "twin.json").read_text())
        if done.get("schema") == SCHEMA:  # an older result (other gain grid, no fit) is measured again
            return done
    out.mkdir(parents=True, exist_ok=True)
    cell = cs.Cell(cell_path)
    ticks, picked = samples(folder, every_s, cams)
    result = dict(schema=SCHEMA, episode=folder.name, cell=str(cell_path), cams=cams,
                  real=json.loads((folder / "result.json").read_text()) if (folder / "result.json").exists() else None)
    result["tracking"] = tracking(cell, ticks) if len(ticks) > 50 else None
    set_kp(cell, KPS[2])
    renderer = mujoco.Renderer(cell.model, 480, 640)
    geoms = arm_geoms(cell)
    views, keep = [], {}
    for row, seqs in picked:
        blobs = {c: (folder / c / f"{s:06d}.jpg").read_bytes() for c, s in seqs.items() if (folder / c / f"{s:06d}.jpg").exists()}
        o, pictures = view_one(cell, renderer, geoms, row["state"], blobs, cams)
        views.append(dict(t=row["t"], **o))
        for name, pic in pictures.items():
            if pic[3]:
                keep.setdefault(name, []).append((pic[3]["px"], row["t"], pic))
    for name, rows in keep.items():
        for px, t, pic in sorted(rows, key=lambda r: -r[0])[:worst]:
            overlay(*pic).save(out / f"worst-{name}-{t:.1f}.jpg", quality=80)
    result["view"] = summarise_views(views)
    result["views"] = views
    (out / "twin.json").write_text(json.dumps(result, indent=1))
    return result


def summarise_views(views):
    out = {}
    for name in {k for v in views for k in v if k != "t"}:
        rows = [v[name] for v in views if v.get(name)]
        if not rows:
            continue
        px = np.array([r["px"] for r in rows])
        out[name] = dict(n=len(rows), median_px=float(np.median(px)), p90_px=float(np.percentile(px, 90)),
                         median_dx=float(np.median([r["dx"] for r in rows])), median_dy=float(np.median([r["dy"] for r in rows])),
                         median_score=float(np.median([r["score"] for r in rows])),
                         limit_px=LIMIT_PX.get(name), within=bool(np.median(px) <= LIMIT_PX.get(name, 5)))
    return out


# -- site access (read only) ----------------------------------------------------------------------------------------------------
def ssh(host, command, data=None, timeout=300):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command], input=data,
                          capture_output=True, timeout=timeout, check=True).stdout


def fetch(site, root, name, dest, every_s, cams):
    """Copy one episode's rows and only the sampled frames from the site PC into dest/name."""
    import tarfile
    folder = Path(dest) / name
    if (folder / ".fetched").exists():
        return folder
    q = shlex.quote(f"{root}/{name}")
    small = ssh(site, f"cd {q} && tar -cf - --ignore-failed-read task.json result.json ticks.jsonl " + " ".join(f"{c}.jsonl" for c in cams))
    folder.mkdir(parents=True, exist_ok=True)
    tarfile.open(fileobj=io.BytesIO(small)).extractall(folder)
    _, picked = samples(folder, every_s, cams)
    wanted = sorted({f"{c}/{s:06d}.jpg" for _, seqs in picked for c, s in seqs.items()})
    if wanted:
        blob = ssh(site, f"cd {q} && tar -cf - --ignore-failed-read -T -", data="\n".join(wanted).encode())
        tarfile.open(fileobj=io.BytesIO(blob)).extractall(folder)
    (folder / ".fetched").touch()
    return folder


def one_episode(job):
    site, root, name, cell, out, every_s, cams = job
    try:
        folder = fetch(site, root, name, Path(out) / "episodes", every_s, cams)
        r = replay(folder, cell, Path(out) / "twin" / name, cams, every_s)
        return name, "ok", (r.get("tracking") or {}).get("best")
    except Exception as e:  # one bad episode must not stop the night
        return name, f"error {type(e).__name__}: {e}", None


def closed_episodes(site, root, since):
    """Episode folder names on the site whose result.json exists (the recorder closed them), from `since` (YYYYMMDD) on."""
    text = ssh(site, f"cd {shlex.quote(root)} && ls -d */result.json 2>/dev/null || true").decode()
    return sorted(n.split("/")[0] for n in text.split() if n.split("/")[0][:8] >= since)


def shard_of(name, shard):
    """`i/n`: this host's share of the names, stable across reruns and hosts (zlib crc, not Python's salted hash)."""
    import zlib
    i, n = (int(x) for x in shard.split("/"))
    return zlib.crc32(name.encode()) % n == i


def batch(args):
    """Replay the named episodes, or with --watch every closed episode of this shard as it appears, until the deadline."""
    done, end = set(), time.time() + 60 * (args.watch or 0)
    with ProcessPoolExecutor(args.jobs) as pool:
        while True:
            names = [n for n in args.episodes.split(",") if n] if args.episodes else closed_episodes(args.site, args.root, args.since)
            todo = [n for n in names if n not in done and shard_of(n, args.shard)]
            jobs = [(args.site, args.root, n, args.cell, args.out, args.every, parse_cams(args.cams)) for n in todo]
            for name, status, best in pool.map(one_episode, jobs):
                done.add(name)
                print(json.dumps(dict(episode=name, status=status, best=best)), flush=True)
            if not args.watch or time.time() + args.poll >= end:
                return 0
            time.sleep(args.poll)


# -- camera fit -----------------------------------------------------------------------------------------------------------------
STEPS = {"x": .004, "y": .004, "z": .004, "rx": .4, "ry": .4, "rz": .4, "fovy": .3}  # m, deg (camera frame), deg
JOINT_STEPS = {f"j{k}": .4 for k in range(1, 6)}  # deg added to the real joint reading (a zero offset)


def posed(cell, state, zero_deg=None):
    import mujoco
    import omx_cell_sim as cs
    data = mujoco.MjData(cell.model)
    data.qpos[cell.qadr] = cs.real_q(state)
    if zero_deg is not None:
        data.qpos[cell.qadr[:5]] += np.radians(zero_deg)
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]
    mujoco.mj_forward(cell.model, data)
    return data


def apply_delta(cell, camera, base, delta):
    """Camera pose = surveyed pose moved by delta: x/y/z in the world (m), rx/ry/rz about the camera's own axes (deg)."""
    import mujoco
    m, i = cell.model, cell.model.camera(camera).id
    pos, quat, fovy = base
    m.cam_pos[i] = pos + [delta.get("x", 0.), delta.get("y", 0.), delta.get("z", 0.)]
    turn, q = np.zeros(4), quat.copy()
    for axis, key in (([1., 0, 0], "rx"), ([0, 1., 0], "ry"), ([0, 0, 1.], "rz")):
        mujoco.mju_axisAngle2Quat(turn, np.array(axis), math.radians(delta.get(key, 0.)))
        mujoco.mju_mulQuat(q, q.copy(), turn)
    m.cam_quat[i], m.cam_fovy[i] = q, fovy + delta.get("fovy", 0.)


def fit_camera(args):
    """Fit the camera pose and/or the joints' zero offsets (--params) to the real frames of most episodes; judge on the
    held-out ones (every third by crc). Either can absorb the other's error: confirm with a still photo and a joint
    reading at a known pose before the cell file or the calibration changes."""
    import mujoco
    import omx_cell_sim as cs
    cams = {args.real_camera: args.camera}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = closed_episodes(args.site, args.root, args.since)
    items = {"fit": [], "hold": []}
    for name in names:
        try:
            folder = fetch(args.site, args.root, name, out / "episodes", args.every, cams)
        except Exception as e:
            print(f"[fit] skip {name}: {e}", file=sys.stderr)
            continue
        _, picked = samples(folder, args.every, cams)
        for row, seqs in picked[::max(1, len(picked) // args.per_episode)]:
            jpg = folder / args.real_camera / f"{seqs[args.real_camera]:06d}.jpg"
            if jpg.exists():
                items["hold" if shard_of(name, "0/3") else "fit"].append((row["state"], edge_strength(load_rgb(jpg.read_bytes()))))
    cell = cs.Cell(args.cell)
    renderer, geoms = mujoco.Renderer(cell.model, 480, 640), arm_geoms(cell)
    steps = {**(STEPS if args.params in ("camera", "both") else {}), **(JOINT_STEPS if args.params in ("joints", "both") else {})}
    i = cell.model.camera(args.camera).id
    base = (cell.model.cam_pos[i].copy(), cell.model.cam_quat[i].copy(), float(cell.model.cam_fovy[i]))

    def edges(data):
        mujoco.mj_camlight(cell.model, data)  # a changed model camera reaches data only through this
        return outline(silhouette(cell, renderer, data, args.camera, geoms)[0])

    def zero_deg(delta):
        return [delta.get(f"j{k}", 0.) for k in range(1, 6)]

    def score(delta, which="fit"):
        apply_delta(cell, args.camera, base, delta)
        vals = []
        for state, g in items[which]:
            ys, xs = np.nonzero(edges(posed(cell, state, zero_deg(delta))))
            if len(ys) >= 40:
                vals.append(g[ys, xs].mean())
        return float(np.mean(vals)) if vals else 0.

    def hold_px(delta):
        apply_delta(cell, args.camera, base, delta)
        px = [o["px"] for state, g in items["hold"] if (o := offset(g, edges(posed(cell, state, zero_deg(delta)))))]
        return float(np.median(px)) if px else None

    zero = {k: 0. for k in steps}
    delta, best = dict(zero), score(zero)
    start = best
    for scale in (4, 2, 1, .5):  # coordinate ascent, step halving
        moved = True
        while moved:
            moved = False
            for key, step in steps.items():
                for sign in (1, -1):
                    trial = dict(delta, **{key: delta[key] + sign * step * scale})
                    s = score(trial)
                    if s > best + 1e-3:
                        delta, best, moved = trial, s, True
                        break
    result = dict(schema="rosy.omx-twin-view-fit.v1", camera=args.camera, params=args.params, cell=str(args.cell),
                  n_fit=len(items["fit"]), n_hold=len(items["hold"]), delta={k: round(v, 4) for k, v in delta.items()},
                  fit_score=[round(start, 3), round(best, 3)], hold_score=[round(score(zero, "hold"), 3), round(score(delta, "hold"), 3)],
                  hold_median_px=[hold_px(zero), hold_px(delta)], limit_px=LIMIT_PX.get(args.camera))
    apply_delta(cell, args.camera, base, delta)
    result.update(pos=cell.model.cam_pos[i].round(5).tolist(), quat=cell.model.cam_quat[i].round(6).tolist(),
                  fovy=round(float(cell.model.cam_fovy[i]), 3))
    (out / f"view-fit-{args.params}.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result))
    return 0


# -- live -----------------------------------------------------------------------------------------------------------------------
LIVE_READ = r"""import base64, json, sys, urllib.request
out = {"live": json.load(open(sys.argv[1])), "frames": {}}
for name, url in json.loads(sys.argv[2]).items():
    try:
        out["frames"][name] = base64.b64encode(urllib.request.urlopen(url, timeout=3).read()).decode()
    except Exception as e:
        out["frames"][name] = None
print(json.dumps(out))
"""


def live(args):
    """Every `period` s: the live state posed in the sim against the live frames; a camera off by more than its limit
    for `alarm` reads in a row is printed as ALARM. Rows in live.jsonl, the latest overlay per camera as latest-<cam>.jpg."""
    import mujoco
    import omx_cell_sim as cs
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cell = cs.Cell(args.cell)
    renderer, geoms = mujoco.Renderer(cell.model, 480, 640), arm_geoms(cell)
    cams = parse_cams(args.cams)
    urls = {c: f"http://127.0.0.1:8767/frame/{c}.jpg" for c in cams}
    streak, end, last_t = {}, time.time() + 60 * args.minutes, None
    with (out / "live.jsonl").open("a") as log:
        while time.time() < end:
            start = time.time()
            try:
                got = json.loads(ssh(args.site, f"python3 -c {shlex.quote(LIVE_READ)} {shlex.quote(args.live)} {shlex.quote(json.dumps(urls))}", timeout=20))
            except Exception as e:
                print(f"[twin-live] site read failed: {e}", file=sys.stderr, flush=True)
                time.sleep(args.period)
                continue
            state = got["live"].get("state")
            frames = {c: base64.b64decode(b) for c, b in got["frames"].items() if b}
            fresh, last_t = got["live"].get("t") != last_t, got["live"].get("t")  # the runner is not running: nothing new
            if state and fresh:
                o, pictures = view_one(cell, renderer, geoms, state, frames, cams)
                target = got["live"].get("target")
                row = dict(t=got["live"].get("t"), read=start, view=o, lag=got["live"].get("lag"), fault=got["live"].get("fault"),
                           follow_deg=(np.degrees(cs.norm_to_rad(state[:5]) - cs.norm_to_rad(target[:5])).round(2).tolist() if target else None))
                log.write(json.dumps(row) + "\n")
                log.flush()
                for name, pic in pictures.items():
                    overlay(*pic).save(out / f"latest-{name}.jpg", quality=80)
                    bad = pic[3] is None or pic[3]["px"] > LIMIT_PX.get(name, 5)
                    streak[name] = streak.get(name, 0) + 1 if bad else 0
                    if streak[name] == args.alarm:
                        print(f"[twin-live] ALARM {name}: sim and real disagree {args.alarm} reads in a row ({pic[3]})", flush=True)
            time.sleep(max(0., args.period - (time.time() - start)))
    return 0


# -- report ---------------------------------------------------------------------------------------------------------------------
def report(dirs):
    """Markdown over every twin.json: the gain that follows the real arm, real vs sim lag, and the camera gap."""
    results = [json.loads(p.read_text()) for d in dirs for p in sorted(Path(d).rglob("twin.json"))]
    if not results:
        print("no twin.json under", *dirs)
        return 1
    lines = [f"# OMX twin report: {len(results)} real episodes", ""]
    tracked = [r for r in results if r.get("tracking")]
    if tracked:
        keys = sorted({(g["kp"], g["gravity_comp"]) for r in tracked for g in r["tracking"]["grid"]})
        lines += ["## Tracking: sim driven by the real actions, RMS deg against the real joints (mean over episodes)", "",
                  "| kp | gravity comp | j1 | j2 | j3 | j4 | j5 | mean |", "|---|---|---|---|---|---|---|---|"]
        for kp, gc in keys:
            rms = np.array([g["rms_deg"] for r in tracked for g in r["tracking"]["grid"] if (g["kp"], g["gravity_comp"]) == (kp, gc)])
            m = rms.mean(0)
            lines.append(f"| {kp:g} | {'on' if gc else 'off'} | " + " | ".join(f"{v:.2f}" for v in m) + f" | {m.mean():.2f} |")
        real_lag = np.array([r["tracking"]["real_lag_s"] for r in tracked]).mean(0)
        best = [r["tracking"]["best"] for r in tracked]
        lines += ["", f"Real servo lag behind the command (s, j1-j5): {' '.join(f'{v:.2f}' for v in real_lag)}",
                  "Best (kp, gravity comp) per episode: " + ", ".join(f"{k}={sum(1 for b in best if (b['kp'], b['gravity_comp']) == k)}"
                                                                     for k in sorted({(b['kp'], b['gravity_comp']) for b in best})),
                  "Per-joint gains together (mean RMS deg j1-j5): " + " ".join(
                      f"{v:.2f}" for v in np.mean([r["tracking"]["fitted"]["rms_deg"] for r in tracked if "fitted" in r["tracking"]] or [[np.nan] * 5], 0)),
                  "Median best kp per joint (j1-j5): " + " ".join(f"{np.median([r['tracking']['best_per_joint'][j]['kp'] for r in tracked]):g}"
                                                                  for j in range(5)), ""]
    lines += ["## View: sim arm outline against the real frame", "",
              "| episode | real outcome | camera | median px | p90 px | median dx,dy | score | within |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        outcome = (r.get("real") or {}).get("outcome") or (r.get("real") or {}).get("why") or "-"
        for name, v in sorted((r.get("view") or {}).items()):
            lines.append(f"| {r['episode']} | {outcome} | {name} | {v['median_px']:.1f} | {v['p90_px']:.1f} | "
                         f"{v['median_dx']:+.0f},{v['median_dy']:+.0f} | {v['median_score']:.2f} | {'yes' if v['within'] else 'NO'} |")
    lines += ["", "A score near 1 means the outline found no arm edges: not this arm's episode, a moved camera or a wrong role.",
              "Candidate gap rows go to tools/harness/sim2real_gaps.yaml only with this report as evidence (D-480)."]
    print("\n".join(lines))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("replay", "batch", "live"):
        s = sub.add_parser(name)
        s.add_argument("--cell", required=True)
        s.add_argument("--out", required=True)
        s.add_argument("--cams", default="top=top,arm_b_wrist=wrist", help="episode camera=sim camera, comma separated (sim: top, side, wrist); the sim cell is arm_b, so only arm_b_wrist is its wrist ('front' was arm_a's wrist, retired 2026-11-08)")
    sub.choices["replay"].add_argument("episode")
    sub.choices["replay"].add_argument("--every", type=float, default=2.0)
    b = sub.choices["batch"]
    for flag in ("--site", "--root"):
        b.add_argument(flag, required=True)
    b.add_argument("--episodes", help="comma separated names; default: every closed episode from --since")
    b.add_argument("--since", default="20261101", help="YYYYMMDD; the top camera is the surveyed D435 from 11-01")
    b.add_argument("--shard", default="0/1")
    b.add_argument("--watch", type=float, default=0, help="minutes to keep picking up newly closed episodes")
    b.add_argument("--poll", type=float, default=300)
    b.add_argument("--every", type=float, default=2.0)
    b.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    v = sub.choices["live"]
    v.add_argument("--site", required=True)
    v.add_argument("--live", required=True, help="live.json path on the site PC (chunk_runner's chunk-io)")
    v.add_argument("--period", type=float, default=2.0)
    v.add_argument("--minutes", type=float, default=600)
    v.add_argument("--alarm", type=int, default=3)
    sub.add_parser("report").add_argument("dirs", nargs="+")
    f = sub.add_parser("fit-camera")
    for flag in ("--cell", "--out", "--site", "--root"):
        f.add_argument(flag, required=True)
    f.add_argument("--since", default="20261101")
    f.add_argument("--camera", default="top")
    f.add_argument("--real-camera", default="top")
    f.add_argument("--every", type=float, default=2.0)
    f.add_argument("--per-episode", type=int, default=6)
    f.add_argument("--params", choices=("camera", "joints", "both"), default="camera")
    a = p.parse_args(argv)
    if a.command == "fit-camera":
        return fit_camera(a)
    if a.command == "report":
        return report(a.dirs)
    if a.command == "replay":
        replay(a.episode, a.cell, a.out, parse_cams(a.cams), a.every)
        return 0
    return batch(a) if a.command == "batch" else live(a)


if __name__ == "__main__":
    raise SystemExit(main())
