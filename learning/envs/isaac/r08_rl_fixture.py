"""Pinned A/B CAD layout for the r08 ship PPO scenario."""
from pathlib import Path
import subprocess
import sys

CASE = "r08-v24-cad194"
PRESET = "v24-20261114-cad194"


def cell_layout():
    sim = str(Path(__file__).resolve().parents[3] / "tools/sim")
    if sim not in sys.path:
        sys.path.insert(0, sim)
    from omx_two_arm_sites import Layout
    return Layout(preset=PRESET)


def layout_digest(layout):
    from omx_two_arm_sites import layout_digest as digest

    return digest(layout)


def request_for(layout, seed, layers):
    identity = layout_digest(layout)
    if identity != layout_digest(cell_layout()):
        raise ValueError("MuJoCo layout differs from the approved Isaac r08 layout")
    return dict(seed=seed, layers=layers, case=CASE, layout_sha256=identity)


def require_sdk(binding):
    if binding["sdk_version"] != "6.2.0.0":
        raise ValueError("r08 PPO requires the declared Isaac Sim 6.2 SDK")
    result = subprocess.run([binding["sdk_python"], "-c",
                             "from importlib.metadata import version; print(version('mujoco'))"],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("r08 PPO requires MuJoCo for the shared CAD contact geometry")


def fixture(layers, nominal):
    """Keep PPO task settings while replacing legacy geometry with actual CAD datums."""
    import numpy as np
    if type(layers) is not int or layers not in (1, 2, 3):
        raise ValueError("r08 stacking requires layers 1, 2 or 3")
    layout = cell_layout()
    from omx_physics import Physics
    from omx_two_arm_sites import ARMS, ship_cell
    mass = Physics(layout.choices["physics"]).container()["mass"]
    items = []
    for index, (cid, name, arm) in enumerate(layout.plan_order()[:layers * 3]):
        site = layout.sites[name]
        items.append(dict(id=cid, cells=3, cell=[0, site["row"], site["layer"]],
                          size=list(layout.box), mass=mass,
                          arm=ARMS.index(arm), color_rgb=nominal["cargo_colors_rgb"][index % 3],
                          target=[*site["xy"], site["z"]]))
    targets = np.asarray([item["target"] for item in items])
    half = np.asarray(layout.box) / 2
    low, high = targets.min(axis=0) - half, targets.max(axis=0) + half
    arms = list(layout.arms.values())
    bases = [(arm.base - arm.R0 @ np.array([*arm.j1_offset_xy, 0.])).tolist() for arm in arms]
    stop_x, belt_y, surface = layout.belt_stop_x, layout.belt_y, layout.belt_top
    pickup_x = layout.sites["belt"]["xy"][0]
    value = dict(nominal, case=CASE, revision=CASE, coordinate_scope="ROSY_TWO_ARM_CELL_LAYOUT",
                 layout_sha256=layout_digest(layout), stack_plan=items, r08_scene=True,
                 arm_bases_m=bases, arm_base_yaws_rad=[arm.yaw for arm in arms],
                 home_joints_rad=[[arm.wait[0], -.4, .7, 1.27, 0.] for arm in arms],
                 tcp_offset_m=layout.sim_arms[ARMS[0]].tcp.tolist(), real_cameras=layout.fixture["real_cameras"],
                 ship_stern_m=list(ship_cell(layout, 0, 0)), workplate_center_m=layout.fixture["workplate_center_m"],
                 workplate_size_m=layout.fixture["workplate_size_m"],
                 belt_source_z_m=surface, belt_center_m=[stop_x + .15, belt_y, surface - .002],
                 belt_stop_m=[stop_x, belt_y, surface + .004], belt_stop_size_m=[.004, .085, .008],
                 belt_pitch_rad=0., belt_size_m=[.3, .085, .004], belt_velocity_m_s=[-.02, 0., 0.],
                 pickup_center_m=[pickup_x, belt_y, surface + half[2]],
                 belt_probe_start_m=[pickup_x + .04, belt_y, surface + half[2]],
                 cargo_mass_kg=[.02, .04, mass],
                 bin_origin_m=low.tolist(), bin_size_m=(high - low).tolist(),
                 gripper="palletizing-v2.1", row_order=[item["cell"][1] for item in items[:3]])
    for key in ("leveling_protocol", "planning_scene", "ship_plate"):
        value.pop(key, None)
    from omx_two_arm_sites import round_coordinates

    return round_coordinates(value)
