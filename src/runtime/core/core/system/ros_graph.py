"""Bounded, read-only ROS 2 graph and DDS isolation telemetry."""

from __future__ import annotations

import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping, Optional
from xml.etree import ElementTree

from core_common.rmw import REQUIRED_RMW


MAX_NODES = 64
MAX_TOPICS = 96
MAX_EDGES = 256
MAX_LINUX_DOMAIN_ID = 101


def parse_domain_id(value: Any) -> int:
    """Return a Linux-safe ROS domain ID or raise a clear validation error."""
    if isinstance(value, bool):
        raise ValueError('ROS_DOMAIN_ID must be an integer from 0 to 101')
    text = str(value).strip()
    if not text or not re.fullmatch(r'[0-9]+', text):
        raise ValueError('ROS_DOMAIN_ID must be an integer from 0 to 101')
    domain_id = int(text)
    if not 0 <= domain_id <= MAX_LINUX_DOMAIN_ID:
        raise ValueError('ROS_DOMAIN_ID must be in the Linux-safe range 0 to 101')
    return domain_id


def normalize_namespace(value: Any) -> str:
    text = str(value or '').strip().strip('/')
    return f'/{text}' if text else '/'


def fully_qualified_node_name(name: Any, namespace: Any) -> str:
    clean_name = str(name).strip().strip('/')
    clean_namespace = normalize_namespace(namespace)
    if clean_namespace == '/':
        return f'/{clean_name}'
    return f'{clean_namespace}/{clean_name}'


def _default_dds_config_reader(uri: str) -> str:
    if not uri.startswith('file://'):
        raise ValueError('only file:// CycloneDDS profiles can be inspected')
    return Path(uri.removeprefix('file://')).read_text(encoding='utf-8')


def _dds_isolation(uri: str, reader: Callable[[str], str]) -> dict[str, Any]:
    try:
        content = reader(uri)
        root = ElementTree.fromstring(content)
    except (OSError, ValueError, ElementTree.ParseError):
        return {'mode': 'unknown', 'interface': None, 'uri': uri or None}

    interface_elements = [
        element for element in root.iter()
        if element.tag.rsplit('}', 1)[-1] == 'NetworkInterface'
    ]
    selectors: list[str] = []
    all_loopback = bool(interface_elements)
    for element in interface_elements:
        name = element.attrib.get('name', '').strip()
        address = element.attrib.get('address', '').strip()
        if name:
            selectors.append(name)
            all_loopback = all_loopback and name == 'lo'
        elif address:
            selectors.append(address)
            all_loopback = all_loopback and address in {'127.0.0.1', '::1', 'localhost'}
        else:
            selectors.append('auto')
            all_loopback = False

    if all_loopback:
        return {'mode': 'localhost_only', 'interface': 'lo', 'uri': uri or None}
    if not interface_elements:
        return {'mode': 'unknown', 'interface': None, 'uri': uri or None}
    return {
        'mode': 'network_visible',
        'interface': ', '.join(selectors),
        'uri': uri or None,
    }


