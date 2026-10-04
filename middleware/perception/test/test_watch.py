#!/usr/bin/env python3
import unittest

from control.watch import (
    FOREIGN,
    PRODUCT_EXCLUSIVE,
    PRODUCT_REQUIRED,
    STANDALONE_ALLOWED,
    STANDALONE_EXCLUSIVE,
    STANDALONE_REQUIRED,
    inspect,
)


def healthy():
    nodes = list(STANDALONE_REQUIRED) + ['lcd_node', 'web_node']
    pubs = {
        '/cmd_vel': ['safety_node'],
        '/cmd_vel_raw': ['wander_node'],
        '/scan': ['sllidar_node'],
    }
    return nodes, pubs


class WatchContractTest(unittest.TestCase):
    """The guard tables must describe the OS graph, not the pinky_* era.

    D-2/D-38: CORE owns the final cmd_vel in the OS runtime; the legacy
    safety gate owns it only in control-standalone mode (D-149). Exactly
    one of them may publish — never both.
    """

    def test_required_uses_current_node_names(self):
        for name in ('bringup', 'sensor_adc', 'imu_bno055'):
            self.assertIn(name, STANDALONE_REQUIRED)
        self.assertFalse(
            any(n.startswith('pinky_') for n in STANDALONE_REQUIRED),
            f'pinky_* leftovers in STANDALONE_REQUIRED: {STANDALONE_REQUIRED}')

    def test_no_pinky_names_anywhere(self):
        for table, values in (
                ('FOREIGN', FOREIGN), ('STANDALONE_REQUIRED', STANDALONE_REQUIRED)):
            self.assertFalse(
                any(str(v).startswith('pinky_') for v in values),
                f'pinky_* leftovers in {table}')

    def test_product_and_standalone_tables_are_separate(self):
        banned = ('safety_node', 'wander_node', 'sllidar_node', 'camera_detect_node')
        self.assertEqual(PRODUCT_EXCLUSIVE['/cmd_vel'], frozenset({'core'}))
        self.assertEqual(PRODUCT_REQUIRED, ('core',))
        for name in banned:
            self.assertNotIn(name, PRODUCT_REQUIRED)
        self.assertEqual(STANDALONE_EXCLUSIVE['/cmd_vel'], frozenset({'safety_node'}))
        self.assertIsNot(PRODUCT_EXCLUSIVE, STANDALONE_EXCLUSIVE)
        with self.assertRaises(ValueError):
            inspect([], {}, mode='both')

    def test_cmd_vel_raw_allows_control_node(self):
        self.assertIn('control_node', STANDALONE_ALLOWED['/cmd_vel_raw'])

    def test_bridge_twins_stay_foreign(self):
        self.assertIn('parameter_bridge', FOREIGN)
        self.assertIn('image_bridge', FOREIGN)



