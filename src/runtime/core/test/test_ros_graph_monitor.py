from types import SimpleNamespace

import pytest

from core.system.ros_graph import RosGraphMonitor, parse_domain_id


class FakeGraphNode:
    def __init__(self, nodes, topics, publishers=None, subscriptions=None):
        self._nodes = nodes
        self._topics = topics
        self._publishers = publishers or {}
        self._subscriptions = subscriptions or {}

    def get_node_names_and_namespaces(self):
        return list(self._nodes)

    def get_topic_names_and_types(self):
        return list(self._topics)

    def get_publishers_info_by_topic(self, topic):
        return list(self._publishers.get(topic, []))

    def get_subscriptions_info_by_topic(self, topic):
        return list(self._subscriptions.get(topic, []))


def endpoint(name, namespace):
    return SimpleNamespace(node_name=name, node_namespace=namespace)


def test_parse_domain_id_accepts_linux_safe_range_only():
    assert parse_domain_id('0') == 0
    assert parse_domain_id('101') == 101

    for value in ('', 'abc', '-1', '102'):
        with pytest.raises(ValueError):
            parse_domain_id(value)


def test_snapshot_reports_duplicate_and_foreign_nodes_with_topic_edges():
    node = FakeGraphNode(
        nodes=[
            ('core', '/rosy_01'),
            ('bringup', '/rosy_01'),
            ('bringup', '/rosy_01'),
            ('camera', '/visitor'),
        ],
        topics=[('/cmd_vel', ['geometry_msgs/msg/Twist'])],
        publishers={'/cmd_vel': [endpoint('core', '/rosy_01')]},
        subscriptions={'/cmd_vel': [endpoint('bringup', '/rosy_01')]},
    )
    monitor = RosGraphMonitor(
        node,
        domain_id='42',
        namespace='/rosy_01/',
        dds_uri='file:///etc/rosy/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="lo"/>',
        monotonic=lambda: 10.0,
    )

    snapshot = monitor.snapshot()

    assert snapshot['domain_id'] == 42
    assert snapshot['namespace'] == '/rosy_01'
    assert snapshot['isolation']['mode'] == 'localhost_only'
    assert snapshot['node_count'] == 4
    assert snapshot['unique_node_count'] == 3
    assert snapshot['topic_count'] == 1
    assert snapshot['nodes'][1]['instances'] == 2
    assert snapshot['edges'] == [
        {'source': '/rosy_01/core', 'target': '/cmd_vel', 'kind': 'publishes'},
        {'source': '/cmd_vel', 'target': '/rosy_01/bringup', 'kind': 'subscribes'},
    ]
    assert {risk['code'] for risk in snapshot['risks']} == {
        'DUPLICATE_NODE_NAME',
        'FOREIGN_NAMESPACE',
    }
    assert snapshot['status'] == 'WARNING'


def test_snapshot_reports_cyclone_rmw():
    monitor = RosGraphMonitor(
        FakeGraphNode([], []),
        domain_id='42',
        namespace='rosy_01',
        dds_uri='file:///etc/rosy/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="lo"/>',
        environment={'RMW_IMPLEMENTATION': 'rmw_cyclonedds_cpp'},
    )
    snapshot = monitor.snapshot()
    assert snapshot['rmw'] == 'rmw_cyclonedds_cpp'
    assert 'RMW_NOT_CYCLONE' not in {risk['code'] for risk in snapshot['risks']}


def test_foreign_rmw_is_an_explicit_error():
    monitor = RosGraphMonitor(
        FakeGraphNode([], []),
        domain_id='42',
        namespace='rosy_01',
        dds_uri='file:///etc/rosy/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="lo"/>',
        environment={'RMW_IMPLEMENTATION': 'rmw_fastrtps_cpp'},
    )
    snapshot = monitor.snapshot()
    assert snapshot['rmw'] == 'rmw_fastrtps_cpp'
    assert snapshot['status'] == 'ERROR'
    assert 'RMW_NOT_CYCLONE' in {risk['code'] for risk in snapshot['risks']}