class RosGraphMonitor:
    """Read and cache a small ROS graph snapshot suitable for a Pi dashboard."""

    def __init__(
        self,
        node: Any,
        *,
        domain_id: Any = None,
        namespace: Any = None,
        dds_uri: Optional[str] = None,
        dds_config_reader: Optional[Callable[[str], str]] = None,
        monotonic: Callable[[], float] = time.monotonic,
        cache_seconds: float = 1.0,
        environment: Optional[Mapping[str, str]] = None,
    ) -> None:
        env = environment or os.environ
        self._node = node
        self._domain_id_raw = env.get('ROS_DOMAIN_ID', '') if domain_id is None else domain_id
        self._namespace = normalize_namespace(
            env.get('ROSY_NAMESPACE', '') if namespace is None else namespace
        )
        self._dds_uri = str(env.get('CYCLONEDDS_URI', '') if dds_uri is None else dds_uri)
        self._rmw = str(env.get('RMW_IMPLEMENTATION') or '').strip()
        self._dds_config_reader = dds_config_reader or _default_dds_config_reader
        self._monotonic = monotonic
        self._cache_seconds = max(0.0, float(cache_seconds))
        self._cached: Optional[dict[str, Any]] = None
        self._cached_at: Optional[float] = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        now = self._monotonic()
        with self._lock:
            if (
                self._cached is not None
                and self._cached_at is not None
                and now - self._cached_at < self._cache_seconds
            ):
                return self._cached
            snapshot = self._collect()
            self._cached = snapshot
            self._cached_at = now
            return snapshot

    def _collect(self) -> dict[str, Any]:
        try:
            raw_nodes = list(self._node.get_node_names_and_namespaces())
            raw_topics = list(self._node.get_topic_names_and_types())
        except Exception as error:
            return {
                'status': 'UNAVAILABLE',
                'domain_id': None,
                'namespace': self._namespace,
                'rmw': self._rmw or None,
                'isolation': {'mode': 'unknown', 'interface': None, 'uri': self._dds_uri or None},
                'node_count': None,
                'unique_node_count': None,
                'topic_count': None,
                'nodes': [],
                'topics': [],
                'edges': [],
                'risks': [{'code': 'GRAPH_UNAVAILABLE', 'message': str(error)}],
                'truncated': {'nodes': False, 'topics': False, 'edges': False},
            }

        risks: list[dict[str, str]] = []
        try:
            domain_id: Optional[int] = parse_domain_id(self._domain_id_raw)
        except ValueError as error:
            domain_id = None
            risks.append({'code': 'DOMAIN_ID_INVALID', 'message': str(error)})

        isolation = _dds_isolation(self._dds_uri, self._dds_config_reader)
        if self._rmw and self._rmw != REQUIRED_RMW:
            risks.append({
                'code': 'RMW_NOT_CYCLONE',
                'message': f'RMW_IMPLEMENTATION={self._rmw}; Rosy requires {REQUIRED_RMW}',
            })
        if isolation['mode'] == 'network_visible':
            risks.append({
                'code': 'DDS_NOT_LOOPBACK',
                'message': f"DDS is visible on {isolation['interface']}",
            })
        elif isolation['mode'] == 'unknown':
            risks.append({
                'code': 'DDS_CONFIG_UNAVAILABLE',
                'message': 'CycloneDDS interface isolation could not be verified',
            })

        node_instances: dict[str, int] = {}
        node_order: list[str] = []
        for name, namespace in raw_nodes:
            full_name = fully_qualified_node_name(name, namespace)
            if full_name not in node_instances:
                node_order.append(full_name)
                node_instances[full_name] = 0
            node_instances[full_name] += 1

        duplicate_names = [name for name in node_order if node_instances[name] > 1]
        if duplicate_names:
            risks.append({
                'code': 'DUPLICATE_NODE_NAME',
                'message': 'Duplicate node names: ' + ', '.join(duplicate_names[:8]),
            })

        if self._namespace == '/':
            foreign_nodes = []
        else:
            foreign_nodes = [
                name for name in node_order
                if not (
                    name == self._namespace
                    or name.startswith(f'{self._namespace}/')
                )
            ]
        if foreign_nodes:
            risks.append({
                'code': 'FOREIGN_NAMESPACE',
                'message': 'Nodes outside expected namespace: ' + ', '.join(foreign_nodes[:8]),
            })

        visible_node_names = node_order[:MAX_NODES]
        nodes = [
            {
                'name': name,
                'instances': node_instances[name],
                'foreign': name in foreign_nodes,
            }
            for name in visible_node_names
        ]

        topics: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        edge_truncated = False
        for topic_name, topic_types in raw_topics[:MAX_TOPICS]:
            publishers = list(self._node.get_publishers_info_by_topic(topic_name))
            subscriptions = list(self._node.get_subscriptions_info_by_topic(topic_name))
            topics.append({
                'name': topic_name,
                'types': list(topic_types),
                'publishers': len(publishers),
                'subscribers': len(subscriptions),
            })
            for endpoint in publishers:
                if len(edges) >= MAX_EDGES:
                    edge_truncated = True
                    break
                edges.append({
                    'source': fully_qualified_node_name(
                        endpoint.node_name, endpoint.node_namespace
                    ),
                    'target': topic_name,
                    'kind': 'publishes',
                })
            for endpoint in subscriptions:
                if len(edges) >= MAX_EDGES:
                    edge_truncated = True
                    break
                edges.append({
                    'source': topic_name,
                    'target': fully_qualified_node_name(
                        endpoint.node_name, endpoint.node_namespace
                    ),
                    'kind': 'subscribes',
                })

        error_codes = {'DOMAIN_ID_INVALID', 'DDS_NOT_LOOPBACK', 'RMW_NOT_CYCLONE'}
        status = 'ERROR' if any(risk['code'] in error_codes for risk in risks) else (
            'WARNING' if risks else 'OK'
        )
        return {
            'status': status,
            'domain_id': domain_id,
            'namespace': self._namespace,
            'rmw': self._rmw or None,
            'isolation': isolation,
            'node_count': len(raw_nodes),
            'unique_node_count': len(node_order),
            'topic_count': len(raw_topics),
            'nodes': nodes,
            'topics': topics,
            'edges': edges,
            'risks': risks,
            'truncated': {
                'nodes': len(node_order) > MAX_NODES,
                'topics': len(raw_topics) > MAX_TOPICS,
                'edges': edge_truncated,
            },
        }
