"""Shared Gazebo floor visuals; collision and motion remain with the native runner."""
import math
import xml.etree.ElementTree as ET


def configure_ground_collision(stage, ground_path):
    """Keep the SDK ground's display mesh out of the physical contact solver."""
    from pxr import UsdPhysics, UsdShade

    mesh = stage.GetPrimAtPath(ground_path + '/geom')
    plane = stage.GetPrimAtPath(ground_path + '/collisionPlane')
    if (not mesh or not plane or mesh.GetTypeName() != 'Mesh' or plane.GetTypeName() != 'Plane'
            or not mesh.HasAPI(UsdPhysics.CollisionAPI) or not plane.HasAPI(UsdPhysics.CollisionAPI)
            or UsdPhysics.CollisionAPI(plane).GetCollisionEnabledAttr().Get() is not True):
        raise RuntimeError('Unexpected SDK ground collision layout')
    targets = mesh.GetRelationship('material:binding:physics').GetTargets()
    if len(targets) != 1 or not stage.GetPrimAtPath(targets[0]).HasAPI(UsdPhysics.MaterialAPI):
        raise RuntimeError('SDK ground physics material missing')
    # Isaac 5.1 wraps /geom as a collider beside the already active collisionPlane.
    UsdPhysics.CollisionAPI(mesh).GetCollisionEnabledAttr().Set(False)
    UsdShade.MaterialBindingAPI.Apply(plane).Bind(
        UsdShade.Material(stage.GetPrimAtPath(targets[0])), materialPurpose='physics')
    if (UsdPhysics.CollisionAPI(mesh).GetCollisionEnabledAttr().Get() is not False
            or plane.GetRelationship('material:binding:physics').GetTargets() != targets):
        raise RuntimeError('Single ground collision readback failed')
    result = dict(collider=str(plane.GetPath()), visual_collision=False, material=str(targets[0]))
    verify_ground_collision(stage, ground_path, result)
    return result


def verify_ground_collision(stage, ground_path, expected):
    """Reject reset-time changes or competing ground contacts without repairing them."""
    from pxr import UsdPhysics, UsdShade

    active = [str(prim.GetPath()) for prim in stage.Traverse()
              if str(prim.GetPath()).startswith(ground_path + '/')
              and prim.HasAPI(UsdPhysics.CollisionAPI)
              and UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get()]
    plane = stage.GetPrimAtPath(expected['collider'])
    material, _ = UsdShade.MaterialBindingAPI(plane).ComputeBoundMaterial(materialPurpose='physics')
    if active != [expected['collider']] or not material or str(material.GetPath()) != expected['material']:
        raise RuntimeError('Single ground collision or resolved material changed')


def floor_visuals(map_root):
    world = ET.parse(map_root / 'training-curved/worlds/map_v2_fleet_real.world')
    result = []
    for model in world.findall('./world/model'):
        if model.get('name') == 'ground_plane':
            continue
        parent = tuple(map(float, model.findtext('pose', '0 0 0 0 0 0').split()))
        for link in model.findall('link'):
            local = tuple(map(float, link.findtext('pose', '0 0 0 0 0 0').split()))
            for visual in link.findall('visual'):
                plane = visual.find('geometry/plane')
                if plane is None:
                    continue
                pose = tuple(map(float, visual.findtext('pose', '0 0 0 0 0 0').split()))
                if (any(len(p) != 6 or not all(math.isfinite(v) for v in p)
                        for p in (parent, local, pose)) or any(parent[3:] + local[3:])):
                    raise ValueError('floor visual requires finite poses and unrotated parents')
                size = tuple(map(float, plane.findtext('size').split()))
                colour = tuple(map(float, visual.findtext('material/diffuse').split()))
                if (plane.findtext('normal') != '0 0 1' or len(size) != 2
                        or not all(math.isfinite(v) and v > 0 for v in size)
                        or len(colour) != 4 or not all(0 <= v <= 1 for v in colour)):
                    raise ValueError('invalid floor visual geometry or colour')
                uri = visual.findtext('material/pbr/metal/albedo_map')
                texture = None
                if uri is not None:
                    prefix = 'model://control/map/map_v2_fleet/'
                    if not uri.startswith(prefix):
                        raise ValueError('floor texture must belong to the shared map')
                    texture = (map_root / uri[len(prefix):]).resolve()
                    if not texture.is_relative_to(map_root.resolve()) or not texture.is_file():
                        raise ValueError('floor texture missing or outside the shared map')
                result.append(dict(name='_'.join((model.get('name'), link.get('name'), visual.get('name'))),
                    pose=tuple(parent[i] + local[i] + pose[i] for i in range(3)) + pose[3:],
                    size=size, colour=colour[:3], texture=texture))
    if not result:
        raise ValueError('shared floor visuals missing')
    return result


