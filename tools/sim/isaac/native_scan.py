"""PhysX scene queries in the imported LiDAR frame; no map-derived ranges."""
import math


def scan_sample(cast, transform_direction, *, robot_path, stamp_ns):
    if (type(stamp_ns) is not int or stamp_ns < 0 or not isinstance(robot_path, str)
            or not robot_path.startswith('/') or robot_path.endswith('/')):
        raise ValueError('native robot path and physics timestamp required')
    ranges = []
    increment = 2 * math.pi / 640
    for index in range(640):
        angle = -math.pi + index * increment
        direction = tuple(transform_direction((math.cos(angle), math.sin(angle), 0.)))
        if (len(direction) != 3 or not all(math.isfinite(v) for v in direction)
                or not math.isclose(sum(v * v for v in direction), 1., abs_tol=1e-5)):
            raise ValueError('unit native sensor direction required')
        nearest = [math.inf]
        def report(hit):
            path, distance = hit.collision, hit.distance
            if (not isinstance(path, str) or not path.startswith('/')
                    or not math.isfinite(distance) or not 0 <= distance <= 12.):
                raise ValueError('invalid native raycast hit')
            if path != robot_path and not path.startswith(robot_path + '/'):
                nearest[0] = min(nearest[0], distance)
            return True
        cast(direction, report)
        # No hit remains UNKNOWN, including after ignoring own collision geometry.
        ranges.append(nearest[0])
    return dict(ranges=ranges, frame_id='rplidar_link', range_min=.05, range_max=12.,
                angle_min=-math.pi, angle_max=math.pi - increment, angle_increment=increment,
                source_stamp_ns=stamp_ns, source_now_ns=stamp_ns)


class NativeScan:
    def __init__(self, stage):
        import omni.physx
        from pxr import UsdGeom
        matches = [p for p in stage.Traverse() if p.GetName() == 'rplidar_link'
                   and str(p.GetPath()).startswith('/World/Imported/')]
        if len(matches) != 1:
            raise RuntimeError('unique imported native LiDAR frame required')
        self.prim = matches[0]
        self.cache = UsdGeom.XformCache()
        self.query = omni.physx.get_physx_scene_query_interface()

    def capture(self, physics_time):
        import carb
        from pxr import Gf
        if not math.isfinite(physics_time) or physics_time < 0:
            raise ValueError('finite physics capture time required')
        self.cache.Clear()
        transform = self.cache.GetLocalToWorldTransform(self.prim)
        origin = carb.Float3(*transform.Transform(Gf.Vec3d(0.)))
        def cast(direction, report):
            self.query.raycast_all(origin, carb.Float3(*direction), 12., report)
        return scan_sample(cast, lambda ray: transform.TransformDir(Gf.Vec3d(*ray)),
                           robot_path='/World/Imported', stamp_ns=round(physics_time * 1e9))
