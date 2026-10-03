"""D-423 region range for camera_detect_node: the NOMINAL ground plane and the LiDAR
range in each region's bearing span. A mixin on CameraDetectNode; it reads the
node's parameters and state (_ground_mode, _ground, _nominal_ground, _scan, ...)."""
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

from .calibrated_values import finite_overrides, lidar_nose_rad, nominal_camera_profile
from .sensing.body import LIDAR_X
from .sensing.lidar import enable_simulation_scans, is_robot_scan
from .sensing.perception.camera_ground import nominal_ground_plane
from .sensing.perception.region_range import range_regions, scan_in_camera


class RegionRangeMixin:
    def _load_nominal_ground(self):
        """(plane, camera x offset) for mode 'nominal', else (None, None)."""
        if self._ground_mode != 'nominal':
            return None, None
        profile, source = nominal_camera_profile(
            str(self.get_parameter('nominal_camera_profile_path').value),
            override=finite_overrides({key: self.get_parameter(f'camera_{key}_override').value
                                       for key in ('pitch_rad', 'height_m')}))
        self.get_logger().info(f'camera profile from {source}')
        plane = nominal_ground_plane(
            source='NOMINAL', allowed=bool(self.get_parameter('allow_nominal_ground').value),
            width_px=int(self.get_parameter('width').value),
            height_px=int(self.get_parameter('height').value), profile=profile)
        if plane is None:
            self.get_logger().warn('NOMINAL ground refused (allow_nominal_ground false or '
                                   'profile incomplete); regions stay unranged')
        return plane, profile.get('x_offset_m')

    def _start_region_lidar(self):
        """Subscribe scan for region range only with the NOMINAL plane (read once, at start)."""
        if not bool(self.get_parameter('region_lidar_range').value):
            return
        if self._nominal_ground is None:
            self.get_logger().warn('region_lidar_range needs camera_ground_mode nominal with a '
                                   'NOMINAL plane; scan not subscribed')
            return
        if bool(self.get_parameter('accept_simulation_scans').value):
            enable_simulation_scans(True)  # process-wide: every is_robot_scan caller in this process
        self._lidar_nose, source = lidar_nose_rad(override=finite_overrides(
            {'lidar_yaw_offset': self.get_parameter('lidar_yaw_offset_override').value}))
        self.get_logger().info(f'region LiDAR range on; lidar forward from {source}')
        self.create_subscription(LaserScan, 'scan', self._on_scan, qos_profile_sensor_data)

    def _on_scan(self, msg):
        if is_robot_scan(msg):
            self._scan = msg
        elif self._scan is None and not self._scan_rejected_logged:
            self._scan_rejected_logged = True
            self.get_logger().warn('scan arrives but is not from the onboard C1 (is_robot_scan); '
                                   'Gazebo needs accept_simulation_scans')

    def _lidar_ranged(self, regions, capture_stamp):
        """D-423: LiDAR range per region; unchanged without a fresh scan or the NOMINAL plane."""
        scan, value = self._scan, lambda name: float(self.get_parameter(name).value)
        if (scan is None or self._lidar_nose is None or self._camera_x_m is None or self._ground is None
                or self._ground is not self._nominal_ground
                or abs(scan.header.stamp.sec + scan.header.stamp.nanosec * 1e-9 - capture_stamp)
                > value('region_lidar_max_age_s')):
            return regions
        points = scan_in_camera(scan.ranges, scan.angle_min, scan.angle_increment, scan.range_min,
                                scan.range_max, nose_rad=self._lidar_nose, lidar_x_m=LIDAR_X,
                                camera_x_m=float(self._camera_x_m))
        return range_regions(regions, self._ground, points, tolerance_m=value('region_lidar_tolerance_m'),
                             tolerance_ratio=value('region_lidar_tolerance_ratio'))
