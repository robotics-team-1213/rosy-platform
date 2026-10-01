"""Production camera graph and frame publication, with capture deliberately disabled."""
import ast
import unittest
from pathlib import Path

try:
    import numpy as np
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from sensor_msgs.msg import CompressedImage, Image
    from std_msgs.msg import Bool, Float32, String
    from rclpy.qos import ReliabilityPolicy
    # The class body is exec'd against the node module's own globals.
    import control.camera_detect_node as camera_module
except ImportError:
    rclpy = None


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class CameraGraphTests(unittest.TestCase):
    def test_camera_topics_and_image_frame_are_robot_scoped(self):
        path = Path(__file__).parents[1] / 'control/camera_detect_node.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CameraDetectNode')
        for namespace in ('rosy_01', 'rosy_02'):
            class NamespacedNode(Node):
                def __init__(self, name):
                    super().__init__(name, namespace=namespace, parameter_overrides=[
                        Parameter('camera_frame', value=namespace + '/camera_link')])

            bindings = dict(vars(camera_module), Node=NamespacedNode,
                            ground_plane=lambda **kwargs: None, CameraPolicy=lambda **kwargs: None)
            exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), bindings)
            constructor = bindings['CameraDetectNode']
            constructor._start_cam = lambda self: None
            constructor.tick = lambda self: None
            rclpy.init()
            node = None
            try:
                node = constructor()
                topics = {p.topic_name for p in node.publishers} - {'/rosout', '/parameter_events'}
                # + camera/controls and camera/calibration/status; compressed stays off
                self.assertEqual(len(topics), 9, topics)
                self.assertNotIn('/' + namespace + '/camera/front/compressed', topics)
                self.assertTrue(all(t.startswith('/' + namespace + '/camera/') for t in topics), topics)
                recorded = []
                node.img_pub = type('Capture', (), {'publish': lambda self, msg: recorded.append(msg)})()
                frame = np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
                node._publish_front(frame)
                self.assertEqual(recorded[0].header.frame_id, namespace + '/camera_link')
                self.assertEqual(recorded[0].encoding, 'bgr8')
                self.assertEqual(bytes(recorded[0].data), frame.tobytes())
            finally:
                if node is not None:
                    node.destroy_node()
                rclpy.shutdown()

    def test_compressed_capture_stream_is_opt_in_and_shares_the_raw_stamp(self):
        path = Path(__file__).parents[1] / 'control/camera_detect_node.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CameraDetectNode')

        class CaptureNode(Node):
            def __init__(self, name):
                super().__init__(name, namespace='rosy_01', parameter_overrides=[
                    Parameter('publish_compressed', value=True)])

        bindings = dict(vars(camera_module), Node=CaptureNode,
                        ground_plane=lambda **kwargs: None, CameraPolicy=lambda **kwargs: None)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), bindings)
        constructor = bindings['CameraDetectNode']
        constructor._start_cam = lambda self: None
        constructor.tick = lambda self: None
        rclpy.init()
        node = None
        try:
            node = constructor()
            topics = {p.topic_name for p in node.publishers}
            self.assertIn('/rosy_01/camera/front/compressed', topics)
            qos = next(p.qos_profile for p in node.publishers
                       if p.topic_name == '/rosy_01/camera/front/compressed')
            self.assertEqual(qos.depth, 1)
            self.assertEqual(qos.reliability, ReliabilityPolicy.BEST_EFFORT)
            raw, jpeg = [], []
            node.img_pub = type('Raw', (), {'publish': lambda self, msg: raw.append(msg)})()
            node.jpeg_pub = type('Jpeg', (), {'publish': lambda self, msg: jpeg.append(msg)})()
            frame = np.zeros((8, 8, 3), dtype=np.uint8)
            node._publish_front(frame, 12.25)
            self.assertEqual(jpeg[0].format, 'jpeg')
            self.assertEqual(jpeg[0].header.stamp, raw[0].header.stamp)
            self.assertEqual(jpeg[0].header.frame_id, raw[0].header.frame_id)
            self.assertEqual(bytes(jpeg[0].data)[:2], bytes([0xFF, 0xD8]))
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
