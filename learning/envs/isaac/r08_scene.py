"""Author the shared r08 CAD and its decomposed contact shapes in PhysX."""
import os

from r08_rl_fixture import cell_layout, layout_digest


def add_structure(stage, fixture):
    import numpy as np
    from pxr import Gf, UsdGeom, UsdPhysics, UsdShade, Vt

    layout = cell_layout()
    if layout_digest(layout) != fixture["layout_sha256"]:
        raise RuntimeError("Approved r08 fixture and authored geometry differ")
    os.environ.setdefault("MUJOCO_GL", "disable")
    from omx_two_arm_world import World, mujoco

    scene = World(layout=layout)
    with scene.meshes:
        model, data = scene.model, scene.reset()
        bin_root = UsdGeom.Xform.Define(stage, "/World/Bin")
        UsdPhysics.RigidBodyAPI.Apply(bin_root.GetPrim()).CreateKinematicEnabledAttr(True)
        UsdGeom.Xform.Define(stage, "/World/CellStructures")
        material = UsdShade.Material.Get(stage, "/World/GripMaterial")
        for index in range(model.ngeom):
            if model.geom_bodyid[index] != 0:
                continue
            name = model.geom(index).name
            if name in {"floor", "table", "belt", "belt_stop", "ship_house", "cx_house"}:
                continue
            ship_contact = name == "cx_bow" or name.startswith(("stern", "hold"))
            temp_contact = name.startswith(("deck_", "wa", "wb"))
            collides = ship_contact or temp_contact
            rgba = model.geom_rgba[index]
            if not collides and rgba[3] <= 0:
                continue
            path = f"/World/{'Bin' if ship_contact else 'CellStructures'}/{name}"
            if model.geom_type[index] == mujoco.mjtGeom.mjGEOM_MESH:
                mesh = model.geom_dataid[index]
                vertex, count = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
                points = model.mesh_vert[vertex:vertex + count]
                face, count = model.mesh_faceadr[mesh], model.mesh_facenum[mesh]
                faces = model.mesh_face[face:face + count]
                shape = UsdGeom.Mesh.Define(stage, path)
                shape.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(points)))
                shape.CreateFaceVertexCountsAttr([3] * len(faces))
                shape.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.ravel()))
                shape.CreateSubdivisionSchemeAttr("none")
                if collides:
                    UsdPhysics.MeshCollisionAPI.Apply(shape.GetPrim()).CreateApproximationAttr("convexHull")
            elif model.geom_type[index] == mujoco.mjtGeom.mjGEOM_BOX:
                shape = UsdGeom.Cube.Define(stage, path)
                shape.CreateSizeAttr(2.)
            else:
                raise RuntimeError(f"Unsupported r08 geometry {name}: {model.geom_type[index]}")
            transform = np.eye(4)
            transform[:3, :3] = data.geom_xmat[index].reshape(3, 3).T
            transform[3, :3] = data.geom_xpos[index]
            shape.AddTransformOp().Set(Gf.Matrix4d(*transform.ravel()))
            if isinstance(shape, UsdGeom.Cube):
                shape.AddScaleOp().Set(Gf.Vec3d(*model.geom_size[index].tolist()))
            shape.CreateDisplayColorAttr([Gf.Vec3f(*rgba[:3].tolist())])
            if collides:
                shape.CreatePurposeAttr("guide")
                UsdPhysics.CollisionAPI.Apply(shape.GetPrim())
                UsdShade.MaterialBindingAPI.Apply(shape.GetPrim()).Bind(
                    material, UsdShade.Tokens.weakerThanDescendants, "physics")


def add_cargo_visual(stage, body, item):
    """Draw the printed container v3 over its same-sized box contact proxy."""
    from pxr import Gf, UsdGeom, Vt
    from palletizing_gripper import _triangles
    from omx_two_arm_sites import SHIP_ASSETS

    triangles = _triangles(SHIP_ASSETS / "container_1x3_v3.stl")
    mesh = UsdGeom.Mesh.Define(stage, body.GetPath().AppendChild("PrintedContainer"))
    size = item["size"]
    points = [Gf.Vec3f(*(tri[3 * vertex + axis] / 1000 / size[axis] - .5 for axis in range(3)))
              for tri in triangles for vertex in range(3)]
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateSubdivisionSchemeAttr("none")
    mesh.CreateFaceVertexCountsAttr([3] * len(triangles))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(list(range(len(points)))))
    mesh.CreateDisplayColorAttr([Gf.Vec3f(*item["color_rgb"])])
    mesh.CreatePurposeAttr(UsdGeom.Tokens.default_)
    UsdGeom.Cube(body).CreatePurposeAttr("guide")
