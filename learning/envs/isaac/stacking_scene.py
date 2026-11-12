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
            scale=np.array([UNIT*item['cells'], UNIT, UNIT]), mass=(fixture.get('cargo_mass_kg') or [.02, .04, .06])[item['cells']-1],
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
        if cube and fixture.get('container_variant', 'plain') != 'plain':
            variant_colliders(stage, box, item['cells']*UNIT, fixture['container_variant'])
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


def variant_colliders(stage, box, length, name):
    """Replace the cuboid collider by the convex pieces of container variant `name` (container_variants.py); the cuboid stays the
    body and the visual. The prim is scaled to the container size, so the piece points are divided by that scale."""
    from pxr import Gf, UsdGeom, UsdPhysics, UsdShade, Vt
    import container_variants as cv
    UsdPhysics.CollisionAPI(box.prim).CreateCollisionEnabledAttr(False)
    scale, material = (length, UNIT, UNIT), UsdShade.Material.Get(stage, '/World/GripMaterial')
    for k, (kind, data, *rest) in enumerate(cv.pieces(cv.VARIANTS[name], length)):
        if kind == 'box':
            points = [(rest[0][0]+sx*data[0], rest[0][1]+sy*data[1], rest[0][2]+sz*data[2]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
            points = [tuple(c/1e3 for c in p) for p in points]
        else:
            points = [tuple(data[i:i+3]) for i in range(0, len(data), 3)]
        piece = UsdGeom.Mesh.Define(stage, box.prim.GetPath().AppendChild(f'Piece{k}'))
        piece.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*(c/s for c, s in zip(p, scale))) for p in points]))
        tris = cv.hull_triangles(points)
        piece.CreateFaceVertexCountsAttr(Vt.IntArray([3]*len(tris)))
        piece.CreateFaceVertexIndicesAttr(Vt.IntArray([i for t in tris for i in t]))
        piece.CreatePurposeAttr('guide')
        UsdPhysics.CollisionAPI.Apply(piece.GetPrim())
        UsdPhysics.MeshCollisionAPI.Apply(piece.GetPrim()).CreateApproximationAttr('convexHull')
        UsdShade.MaterialBindingAPI.Apply(piece.GetPrim()).Bind(material, UsdShade.Tokens.weakerThanDescendants, 'physics')


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


def real_camera(cameras, name, spec):
    """The surveyed real camera `name` (D-947 3): its pose, resolution and focal length in pixels; created once into `cameras`."""
    import numpy as np
    from isaacsim.sensors.camera import Camera
    from pxr import Gf
    if name not in cameras:
        position, focus, up = (Gf.Vec3d(*spec[k]) for k in ('eye', 'focus', 'up'))
        rotation = Gf.Matrix4d().SetLookAt(position, focus, up).GetInverse().ExtractRotationQuat()
        camera = Camera('/World/Real_'+name, position=np.array(position), resolution=(spec['width'], spec['height']))
        camera.initialize()
        camera.set_world_pose(np.array(position), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
        camera.set_clipping_range(.01, 10.)
        aperture = 36.  # mm; focal length in mm follows from the focal length in pixels
        for key, value in (('horizontalAperture', aperture), ('verticalAperture', aperture*spec['height']/spec['width']),
                           ('focalLength', spec['f_px']*aperture/spec['width'])):
            camera.prim.GetAttribute(key).Set(value)
        cameras[name] = camera
    return cameras[name]


WRIST_VIEW_SIZE = (640, 360)  # the 1280x720 wrist sensor at half size


def wrist_camera(cameras, name, link_path, spec):
    """A camera on the arm's link5 at the wrist-holder lens pose (palletizing_gripper.wrist_camera_pose); moves with the arm."""
    import math
    import numpy as np
    from isaacsim.sensors.camera import Camera
    from palletizing_gripper import wrist_camera_pose
    if name not in cameras:
        width, height = WRIST_VIEW_SIZE
        lens, quat = wrist_camera_pose(spec)
        camera = Camera(link_path+'/WristCamera', resolution=(width, height))
        camera.initialize()
        camera.set_local_pose(np.array(lens), np.array(quat), camera_axes='usd')
        camera.set_clipping_range(.005, 10.)
        f_px = height/2/math.tan(math.radians(spec['vfov_deg'])/2)
        aperture = 36.
        for key, value in (('horizontalAperture', aperture), ('verticalAperture', aperture*height/width),
                           ('focalLength', f_px*aperture/width)):
            camera.prim.GetAttribute(key).Set(value)
        cameras[name] = camera
    return cameras[name]


WRIST_PARTS = ('link5_gripper', 'gripper_plate_F6', 'b16-u16-span-D-holder-assembly')  # assets/omx_wrist_camera_b


def team_wrist_visual(stage, link5):
    """Draw link5 as the team's wrist (gripper body, plate F6, B camera holder) instead of the stock mesh, whose ROBOTIS
    camera frame F9 sits 2.6 mm from the B lens and filled a third of the wrist image (run f3c208d1). Visual only:
    the colliders, link6 and link7 stay as imported."""
    from pathlib import Path
    from pxr import Gf, UsdGeom, Vt
    from palletizing_gripper import _triangles
    # The importer puts link5's mesh in instanceable children (follower_06_pan_Revised = visual, ..._1 = guide collider);
    # visibility never changes physics, so every child but the finger links is hidden.
    stock = [c for c in stage.GetPrimAtPath(link5).GetChildren() if c.GetName() not in ('link6', 'link7')]
    if not stock:
        raise RuntimeError(f'no stock visual found under {link5}')
    for prim in stock:
        UsdGeom.Imageable(prim).MakeInvisible()
    for name in WRIST_PARTS:
        tris = _triangles(Path(__file__).resolve().parent/'assets/omx_wrist_camera_b'/f'{name}.stl')
        mesh = UsdGeom.Mesh.Define(stage, f'{link5}/team_visuals/{name.replace("-", "_")}')
        mesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(t[3*i]/1e3, t[3*i+1]/1e3, t[3*i+2]/1e3) for t in tris for i in range(3)]))
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3]*len(tris)))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(list(range(3*len(tris)))))
        mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateDisplayColorAttr(Vt.Vec3fArray([Gf.Vec3f(.12, .12, .13)]))


