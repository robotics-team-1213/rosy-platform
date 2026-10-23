"""Static direct-neighbor configuration and bounded control-unit HTTP transport."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx
import yaml

from fleet.server.control_unit_config import ControlUnitTopology, _identifier


@dataclass(frozen=True)
class ControlUnitPeer:
    url: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class ControlUnitConfig:
    unit_id: str
    topology: ControlUnitTopology
    peers: object = field(repr=False)


def load_control_unit(path):
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(65_537)
    if len(data) > 65_536:
        raise ValueError("CONTROL_UNIT_CONFIGURATION_TOO_LARGE")
    document = yaml.safe_load(data)
    if not isinstance(document, dict) or set(document) != {"unit_id", "manifest", "peers"}:
        raise ValueError("INVALID_CONTROL_UNIT_CONFIGURATION")
    topology = ControlUnitTopology.from_mapping(document["manifest"])
    unit = topology.unit(document["unit_id"])
    neighbors = {u.unit_id for u in topology.units.values() if u.parent == unit.unit_id}
    if unit.parent is not None:
        neighbors.add(unit.parent)
    if not isinstance(document["peers"], dict) or set(document["peers"]) != neighbors:
        raise ValueError("CONTROL_UNIT_NEIGHBOR_CONFIGURATION_MISMATCH")
    peers = {}
    for identity, entry in document["peers"].items():
        if not isinstance(entry, dict) or set(entry) != {"url", "token_file"}:
            raise ValueError("INVALID_CONTROL_UNIT_PEER")
        url = entry["url"]
        if not isinstance(url, str) or any(ord(c) < 33 or ord(c) == 127 for c in url):
            raise ValueError("INVALID_CONTROL_UNIT_PEER_URL")
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("INVALID_CONTROL_UNIT_PEER_URL")
        if not isinstance(entry["token_file"], str) or not entry["token_file"]:
            raise ValueError("CONTROL_UNIT_SERVICE_TOKEN_FILE_REQUIRED")
        token_path = path.parent / entry["token_file"]
        with token_path.open("rb") as stream:
            token_data = stream.read(1025)
        if len(token_data) > 1024:
            raise ValueError("INVALID_CONTROL_UNIT_SERVICE_TOKEN")
        token = token_data.decode("ascii").strip()
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("INVALID_CONTROL_UNIT_SERVICE_TOKEN")
        peers[identity] = ControlUnitPeer(url.rstrip("/"), token)
    if len({peer.url for peer in peers.values()}) != len(peers):
        raise ValueError("CONTROL_UNIT_PEER_ENDPOINT_COLLISION")
    return ControlUnitConfig(unit.unit_id, topology, MappingProxyType(peers))


class ControlUnitPeers:
    def __init__(self, config, http):
        self.config, self.http = config, http

    async def __call__(self, unit_id, method, path, body=None):
        if unit_id not in self.config.peers or method not in {"GET", "POST"}:
            raise ValueError("CONTROL_UNIT_PEER_OUTSIDE_SCOPE")
        if path == "inbox" and method == "POST":
            suffix = "/inbox"
        else:
            parts = path.split("/")
            if len(parts) != 2:
                raise ValueError("INVALID_CONTROL_UNIT_PEER_PATH")
            _identifier(parts[0])
            _identifier(parts[1], limit=128)
            suffix = "/delegations/" + path + ("/cancel" if method == "POST" else "")
        peer = self.config.peers[unit_id]
        async with self.http.stream(method, peer.url + "/api/fleet/control-unit" + suffix,
                                    headers={"Authorization": "Bearer " + peer.token},
                                    json=body, follow_redirects=False, timeout=3.0) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 131_072:
                    raise ValueError("CONTROL_UNIT_PEER_RESPONSE_TOO_LARGE")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("INVALID_CONTROL_UNIT_PEER_RESPONSE")
            return value
