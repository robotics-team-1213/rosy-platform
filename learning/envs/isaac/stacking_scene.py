"""Cargo bodies, contact probes and still images for the OMX stacking scene (split from stacking_task, D-766)."""
from stacking_fixture import UNIT


def add_cargo(world, stage, plan, links, material, fixture, *, mapped, cube):
    """One dynamic box per plan item with its contact view; containers get collision-free visual ribs."""
    import numpy as np
    from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics
    from isaacsim.core.api.objects import DynamicCuboid
    from isaacsim.core.prims import RigidPrim
    colors = {1: [.03, .08, .24], 2: [.15, .65, .25], 3: [.95, .4, .08]}
    cargo, contacts = [], []
    filters = [link[key] for link in links for key in ('link6', 'link7')]
    for i, item in enumerate(plan):
        box = world.scene.add(DynamicCuboid('/World/Cargo'+str(i), name='cargo'+str(i), size=1.,
            scale=np.array([UNIT*item['cells'], UNIT, UNIT]), mass=.02*item['cells'],
            position=np.array([.7, -.5+i*.065, .015]), color=np.array(item.get('color_rgb', colors[item['cells']])),
            physics_material=material))
        cargo.append(box)
        if cube:
            # Visual details inherit the cargo transform; the nominal box remains its only collider.
            def panel(name, position, scale, shade):
                panel = UsdGeom.Cube.Define(stage, box.prim.GetPath().AppendChild(name))
                panel.CreateSizeAttr(1.)
                transform = UsdGeom.XformCommonAPI(panel.GetPrim())
                transform.SetTranslate(Gf.Vec3d(*position))
                transform.SetScale(Gf.Vec3f(*scale))
                panel.CreateDisplayColorAttr([Gf.Vec3f(*(v*shade for v in item['color_rgb']))])
                assert not panel.GetPrim().HasAPI(UsdPhysics.CollisionAPI)
                assert not panel.GetPrim().HasAPI(UsdPhysics.RigidBodyAPI)
            for side in (-1, 1):
                for rib, x in enumerate((-.36, -.18, 0., .18, .36)):
                    panel(f'Rib{"Left" if side < 0 else "Right"}{rib}', [x, side*.502, 0.], [.025, .006, .88], .72)
            panel('DoorSeam', [.502, 0., 0.], [.006, .012, .88], .55)
            for side in (-1, 1):
                panel('DoorBar'+('Left' if side < 0 else 'Right'), [.506, side*.17, 0.], [.008, .015, .76], .55)
        if mapped:
            # Resolve the small stacked contacts with the same solver budget as the arms.
            body = PhysxSchema.PhysxRigidBodyAPI.Apply(box.prim)
            body.CreateSolverPositionIterationCountAttr(64)
            body.CreateSolverVelocityIterationCountAttr(16)
            assert body.GetSolverVelocityIterationCountAttr().Get() == 16
        contacts.append(world.scene.add(RigidPrim('/World/Cargo'+str(i), name='contact'+str(i),
            track_contact_forces=True, contact_filter_prim_paths_expr=filters+['/World/Bin']+(['/World/Conveyor'] if mapped else [])+
            ['/World/Cargo'+str(j) for j in range(len(plan)) if j != i]+(['/World/Table'] if fixture.get('leveling_protocol') else []),
            max_contact_count=512 if cube else 128)))
    return cargo, contacts


def add_probes(world, stage, links, plan, arm_roots, *, mapped, probed):
    """Wrist pose views (mapped) and per-link grasp contact probes against the other arm and the scene."""
    from pxr import Usd, UsdPhysics
    from isaacsim.core.prims import RigidPrim
    wrist_views, grasp_probes = [], []
    if mapped:
        for i, link in enumerate(links):
            path = stage.GetPrimAtPath(link['end_effector_link']).GetParent().GetPath()
            wrist_views.append(world.scene.add(RigidPrim(str(path), name='wrist_pose'+str(i))))
    probe_filters = ['/World/Table', '/World/PlywoodMap', '/World/Conveyor', '/World/BeltStop', '/World/Bin']+[
        '/World/Cargo'+str(i) for i in range(len(plan))]
    if probed:
        body_paths = [[str(p.GetPath()) for p in Usd.PrimRange(root) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
                      for root in arm_roots]
        for i in range(2):
            views = []
            filters = probe_filters+body_paths[1-i]
            for j, path in enumerate(body_paths[i][1:]):
                view = world.scene.add(RigidPrim(path, name=f'grasp_probe_{i}_{j}', track_contact_forces=True,
                    contact_filter_prim_paths_expr=filters, max_contact_count=128))
                views.append((path, view))
            grasp_probes.append((filters, views))
    return wrist_views, grasp_probes


def capture(world, camera, eye, path, *, container, overview=False):
    """Render the observer camera from the named viewpoint and save an 800x600 PNG at `path`."""
    import numpy as np
    from pxr import Gf
    from PIL import Image
    position = Gf.Vec3d(2.2, -2.2, 3.) if overview else eye
    focus = Gf.Vec3d(0., 1.1, 0.) if overview else Gf.Vec3d(.13, -.10, .12)
    if container and overview:
        position, focus = Gf.Vec3d(2.4,-3.,2.8),Gf.Vec3d(.15,-.65,.03)
    up = Gf.Vec3d(0., 0., 1.)
    if path.name == 'mapped-top.png':
        position, focus, up = Gf.Vec3d(.16, .10, 1.25), Gf.Vec3d(.16, .10, 0.), Gf.Vec3d(0., 1., 0.)
    elif path.name == 'mapped-side.png':
        position, focus = Gf.Vec3d(.8, -.05, .16), Gf.Vec3d(.03, 0., .08)
    rotation = Gf.Matrix4d().SetLookAt(position, focus, up).GetInverse().ExtractRotationQuat()
    camera.set_world_pose(np.array(position), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
    for _ in range(8):
        world.render()
    rgba = camera.get_rgba()
    if rgba is None or rgba.shape != (600, 800, 4):
        raise RuntimeError('Actual SDK image unavailable')
    Image.fromarray(rgba.astype(np.uint8)).save(path)
