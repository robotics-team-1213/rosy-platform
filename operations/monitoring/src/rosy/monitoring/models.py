"""Bounded monitoring graphs; source validity and collection validity are independent."""

from datetime import datetime
from typing import Annotated, Literal, Self

from core_common.protocol.connect_reason import REASONS
from pydantic import (AwareDatetime, BaseModel, ConfigDict, Field, StrictBool,
                      StringConstraints, field_validator, model_validator)


Name = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=96,
                                       pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
SiteId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64,
                                         pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
GraphId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256,
                                          pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
ReportSeconds = Annotated[float, Field(strict=True, ge=0, le=15, allow_inf_nan=False)]
REASON_CODES = frozenset(REASONS) | {
    "MONITORING_DNS", "MONITORING_CONNECT", "MONITORING_TLS", "MONITORING_AUTH",
    "MONITORING_HTTP", "MONITORING_PROTOCOL", "MONITORING_TIMEOUT", "MONITORING_SOURCE",
    "MONITORING_AUTH_CONFIG", "MONITORING_STALE", "MONITORING_CLOCK", "MONITORING_REPLAY",
}


class MonitoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def timestamps_are_explicit(cls, value, info):
        if info.field_name in {"sampled_at", "produced_at"} and value is not None:
            if not isinstance(value, (str, datetime)) or isinstance(value, str) and "T" not in value:
                raise ValueError("an explicit timezone-aware timestamp is required")
        return value


class Observation(MonitoringModel):
    site_id: SiteId
    origin_collector: Name
    origin_source: Name
    sample_id: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128,
                                               pattern=r"^[A-Za-z0-9_.:-]+$")] | None
    sampled_at: AwareDatetime | None
    age_s: Seconds | None
    valid_for_s: Literal[15, 900, 2100]
    remaining_s: Annotated[float, Field(strict=True, ge=0, le=2100, allow_inf_nan=False)]
    report_remaining_s: ReportSeconds
    freshness: Literal["fresh", "stale", "unknown"]
    reason_code: Annotated[str, Field(strict=True, max_length=96)] | None = None

    @field_validator("valid_for_s", mode="before")
    @classmethod
    def strict_source_lifetime(cls, value):
        if type(value) is not int:
            raise ValueError("source lifetime must be an integer")
        return value

    @field_validator("reason_code")
    @classmethod
    def reason_is_public(cls, value):
        if value is not None and value not in REASON_CODES:
            raise ValueError("unregistered monitoring reason")
        return value

    @model_validator(mode="after")
    def coherent_lifetimes(self) -> Self:
        known = (self.sample_id is not None, self.sampled_at is not None, self.age_s is not None)
        if self.freshness == "unknown":
            if any(known) or self.remaining_s or self.report_remaining_s:
                raise ValueError("unobserved information has no evidence or remaining lifetime")
        else:
            if not all(known):
                raise ValueError("observed information requires its original sample metadata")
            if self.remaining_s and self.age_s + self.remaining_s > self.valid_for_s + 1e-6:
                raise ValueError("source lifetime cannot be extended")
            fresh = self.remaining_s > 0 and self.report_remaining_s > 0
            if (self.freshness == "fresh") != fresh:
                raise ValueError("freshness must reflect both lifetimes")
        return self


class MonitoringNode(Observation):
    id: GraphId
    kind: Literal["collector", "robot", "host", "fleet", "service"]
    label: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
    reported_health: Literal["OK", "WARNING", "ERROR", "UNKNOWN"]

    @model_validator(mode="after")
    def coherent_node(self) -> Self:
        if not self.id.startswith(f"{self.site_id}:{self.kind}:"):
            raise ValueError("node identity must carry its site and kind")
        if not self.label.isprintable():
            raise ValueError("labels must be printable")
        if self.kind != "host" and self.valid_for_s != 15:
            raise ValueError("only existing host reports have a longer source lifetime")
        if self.freshness == "unknown" and self.reported_health != "UNKNOWN":
            raise ValueError("unobserved inventory cannot report health")
        return self


class MonitoringLink(Observation):
    id: GraphId
    source_id: GraphId
    target_id: GraphId
    kind: Literal["probe", "reported"]
    expected: StrictBool
    reachable: StrictBool | None
    failure_stage: Literal["none", "dns", "connect", "tls", "auth", "http", "protocol",
                           "timeout", "source", "unknown"]
    duration_ms: Seconds | None

    @model_validator(mode="after")
    def coherent_link(self) -> Self:
        if not self.id.startswith(f"{self.site_id}:{self.kind}:") or self.valid_for_s != 15:
            raise ValueError("link identity and lifetime must match its observation")
        if self.reachable is True and self.failure_stage != "none":
            raise ValueError("a successful probe cannot carry a failure stage")
        if self.freshness == "unknown" and (self.reachable is not None or self.duration_ms is not None):
            raise ValueError("unobserved links cannot report a probe result")
        return self


class MonitoringSnapshot(MonitoringModel):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    collector_id: Name
    generation: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{32}$")]
    sequence: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    produced_at: AwareDatetime
    remaining_s: ReportSeconds
    scope_sites: Annotated[tuple[SiteId, ...], Field(min_length=1, max_length=64)]
    nodes: Annotated[tuple[MonitoringNode, ...], Field(max_length=2048)] = ()
    links: Annotated[tuple[MonitoringLink, ...], Field(max_length=4096)] = ()

    @model_validator(mode="after")
    def closed_graph(self) -> Self:
        scopes = set(self.scope_sites)
        nodes = {node.id: node for node in self.nodes}
        ids = [node.id for node in self.nodes] + [link.id for link in self.links]
        if len(scopes) != len(self.scope_sites) or len(ids) != len(set(ids)):
            raise ValueError("duplicate scope or graph identity")
        for item in (*self.nodes, *self.links):
            if item.site_id not in scopes:
                raise ValueError("graph information lies outside the declared scope")
        for link in self.links:
            ends = (nodes.get(link.source_id), nodes.get(link.target_id))
            if any(end is None or end.site_id != link.site_id for end in ends):
                raise ValueError("links require existing endpoints in the same site")
        if len(self.model_dump_json().encode("utf-8")) > 1024 * 1024:
            raise ValueError("monitoring graph exceeds the response budget")
        return self