def add_floor_visuals(stage, visuals):
    from pxr import Gf, Sdf, UsdGeom, UsdShade

    for visual in visuals:
        path = '/World/Track/floor_' + visual['name']
        mesh = UsdGeom.Mesh.Define(stage, path)
        x, y = (v / 2 for v in visual['size'])
        mesh.CreatePointsAttr([(-x, -y, 0), (x, -y, 0), (x, y, 0), (-x, y, 0)])
        mesh.CreateFaceVertexCountsAttr([4])
        mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
        mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateDoubleSidedAttr(True)
        mesh.AddTranslateOp().Set(Gf.Vec3d(*visual['pose'][:3]))
        mesh.AddRotateXYZOp().Set(Gf.Vec3f(*(math.degrees(v) for v in visual['pose'][3:])))
        material = UsdShade.Material.Define(stage, path + '/Material')
        shader = UsdShade.Shader.Define(stage, path + '/Material/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(1.)
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*visual['colour']))
        if visual['texture'] is not None:
            UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray,
                UsdGeom.Tokens.vertex).Set([(0, 0), (1, 0), (1, 1), (0, 1)])
            reader = UsdShade.Shader.Define(stage, path + '/Material/Coordinates')
            reader.CreateIdAttr('UsdPrimvarReader_float2')
            reader.CreateInput('varname', Sdf.ValueTypeNames.String).Set('st')
            reader.CreateOutput('result', Sdf.ValueTypeNames.Float2)
            texture = UsdShade.Shader.Define(stage, path + '/Material/Texture')
            texture.CreateIdAttr('UsdUVTexture')
            texture.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
            texture.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(str(visual['texture']))
            texture.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB')
            texture.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*visual['colour'], 1.))
            texture.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
            shader.GetInput('diffuseColor').ConnectToSource(texture.ConnectableAPI(), 'rgb')
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)


def map_visual_profile(map_root):
    world = ET.parse(map_root / 'training-curved/worlds/map_v2_fleet_real.world')
    ground = world.find('./world/model[@name="ground_plane"]/link/visual')
    colour = tuple(map(float, ground.findtext('material/diffuse').split()))
    size = tuple(map(float, ground.findtext('geometry/plane/size').split()))
    pose = tuple(map(float, world.findtext('./world/model[@name="road_lines"]/pose').split()))
    if (len(colour) != 4 or not all(0 <= v <= 1 for v in colour) or colour[3] != 1
            or len(size) != 2 or not all(math.isfinite(v) and v > 0 for v in size)
            or size[0] != size[1] or len(pose) != 6 or not all(math.isfinite(v) for v in pose)):
        raise ValueError('invalid shared ground or paint profile')
    return dict(ground_colour=colour[:3], ground_size=size[0], paint_pose=pose,
                planes=floor_visuals(map_root))


def add_track_visuals(stage, track, profile):
    from pxr import Gf, UsdGeom, UsdPhysics

    scene = track['scene']
    UsdGeom.Xform.Define(stage, '/World/Track')
    for i, wall in enumerate(scene.walls):
        cube = UsdGeom.Cube.Define(stage, f'/World/Track/wall_{i}')
        cube.CreateSizeAttr(1.)
        cube.AddTranslateOp().Set(Gf.Vec3d(wall.cx, wall.cy, wall.height / 2))
        cube.AddScaleOp().Set(Gf.Vec3d(wall.size_x, wall.size_y, wall.height))
        cube.CreateDisplayColorAttr([Gf.Vec3f(1.)])
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    for part in [dict(name='paint', triangles=scene.lines, colour=[1., 1., 1.]),
                 *track['caution_meshes']]:
        paint = UsdGeom.Mesh.Define(stage, '/World/Track/' + part['name'])
        vertices = [Gf.Vec3f(*v) for t in part['triangles'] for v in t]
        paint.CreatePointsAttr(vertices)
        paint.CreateFaceVertexCountsAttr([3] * len(part['triangles']))
        paint.CreateFaceVertexIndicesAttr(list(range(len(vertices))))
        paint.CreateSubdivisionSchemeAttr('none')
        paint.CreateDoubleSidedAttr(True)
        paint.CreateDisplayColorAttr([Gf.Vec3f(*part['colour'])])
        if part['name'] == 'paint':
            pose = profile['paint_pose']
            paint.AddTranslateOp().Set(Gf.Vec3d(*pose[:3]))
            paint.AddRotateXYZOp().Set(Gf.Vec3f(*(math.degrees(v) for v in pose[3:])))
    add_floor_visuals(stage, profile['planes'])
