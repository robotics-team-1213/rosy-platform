"""Conveyor-right r05 outbound stand fixture geometry and low-friction chute collisions."""
import math

import mujoco

import omx_two_arm_sites as sites


def add_stand(spec, layout, asset_fn, colours):
    """Conveyor-right r05 outbound stand: real v6 gray chute + non-gooseneck gate on 2 floor-seated r05 plates + white U-dock."""
    stand = layout.sites.get("stand")
    if not stand:
        return
    world, box, mesh = spec.worldbody, mujoco.mjtGeom.mjGEOM_BOX, mujoco.mjtGeom.mjGEOM_MESH
    sx, sy = stand["xy"]
    rail_z = sites.OUTBOUND_STAND_SPEC["rail_z_m"]
    alpha = math.radians(24.0)
    ca, sa, ta = math.cos(alpha), math.sin(alpha), math.tan(alpha)
    z_pfloor = rail_z - (.0225 + .057 * ta)
    z_seam = z_pfloor - .008
    cx, cy = sx + .015, sy  # chute local y_l=-15 mm maps to world x=sx
    q_chute = [math.cos(-math.pi / 4), 0., 0., math.sin(-math.pi / 4)]
    q_bot = [0., math.sqrt(.5), math.sqrt(.5), 0.]  # R_z(-90) @ R_y(180): bottom r05 plate inverted
    vis = (
        ("stand_chute", "r05_outbound_chute_v6", [cx, cy, z_pfloor], q_chute, colours["chute_gray"]),
        ("stand_chute_gate", "r05_outbound_chute_gate_v6", [cx, cy, z_pfloor], q_chute, colours["chute_gate"]),
        ("stand_plate_top_deck", "r05_temp_slot_plate_deck", [cx, cy, z_seam], q_chute, colours["r05_deck"]),
        ("stand_plate_top_rim", "r05_temp_slot_plate_rim", [cx, cy, z_seam], q_chute, colours["r05_rim"]),
        ("stand_udock", "r05_outbound_udock_white", [cx, cy, 0.], q_chute, colours["dock_white"]),
    )
    for gname, mname, pos, quat, rgba in vis:
        spec.add_mesh(name=mname, file=asset_fn(mname), scale=[.001] * 3)
        world.add_geom(name=gname, type=mesh, meshname=mname, pos=pos, quat=quat, contype=0, conaffinity=0, rgba=rgba)
    for gname, mname, rgba in (("stand_plate_bot_deck", "r05_temp_slot_plate_deck", colours["r05_deck"]),
                               ("stand_plate_bot_rim", "r05_temp_slot_plate_rim", colours["r05_rim"])):
        world.add_geom(name=gname, type=mesh, meshname=mname, pos=[cx, cy, z_seam], quat=q_bot,
                       contype=0, conaffinity=0, rgba=rgba)
    # Collisions: priority=2 low friction (0.22 < tan(24 deg)) overrides container friction 1.0 (cell_physics.yaml)
    q_ramp = [math.cos(alpha / 2), 0., math.sin(alpha / 2), 0.]
    half_len, half_t = .0735 / (2 * ca), .004
    x_mid = cx + .00525
    z_top_mid = rail_z - (x_mid - sx) * ta
    kw = dict(type=box, priority=2, friction=[.22, .005, .0001], condim=4, rgba=[0, 0, 0, 0])
    world.add_geom(name="stand_ramp", pos=[x_mid - half_t * sa, cy, z_top_mid - half_t * ca],
                   size=[half_len, .0466, half_t], quat=q_ramp, **kw)
    x_bf = cx + .0265
    z_bf = rail_z - (x_bf - sx) * ta
    world.add_geom(name="stand_gate_stop", pos=[x_bf + .004 * (ca + sa), cy, z_bf + .004 * (ca - sa)],
                   size=[.004, .045, .004], quat=q_ramp, **kw)
    for gname, sg in (("stand_wall_l", 1), ("stand_wall_r", -1)):
        world.add_geom(name=gname, pos=[x_mid + .007 * sa, cy + sg * .0496, z_top_mid + .007 * ca],
                       size=[half_len, .003, .007], quat=q_ramp, **kw)
    z_back = z_pfloor + .0225 + .0735 * ta + .002
    for gname, sg in (("stand_back_l", 1), ("stand_back_r", -1)):  # 30 mm center notch clears rear gripper pad
        world.add_geom(name=gname, pos=[cx - .0345, cy + sg * .031, z_back], size=[.003, .016, .004], **kw)