def test_invalid_domain_and_non_loopback_dds_are_explicit_errors():
    monitor = RosGraphMonitor(
        FakeGraphNode([], []),
        domain_id='240',
        namespace='rosy_01',
        dds_uri='file:///tmp/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="wlan0"/>',
    )

    snapshot = monitor.snapshot()

    assert snapshot['domain_id'] is None
    assert snapshot['isolation']['mode'] == 'network_visible'
    assert snapshot['status'] == 'ERROR'
    assert {risk['code'] for risk in snapshot['risks']} == {
        'DOMAIN_ID_INVALID',
        'DDS_NOT_LOOPBACK',
    }


def test_commented_loopback_cannot_hide_active_autodetected_interface():
    monitor = RosGraphMonitor(
        FakeGraphNode([], []),
        domain_id='42',
        namespace='rosy_01',
        dds_uri='file:///tmp/cyclonedds.xml',
        dds_config_reader=lambda _: (
            '<CycloneDDS><Domain><General><Interfaces>'
            '<!-- <NetworkInterface name="lo"/> -->'
            '<NetworkInterface autodetermine="true"/>'
            '</Interfaces></General></Domain></CycloneDDS>'
        ),
    )

    snapshot = monitor.snapshot()

    assert snapshot['isolation']['mode'] == 'network_visible'
    assert snapshot['status'] == 'ERROR'
    assert {risk['code'] for risk in snapshot['risks']} == {'DDS_NOT_LOOPBACK'}


def test_mixed_loopback_and_network_interface_is_network_visible():
    monitor = RosGraphMonitor(
        FakeGraphNode([], []),
        domain_id='42',
        namespace='rosy_01',
        dds_uri='file:///tmp/cyclonedds.xml',
        dds_config_reader=lambda _: (
            '<CycloneDDS><Domain><General><Interfaces>'
            '<NetworkInterface name="lo"/><NetworkInterface name="wlan0"/>'
            '</Interfaces></General></Domain></CycloneDDS>'
        ),
    )

    snapshot = monitor.snapshot()

    assert snapshot['isolation']['mode'] == 'network_visible'
    assert snapshot['isolation']['interface'] == 'lo, wlan0'


def test_root_namespace_contains_all_nodes_without_foreign_warning():
    monitor = RosGraphMonitor(
        FakeGraphNode([('core', '/')], []),
        domain_id='42',
        namespace='/',
        dds_uri='file:///tmp/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="lo"/>',
    )

    snapshot = monitor.snapshot()

    assert snapshot['status'] == 'OK'
    assert snapshot['nodes'][0]['foreign'] is False
    assert snapshot['risks'] == []


def test_snapshot_is_bounded_and_cached():
    node = FakeGraphNode(
        nodes=[(f'node_{index}', '/rosy_01') for index in range(80)],
        topics=[(f'/topic_{index}', ['std_msgs/msg/String']) for index in range(120)],
    )
    ticks = iter((10.0, 10.5, 11.1))
    monitor = RosGraphMonitor(
        node,
        domain_id='42',
        namespace='rosy_01',
        dds_uri='file:///etc/rosy/cyclonedds.xml',
        dds_config_reader=lambda _: '<NetworkInterface name="lo"/>',
        monotonic=lambda: next(ticks),
    )

    first = monitor.snapshot()
    second = monitor.snapshot()
    third = monitor.snapshot()

    assert first is second
    assert third is not second
    assert len(first['nodes']) == 64
    assert len(first['topics']) == 96
    assert first['truncated'] == {'nodes': True, 'topics': True, 'edges': False}


def test_graph_collection_failure_degrades_without_raising():
    class BrokenNode:
        def get_node_names_and_namespaces(self):
            raise RuntimeError('graph unavailable')

    snapshot = RosGraphMonitor(BrokenNode(), domain_id='42', namespace='rosy_01').snapshot()

    assert snapshot['status'] == 'UNAVAILABLE'
    assert snapshot['node_count'] is None
    assert snapshot['risks'][0]['code'] == 'GRAPH_UNAVAILABLE'