def demo_views(cameras, fixture, stage, links):
    """The surveyed real views, plus one wrist camera per arm (arm_a_wrist, arm_b_wrist) when the case sets wrist_camera."""
    views = {view: real_camera(cameras, view, fixture['real_cameras'][view]) for view in fixture['real_cameras']}
    if fixture.get('wrist_camera'):
        for arm, link in zip(('arm_a', 'arm_b'), links):
            link5 = str(stage.GetPrimAtPath(link['end_effector_link']).GetParent().GetPath())
            team_wrist_visual(stage, link5)
            views[arm+'_wrist'] = wrist_camera(cameras, arm+'_wrist', link5, fixture['wrist_camera'])
    return views


def real_capture(world, cameras, name, spec, path):
    """Render one surveyed real camera and save a PNG at `path`."""
    import numpy as np
    from PIL import Image
    camera = real_camera(cameras, name, spec)
    for _ in range(8):
        world.render()
    rgba = camera.get_rgba()
    if rgba is None or rgba.shape != (spec['height'], spec['width'], 4):
        raise RuntimeError('Actual SDK image unavailable')
    Image.fromarray(rgba.astype(np.uint8)).save(path)


def add_ship_plate(stage, fixture):
    """The navy stud plate: one kinematic (never moving) body at /World/Bin, so the cargo contact views see plate and studs as
    'bin'. Visual mesh with the CAD chamfered dots; colliders are a plate box and one convex-hull mesh per dot (ship_plate.stud_solid). A static triangle-mesh collider gave inconsistent vertical contact forces (run s42p)."""
    from pxr import Gf, UsdGeom, UsdPhysics, UsdShade, Vt
    import ship_plate
    spec = fixture['ship_plate']
    body = UsdGeom.Xform.Define(stage, '/World/Bin')
    UsdPhysics.RigidBodyAPI.Apply(body.GetPrim()).CreateKinematicEnabledAttr(True)
    points, tris, plate_faces = ship_plate.mesh(fixture)
    mesh = UsdGeom.Mesh.Define(stage, '/World/Bin/Visual')
    mesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*p) for p in points]))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3]*len(tris)))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray([i for t in tris for i in t]))
    mesh.CreateSubdivisionSchemeAttr('none')
    navy, stud = Gf.Vec3f(.04, .07, .22), Gf.Vec3f(.85, .88, .92)
    color = mesh.CreateDisplayColorAttr(Vt.Vec3fArray([navy]*plate_faces+[stud]*(len(tris)-plate_faces)))
    UsdGeom.Primvar(color).SetInterpolation('uniform')
    material = UsdShade.Material.Get(stage, '/World/GripMaterial')

    def collider(prim):
        prim.CreatePurposeAttr('guide')
        UsdPhysics.CollisionAPI.Apply(prim.GetPrim())
        UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(material, UsdShade.Tokens.weakerThanDescendants, 'physics')
    outline, top = ship_plate.outline(fixture), ship_plate.top_z(fixture)
    x0, x1, cy = min(x for x, _ in outline), max(x for x, _ in outline), ship_plate.stack_centre(fixture)[1]
    plate = UsdGeom.Cube.Define(stage, '/World/Bin/PlateCollider')
    plate.CreateSizeAttr(1.)
    pose = UsdGeom.Xformable(plate)
    pose.AddTranslateOp().Set(Gf.Vec3d((x0+x1)/2, cy, top-spec['thickness_m']/2))
    pose.AddScaleOp().Set(Gf.Vec3f(x1-x0, 2*max(abs(y-cy) for _, y in outline), spec['thickness_m']))
    collider(plate)
    solid, solid_tris = ship_plate.stud_solid(spec)
    for n, (x, y) in enumerate(ship_plate.stud_positions(fixture)):
        dot = UsdGeom.Mesh.Define(stage, f'/World/Bin/Stud{n}')
        dot.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*p) for p in solid]))
        dot.CreateFaceVertexCountsAttr(Vt.IntArray([3]*len(solid_tris)))
        dot.CreateFaceVertexIndicesAttr(Vt.IntArray([i for t in solid_tris for i in t]))
        UsdGeom.Xformable(dot).AddTranslateOp().Set(Gf.Vec3d(x, y, top))
        UsdPhysics.MeshCollisionAPI.Apply(dot.GetPrim()).CreateApproximationAttr('convexHull')
        collider(dot)
    if fixture.get('berth_kit') == 'v16-modular':
        add_cell_structures(stage, fixture)


