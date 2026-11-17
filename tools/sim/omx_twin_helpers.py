"""Open-loop servo tracking (`lag_s`, `track`, `tracking`), silhouette/edge alignment (`silhouette`, `offset`, `view_one`), and episode replay for `omx_twin`."""
import io
import json
import math
from pathlib import Path
import sys
import zlib

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parents[1] / "deploy/robot/omx")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import numpy as np  # noqa: E402

KPS = (10.0, 15.0, 20.0, 30.0, 40.0, 60.0, 80.0)  # 40 is omx_cell_sim's actuator gain
ARM_LINKS = ("link1", "link2", "link3", "link4", "link5", "link6", "link7")
LIMIT_PX = {"top": 3, "side": 3, "wrist": 5}  # D-947 proposed camera match
SEARCH_PX, STEP_PX = 24, 2
GRID_HZ = 50
SCHEMA = "rosy.omx-twin-episode.v2"


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
    cell.model.body_gravcomp[cell.model.body("box").id] = 1
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
    per_joint = [min(rows, key=lambda r: r["rms_deg"][j]) for j in range(5)]
    kp = [r["kp"] for r in per_joint]
    sim = track(cell, ticks, np.array(kp), best["gravity_comp"])
    err = np.degrees(sim - real)
    fitted = dict(kp=kp, gravity_comp=best["gravity_comp"], rms_deg=np.sqrt((err ** 2).mean(0)).round(2).tolist(),
                  lag_s=[lag_s(g, cmd[:, j], sim[:, j]) for j in range(5)])
    return dict(fitted=fitted, seconds=round(float(g[-1] - g[0]), 1), real_lag_s=real_lag,
                real_follow_rms_deg=np.sqrt((np.degrees(real - cmd) ** 2).mean(0)).round(2).tolist(),
                grid=rows, best=dict(kp=best["kp"], gravity_comp=best["gravity_comp"], rms_deg=best["rms_deg"]),
                best_per_joint=[dict(kp=r["kp"], gravity_comp=r["gravity_comp"], rms_deg=r["rms_deg"][j]) for j, r in enumerate(per_joint)])


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


def physics_zero(cell):
    """The cell's physics candidate's zero_offset_deg for j1-j5 (sim q = real + offset; the sim cell is arm_b)."""
    return [cell.physics.joint("arm_b", f"joint{k}").get("zero_offset_deg", 0.) for k in range(1, 6)]


def posed(cell, state, zero_deg=None):
    import mujoco
    import omx_cell_sim as cs
    data = mujoco.MjData(cell.model)
    data.qpos[cell.qadr] = cs.real_q(state)
    data.qpos[cell.qadr[:5]] += np.radians(physics_zero(cell) if zero_deg is None else zero_deg)
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]
    mujoco.mj_forward(cell.model, data)
    return data


def view_one(cell, renderer, geoms, state, frames, cams, zero_deg=None):
    """{sim camera: offset dict} for one real state and its real frames ({episode camera: jpeg bytes})."""
    data = posed(cell, state, zero_deg)
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


def replay(folder, cell_path, out, cams, every_s=2.0, worst=4, physics="design"):
    """twin.json (+ worst overlays) for one episode folder. Resumable: an existing twin.json is the result."""
    import mujoco
    import omx_cell_sim as cs
    folder, out = Path(folder), Path(out)
    if (out / "twin.json").exists():
        done = json.loads((out / "twin.json").read_text())
        if done.get("schema") == SCHEMA and done.get("physics", "design") == physics:
            return done
    out.mkdir(parents=True, exist_ok=True)
    cell = cs.Cell(cell_path, physics)
    ticks, picked = samples(folder, every_s, cams)
    result = dict(schema=SCHEMA, episode=folder.name, cell=str(cell_path), physics=physics, cams=cams,
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


def shard_of(name, shard):
    """`i/n`: this host's share of the names, stable across reruns and hosts (zlib crc, not Python's salted hash)."""
    i, n = (int(x) for x in shard.split("/"))
    return zlib.crc32(name.encode()) % n == i