class WatchTest(unittest.TestCase):
    def scoped(self, namespace):
        nodes, pubs = healthy()
        return ([namespace + '/' + name for name in nodes],
                {topic: [namespace + '/' + name for name in names] for topic, names in pubs.items()})

    def test_other_robot_nodes_do_not_create_local_duplicates(self):
        nodes, pubs = self.scoped('/rosy_01')
        other_nodes, _ = self.scoped('/rosy_02')
        report = inspect(nodes + other_nodes, pubs, namespace='/rosy_01')
        self.assertTrue(report.ok, report.line())

    def test_remote_same_name_cannot_satisfy_local_publisher(self):
        nodes, pubs = self.scoped('/rosy_01')
        pubs['/cmd_vel'] = ['/rosy_02/safety_node']
        report = inspect(nodes, pubs, namespace='/rosy_01')
        self.assertFalse(report.ok)
        self.assertTrue(any(i.kind == 'missing_pub' for i in report.issues))
        self.assertTrue(any(i.kind == 'foreign_namespace' for i in report.issues))

    def test_foreign_publisher_is_reported_even_when_local_owner_exists(self):
        nodes, pubs = self.scoped('/rosy_01')
        pubs['/scan'].append('/rosy_02/sllidar_node')
        report = inspect(nodes, pubs, namespace='/rosy_01')
        self.assertFalse(report.ok)
        self.assertTrue(any(i.kind == 'foreign_namespace' for i in report.issues))

    def test_namespace_prefix_collision_is_not_local(self):
        nodes, pubs = self.scoped('/rosy_010')
        report = inspect(nodes, pubs, namespace='/rosy_01')
        self.assertFalse(report.ok)
        self.assertTrue(any(i.kind == 'missing' for i in report.issues))

    def test_ok(self):
        r = inspect(*healthy())
        self.assertTrue(r.ok, r.line())
        self.assertEqual(r.line(), 'ok')

    def test_missing_safety(self):
        nodes, pubs = healthy()
        nodes.remove('safety_node')
        pubs['/cmd_vel'] = []
        r = inspect(nodes, pubs)
        kinds = {i.kind for i in r.issues}
        self.assertFalse(r.ok)
        self.assertIn('missing', kinds)
        self.assertIn('missing_pub', kinds)
        self.assertTrue(any('safety_node' in i.detail for i in r.issues))

    def test_duplicate_wander(self):
        nodes, pubs = healthy()
        nodes.append('wander_node')
        r = inspect(nodes, pubs)
        self.assertFalse(r.ok)
        self.assertTrue(any(i.kind == 'duplicate' and i.node == 'wander_node' for i in r.issues))

    def test_foreign_cmd_vel(self):
        nodes, pubs = healthy()
        pubs['/cmd_vel'] = ['safety_node', 'parameter_bridge']
        r = inspect(nodes, pubs)
        self.assertFalse(r.ok)
        hit = [i for i in r.issues if i.kind == 'foreign' and i.topic == '/cmd_vel']
        self.assertEqual(len(hit), 1)
        self.assertIn('parameter_bridge', hit[0].node)

    def test_foreign_scan_and_raw(self):
        nodes, pubs = healthy()
        pubs['/scan'] = ['sllidar_node', 'parameter_bridge']
        pubs['/cmd_vel_raw'] = ['wander_node', 'image_bridge']
        r = inspect(nodes, pubs)
        topics = {i.topic for i in r.issues if i.kind == 'foreign'}
        self.assertEqual(topics, {'/scan', '/cmd_vel_raw'})

    def test_cmd_vel_only_remote(self):
        nodes, pubs = healthy()
        nodes.remove('safety_node')
        pubs['/cmd_vel'] = ['parameter_bridge']
        r = inspect(nodes, pubs)
        self.assertFalse(r.ok)
        self.assertTrue(any(i.kind == 'missing_pub' for i in r.issues))
        self.assertTrue(any(i.kind == 'foreign' and i.topic == '/cmd_vel' for i in r.issues))

    def test_ignore_cli_and_watch(self):
        nodes, pubs = healthy()
        nodes += ['watch_node', '_ros2cli_daemon_13_abc']
        r = inspect(nodes, pubs)
        self.assertTrue(r.ok, r.line())

    def test_foreign_set(self):
        self.assertIn('parameter_bridge', FOREIGN)
        self.assertIn('image_bridge', FOREIGN)
        self.assertNotIn('pinky_control', FOREIGN)

    def test_safety_zero_on_raw_is_ok(self):
        nodes, pubs = healthy()
        pubs['/cmd_vel_raw'] = ['wander_node', 'safety_node']
        r = inspect(nodes, pubs)
        self.assertTrue(r.ok, r.line())

    def test_web_teleop_on_raw_is_ok(self):
        nodes, pubs = healthy()
        pubs['/cmd_vel_raw'] = ['wander_node', 'web_node']
        r = inspect(nodes, pubs)
        self.assertTrue(r.ok, r.line())

    def test_control_node_on_raw_is_ok(self):
        nodes, pubs = healthy()
        pubs['/cmd_vel_raw'] = ['wander_node', 'control_node']
        r = inspect(nodes, pubs)
        self.assertTrue(r.ok, r.line())

    def test_core_alone_publishing_cmd_vel_is_ok(self):
        # Product runtime: CORE is the only final publisher (D-2/D-38, D-183).
        r = inspect(['core'], {'/cmd_vel': ['core']}, mode='product')
        self.assertTrue(r.ok, r.line())

    def test_core_and_safety_both_publishing_cmd_vel_is_interrupt(self):
        # D-38: the legacy final publisher must never run beside CORE.
        nodes, pubs = healthy()
        pubs['/cmd_vel'] = ['core', 'safety_node']
        standalone = inspect(nodes, pubs, mode='standalone')
        self.assertFalse(standalone.ok)
        self.assertTrue(any('core' in i.detail for i in standalone.issues))
        product = inspect(['core'], {'/cmd_vel': ['core', 'safety_node']}, mode='product')
        self.assertFalse(product.ok)
        self.assertTrue(any('safety_node' in i.detail for i in product.issues))


if __name__ == '__main__':
    unittest.main()
