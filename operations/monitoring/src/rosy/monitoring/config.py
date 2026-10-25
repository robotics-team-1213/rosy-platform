"""Registered read targets and separate reader/upstream credentials; no repair configuration."""

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal, Mapping, Self
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator, model_validator
import yaml

from .models import MonitoringModel, Name, SiteId


EnvName = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]


class ReaderConfig(MonitoringModel):
    principal_id: Name
    token_env: EnvName
    sites: Annotated[tuple[SiteId, ...], Field(min_length=1, max_length=64)]


class SourceConfig(MonitoringModel):
    id: Name
    site_id: SiteId
    kind: Literal["core", "fleet", "host_guard", "host_state", "http", "peer"]
    label: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)] | None = None
    url: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)] | None = None
    path: Path | None = None
    selector: Name | None = None
    token_env: EnvName | None = None
    peer_sites: Annotated[tuple[SiteId, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def read_target(self) -> Self:
        file_source = self.kind in {"host_guard", "host_state"}
        if self.label is not None and not self.label.isprintable():
            raise ValueError("labels must be printable")
        if file_source:
            if self.path is None or not self.path.is_absolute() or self.url or self.token_env:
                raise ValueError("host sources require an absolute local file path")
            if self.kind == "host_guard" and not self.selector:
                raise ValueError("host guard sources require a registered status selector")
        else:
            if self.url is None or self.path is not None or self.selector is not None:
                raise ValueError("HTTP sources require a registered URL")
            try:
                target = urlsplit(self.url)
                port = target.port
                try:
                    loopback = ip_address(target.hostname or "").is_loopback
                except ValueError:
                    loopback = False
                valid = (target.scheme == "https" or target.scheme == "http" and loopback)
                valid = (valid and bool(target.hostname) and target.username is None and target.password is None
                         and not target.query and not target.fragment and "?" not in self.url
                         and "#" not in self.url and self.url.isprintable()
                         and not any(c.isspace() for c in self.url)
                         and (port is None or 1 <= port <= 65535))
                if self.kind != "http" and target.path not in {"", "/"}:
                    valid = False
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("read targets require HTTPS or literal loopback HTTP without credentials")
        if (self.kind == "peer") != bool(self.peer_sites) or len(set(self.peer_sites)) != len(self.peer_sites):
            raise ValueError("only peers declare a nonempty unique scope")
        return self


class MonitoringConfig(MonitoringModel):
    collector_id: Name
    site_id: SiteId
    readers: Annotated[tuple[ReaderConfig, ...], Field(min_length=1, max_length=128)]
    sources: Annotated[tuple[SourceConfig, ...], Field(max_length=128)] = ()
    ca_bundle: Path | None = None

    @field_validator("ca_bundle")
    @classmethod
    def absolute_ca(cls, value):
        if value is not None and not value.is_absolute():
            raise ValueError("CA bundle must be an absolute path")
        return value

    @model_validator(mode="after")
    def unique_owners(self) -> Self:
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source identity")
        if len({r.principal_id for r in self.readers}) != len(self.readers):
            raise ValueError("duplicate reader identity")
        sites = {self.site_id} | {s.site_id for s in self.sources if s.kind != "peer"}
        for source in self.sources:
            if source.kind == "peer":
                incoming = set(source.peer_sites)
                if source.id == self.collector_id or sites & incoming:
                    raise ValueError("a site must have exactly one collector owner")
                sites.update(incoming)
        if len(sites) > 64:
            raise ValueError("too many site scopes")
        for reader in self.readers:
            if len(set(reader.sites)) != len(reader.sites) or not set(reader.sites) <= sites:
                raise ValueError("reader scope must be unique and registered")
        return self


class _ConfigLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("configuration aliases are unsupported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("configuration keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_config(path: Path) -> MonitoringConfig:
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("configuration exceeds its size budget")
        return MonitoringConfig.model_validate(yaml.load(data.decode("utf-8"), Loader=_ConfigLoader))
    except (OSError, ValueError, yaml.YAMLError):
        raise ValueError("invalid monitoring configuration") from None


@dataclass(frozen=True)
class ReadPrincipal:
    principal_id: str
    sites: frozenset[str]


@dataclass(frozen=True, repr=False)
class MonitoringCredentials:
    _readers: tuple[tuple[bytes, ReadPrincipal], ...] = field(repr=False)
    _sources: Mapping[str, str | None] = field(repr=False)

    def authorize(self, token: str) -> ReadPrincipal | None:
        if not _valid_secret(token):
            return None
        digest = sha256(token.encode("ascii")).digest()
        for expected, principal in self._readers:
            if compare_digest(expected, digest):
                return principal
        return None

    def source_token(self, source_id: str) -> str | None:
        try:
            return self._sources[source_id]
        except KeyError:
            raise ValueError("upstream credential unavailable") from None

    def __repr__(self) -> str:
        return "MonitoringCredentials(<redacted>)"


def _valid_secret(value) -> bool:
    return isinstance(value, str) and 32 <= len(value) <= 4096 and all(33 <= ord(c) <= 126 for c in value)


def load_credentials(config: MonitoringConfig, environ: Mapping[str, str]) -> MonitoringCredentials:
    readers, seen, sources = [], set(), {}
    for reader in config.readers:
        token = environ.get(reader.token_env)
        if not _valid_secret(token):
            raise ValueError("reader credential unavailable")
        digest = sha256(token.encode("ascii")).digest()
        if digest in seen:
            raise ValueError("reader credentials must be distinct")
        seen.add(digest)
        readers.append((digest, ReadPrincipal(reader.principal_id, frozenset(reader.sites))))
    for source in config.sources:
        if source.token_env is None:
            sources[source.id] = None
            continue
        token = environ.get(source.token_env)
        if not _valid_secret(token):
            continue
        if sha256(token.encode("ascii")).digest() in seen:
            raise ValueError("reader and upstream credentials must be separate")
        sources[source.id] = token
    return MonitoringCredentials(tuple(readers), sources)
