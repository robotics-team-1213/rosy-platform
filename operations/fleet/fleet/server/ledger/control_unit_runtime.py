from dataclasses import dataclass, field
import asyncio
import json
import ssl
from pathlib import Path
from hashlib import sha256
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
    share_information_with_parent: bool = False
    accept_parent_stop: bool = False
    tls_context: ssl.SSLContext | None = field(default=None, repr=False)


def load_control_unit(path):
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(65_537)
    if len(data) > 65_536:
        raise ValueError("CONTROL_UNIT_CONFIGURATION_TOO_LARGE")
    document = yaml.safe_load(data)
    required = {"unit_id", "manifest", "peers"}
    optional = {"share_information_with_parent", "accept_parent_stop", "tls_ca_file"}
    if (not isinstance(document, dict) or not required <= set(document)
            or set(document) - required - optional):
        raise ValueError("INVALID_CONTROL_UNIT_CONFIGURATION")
    for flag in ("share_information_with_parent", "accept_parent_stop"):
        if type(document.get(flag, False)) is not bool:
            raise ValueError("INVALID_CONTROL_UNIT_OPT_IN")
    tls_context = None
    if "tls_ca_file" in document:
        ca_file = document["tls_ca_file"]
        if not isinstance(ca_file, str) or not ca_file.strip():
            raise ValueError("CONTROL_UNIT_TLS_CA_FILE_REQUIRED")
        tls_context = ssl.create_default_context(cafile=str(path.parent / ca_file))
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
        if (not isinstance(url, str) or "?" in url or "#" in url
                or any(ord(c) < 33 or ord(c) == 127 for c in url)):
            raise ValueError("INVALID_CONTROL_UNIT_PEER_URL")
        try:
            parsed = urlsplit(url)
            endpoint = httpx.URL(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None or parsed.port == 0
                    or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                raise ValueError("INVALID_CONTROL_UNIT_PEER_URL")
        except (ValueError, httpx.InvalidURL):
            raise ValueError("INVALID_CONTROL_UNIT_PEER_URL") from None
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
        peers[identity] = ControlUnitPeer(str(endpoint.copy_with(path="")).rstrip("/"), token)
    if len({peer.url for peer in peers.values()}) != len(peers):
        raise ValueError("CONTROL_UNIT_PEER_ENDPOINT_COLLISION")
    if len({peer.token for peer in peers.values()}) != len(peers):
        raise ValueError("CONTROL_UNIT_SERVICE_CREDENTIAL_NOT_ISOLATED")
    return ControlUnitConfig(unit.unit_id, topology, MappingProxyType(peers),
                             document.get("share_information_with_parent", False),
                             document.get("accept_parent_stop", False), tls_context)


class ControlUnitPeers:
    def __init__(self, config, http):
        self.config, self.http = config, http

    async def __call__(self, unit_id, method, path, body=None):
        if unit_id not in self.config.peers or method not in {"GET", "POST"}:
            raise ValueError("CONTROL_UNIT_PEER_OUTSIDE_SCOPE")
        limit = 131_072
        if (path == "overview" and method == "GET"
                or path == "stop-inbox" and method == "POST"
                or path.startswith("units/") and method == "GET"
                or path.startswith("stops/") and method == "GET"):
            self.config.topology.child(self.config.unit_id, unit_id)
            parts = path.split("/")
            if parts[0] == "units":
                if len(parts) not in {2, 3} or len(parts) == 3 and parts[2] != "map":
                    raise ValueError("INVALID_CONTROL_UNIT_PEER_PATH")
                target = _identifier(parts[1])
                if target != unit_id:
                    self.config.topology.next_hop(unit_id, target)
                if len(parts) == 3:
                    limit = 2_097_152
            elif parts[0] == "stops":
                if len(parts) != 3:
                    raise ValueError("INVALID_CONTROL_UNIT_PEER_PATH")
                origin = _identifier(parts[1])
                _identifier(parts[2], limit=128)
                if origin != self.config.unit_id:
                    self.config.topology.next_hop(origin, self.config.unit_id)
            suffix = "/" + path
        elif path == "inbox" and method == "POST":
            suffix = "/inbox"
        else:
            parts = path.split("/")
            if len(parts) != 2:
                raise ValueError("INVALID_CONTROL_UNIT_PEER_PATH")
            _identifier(parts[0])
            _identifier(parts[1], limit=128)
            suffix = "/delegations/" + path + ("/cancel" if method == "POST" else "")
        payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        if payload is not None and len(payload) > 131_072:
            raise ValueError("CONTROL_UNIT_PEER_REQUEST_TOO_LARGE")
        peer = self.config.peers[unit_id]
        async with asyncio.timeout(3.0):
            async with self.http.stream(method, peer.url + "/api/fleet/control-unit" + suffix,
                                        headers={"Authorization": "Bearer " + peer.token,
                                                 "Content-Type": "application/json", "Accept-Encoding": "identity"},
                                        content=payload, follow_redirects=False, timeout=3.0) as response:
                response.raise_for_status()
                if response.headers.get("Content-Encoding", "").strip().lower() not in {"", "identity"}:
                    raise ValueError("CONTROL_UNIT_PEER_ENCODING_NOT_ALLOWED")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    if len(data) + len(chunk) > limit:
                        raise ValueError("CONTROL_UNIT_PEER_RESPONSE_TOO_LARGE")
                    data.extend(chunk)
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError("INVALID_CONTROL_UNIT_PEER_RESPONSE")
                return value


def install_control_unit(app, path, *, tasks, console, principals, named_logins,
                         console_token, authorize, require_viewer, require_named_operator,
                         map_snapshot=None, configured_omx=None, stop_transport=None, stop_targets=()):
    from fleet.server.control_unit_observation_runtime import install_control_information
    from fleet.server.control_unit_routes import install_control_unit_routes
    from fleet.server.control_unit_service import ControlUnitService
    from fleet.server.control_unit_stop_runtime import install_control_stops, validate_control_stop_owners
    from fleet.server.control_unit_store import ControlUnitStore
    app.state.control_unit = app.state.control_unit_http = None
    app.state.control_unit_stops = app.state.control_unit_information = None
    if path is None:
        return
    if tasks is None:
        raise ValueError("CONTROL_UNIT_DURABLE_JOURNAL_REQUIRED")
    if not principals and not named_logins:
        raise ValueError("CONTROL_UNIT_NAMED_CREDENTIALS_REQUIRED")
    config = load_control_unit(path)
    peer_principals = {p.principal_id for p in principals.values() if p.role == "service"}
    if any("control-unit:" + unit not in peer_principals for unit in config.peers):
        raise ValueError("CONTROL_UNIT_NEIGHBOR_PRINCIPAL_REQUIRED")
    for peer in config.peers.values():
        local = sha256(peer.token.encode()).hexdigest() in principals
        if (peer.token == console_token or console.uses_rest_token(peer.token)
                or console.uses_agent_pairing_token(peer.token) or local):
            raise ValueError("CONTROL_UNIT_SERVICE_CREDENTIAL_NOT_ISOLATED")
    configured_omx = configured_omx or {}
    signal_ids = validate_control_stop_owners(config, console=console, configured_omx=configured_omx,
                                             signals=console._signals, stop_targets=stop_targets)
    store = ControlUnitStore(tasks.store.path, unit_id=config.unit_id)
    service = ControlUnitService(config.topology, store, tasks, console, peer=None)
    http = httpx.AsyncClient(verify=config.tls_context or True, trust_env=False,
                             follow_redirects=False, timeout=3.0)
    service.peer = ControlUnitPeers(config, http)
    app.state.control_unit, app.state.control_unit_http = service, http
    install_control_unit_routes(app, service, authorize=authorize, require_viewer=require_viewer,
                                require_named_operator=require_named_operator)
    install_control_stops(app, config, tasks=tasks, console=console, configured_omx=configured_omx,
                          stop_transport=stop_transport, signal_ids=signal_ids, authorize=authorize, stop_targets=stop_targets,
                          require_viewer=require_viewer, require_named_operator=require_named_operator)
    install_control_information(app, config, tasks=tasks, console=console,
                                 map_snapshot=map_snapshot or (lambda: None),
                                 authorize=authorize, require_viewer=require_viewer)
