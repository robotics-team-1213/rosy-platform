"""MuJoCo side of the container variants: the geometry and masses come from learning/envs/isaac/container_variants.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'learning/envs/isaac'))
from container_variants import NEST_MM, VARIANTS, pieces  # noqa: E402,F401


def add_container(spec, body, name, v, density):
    """Add the container geoms to body (centre of the 90 x 30 x 30 envelope at the body origin)."""
    import mujoco
    for k, (kind, data, *rest) in enumerate(pieces(v)):
        if kind == 'box':
            body.add_geom(name=f'{name}_{k}' if k else name, type=mujoco.mjtGeom.mjGEOM_BOX, size=[s/1e3 for s in data],
                          pos=[p/1e3 for p in rest[0]], density=density)
        else:
            spec.add_mesh(name=f'{name}_m{k}', uservert=data)
            body.add_geom(name=f'{name}_{k}' if k else name, type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f'{name}_m{k}', density=density)