def add_cell_structures(stage, fixture):
    """Add the surveyed CAD cell structures (PR33_C02_BASE, bridge v7, plate v11, and r08 + v16 berth-modular cradles/spacer bridges/concave stopper)."""
    import math
    from pathlib import Path
    from pxr import Gf, UsdGeom, Vt
    from palletizing_gripper import _triangles
    assets = Path(__file__).resolve().parent / 'assets/ship_r08_berth'
    table_z = fixture['workplate_center_m'][2] + fixture['workplate_size_m'][2] / 2
    root = UsdGeom.Xform.Define(stage, '/World/CellStructures')

    def place_stl(prim_path, stl_name, pos_m, yaw_rad=0., rgb=(.5, .72, .85)):
        tris = _triangles(assets / f'{stl_name}.stl')
        mesh = UsdGeom.Mesh.Define(stage, prim_path)
        mesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(t[3*i]/1e3, t[3*i+1]/1e3, t[3*i+2]/1e3) for t in tris for i in range(3)]))
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3]*len(tris)))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(list(range(3*len(tris)))))
        mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateDisplayColorAttr(Vt.Vec3fArray([Gf.Vec3f(*rgb)]))
        xf = UsdGeom.XformCommonAPI(mesh.GetPrim())
        xf.SetTranslate(Gf.Vec3d(*pos_m))
        if yaw_rad:
            xf.SetRotate(Gf.Vec3f(0., 0., math.degrees(yaw_rad)))
        return mesh

    for idx, tag in enumerate(('a', 'b')):
        bx, by, _ = fixture['arm_bases_m'][idx]
        place_stl(f'/World/CellStructures/BasePlate_{tag}', f'omx_base_plate_{tag}', (bx, by, table_z), 0., (.16, .17, .19))
        if fixture.get('temp_bridge', 'v7') == 'v7':
            place_stl(f'/World/CellStructures/TempBridge_{tag}', f'temp_slot_bridge_{tag}', (bx, by, table_z), 0., (.92, .68, .22))
        plate_xy = (bx - .200, by)
        place_stl(f'/World/CellStructures/TempPlate_{tag}', 'temp_slot_plate_v11', (plate_xy[0], plate_xy[1], table_z), 0., (.52, .69, .79))

    stern_x = fixture.get('ship_stern_x_m', .178)
    centre_y = fixture.get('ship_centre_y_m', -.001)
    for name, rgb in (
        ('hull', (.50, .72, .85)),
        ('house', (.50, .72, .85)),
        ('berth_v16_cradle', (.88, .48, .16)),
        ('berth_v16_bridges', (.92, .68, .22)),
        ('berth_v16_stopper', (.22, .62, .52)),
    ):
        place_stl(f'/World/CellStructures/Ship_{name}', name, (stern_x, centre_y, table_z), math.pi, rgb)
    return root
