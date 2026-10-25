"""Monotonic evidence deadlines and bounded, scope-checked peer composition."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import time
from uuid import uuid4

from .config import MonitoringConfig
from .models import MonitoringLink, MonitoringNode, MonitoringSnapshot
from .store import StoreUnavailable


MAX_REMEMBERED = 8192


class ObservationRejected(ValueError):
    def __init__(self, reason_code="MONITORING_PROTOCOL"):
        self.reason_code = reason_code
        super().__init__("monitoring observation rejected")


@dataclass(frozen=True)
class _Record:
    item: MonitoringNode | MonitoringLink
    at: float
    age: float | None
    source_until: float
    report_until: float

    def value(self, now):
        if self.age is None:
            return self.item
        source = max(0.0, self.source_until - now)
        report = max(0.0, self.report_until - now)
        return self.item.model_copy(update={
            "age_s": self.age + now - self.at, "remaining_s": source,
            "report_remaining_s": report, "freshness": "fresh" if source and report else "stale",
        })


def _fact(item):
    return item.model_dump(exclude={"age_s", "remaining_s", "report_remaining_s", "freshness",
                                    "label", "expected", "last_success_at"})


class ObservationCache:
    def __init__(self, config: MonitoringConfig, *, monotonic=time.monotonic,
                 utcnow=lambda: datetime.now(timezone.utc), store=None):
        self.config = config
        self.store = store
        self._monotonic, self._utcnow = monotonic, utcnow
        self._last_now = -math.inf
        self._sources = {source.id: source for source in config.sources}
        self.scope_sites = frozenset({config.site_id}
                                    | {s.site_id for s in config.sources if s.kind != "peer"}
                                    | {site for s in config.sources for site in s.peer_sites})
        self.generation, self._sequence = uuid4().hex, 0
        self._groups = {}
        # shortcut: reject new identities at 8192; add verified expired-anchor pruning for larger inventory churn.
        self._latest = {}
        self._peers = {}
        self._retired = {source.id: deque(maxlen=64) for source in config.sources if source.kind == "peer"}
        now = self._now()
        for source in config.sources:
            peer = source.kind == "peer"
            scopes = source.peer_sites if peer else (source.site_id,)
            kind = {"core": "robot", "fleet": "fleet", "http": "service", "peer": "collector"}.get(
                source.kind, "host")
            rows = {}
            for site in scopes:
                item = MonitoringNode(
                    id=f"{site}:{kind}:{source.id}", site_id=site, kind=kind,
                    label=source.label or source.id,
                    origin_collector=source.id if peer else config.collector_id, origin_source=source.id,
                    sample_id=None, sampled_at=None, age_s=None,
                    valid_for_s=900 if source.kind == "host_guard" else 2100 if source.kind == "host_state" else 15,
                    remaining_s=0.0, report_remaining_s=0.0, freshness="unknown", reported_health="UNKNOWN",
                )
                rows[item.id] = _Record(item, now, None, now, now)
            self._groups[("peer" if peer else "local", source.id)] = rows
        if store is not None:
            self._restore(now, self._wall())

    def _restore(self, now, wall):
        saved = self.store.load()
        groups, anchors = {}, {}
        try:
            for table in ('visible', 'anchors'):
                for key, item, captured in saved[table]:
                    elapsed = (wall - captured).total_seconds()
                    if elapsed < 0:
                        raise StoreUnavailable()
                    source = self._sources.get(key[1])
                    if source is None:
                        continue
                    scopes = source.peer_sites if key[0] == 'peer' else (source.site_id,)
                    if (item.site_id not in scopes or key[0] == 'peer' and source.kind != 'peer'
                            or key[0] == 'local' and item.origin_collector != self.config.collector_id):
                        raise StoreUnavailable()
                    age = None if item.age_s is None else item.age_s + elapsed + 2.0
                    record = _Record(item, now, age,
                                     now + max(0.0, item.remaining_s - elapsed - 2.0), now)
                    if table == 'visible':
                        groups.setdefault(key, {})[item.id] = record
                    else:
                        anchors[(key, item.id)] = record
            peers, retired = {}, dict(self._retired)
            for source, cursor in saved['peers'].items():
                if source not in self._retired:
                    continue
                generation, sequence, history = cursor
                if (not isinstance(generation, str) or len(generation) != 32
                        or any(c not in '0123456789abcdef' for c in generation)
                        or type(sequence) is not int or not 0 <= sequence <= 2**63 - 1
                        or not isinstance(history, list) or len(history) > 64
                        or any(not isinstance(g, str) or len(g) != 32
                               or any(c not in '0123456789abcdef' for c in g) for g in history)):
                    raise StoreUnavailable()
                peers[source] = (generation, sequence)
                retired[source] = deque(history, maxlen=64)
            proposed = self._groups | groups
            self._compose(proposed, self.scope_sites, now, wall, 0)
        except (ValueError, TypeError, KeyError):
            raise StoreUnavailable() from None
        self._groups, self._latest, self._peers, self._retired = proposed, anchors, peers, retired

    def _now(self):
        now = self._monotonic()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self._last_now:
            raise ObservationRejected("MONITORING_CLOCK")
        self._last_now = now
        return now

    def _wall(self):
        value = self._utcnow()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ObservationRejected("MONITORING_CLOCK")
        return value.astimezone(timezone.utc)

    def _source(self, source_id):
        if source_id not in self._sources:
            raise ObservationRejected()
        return self._sources[source_id]

    def _record(self, item, old, now, wall, budget, envelope, *, peer):
        if item.age_s is None:
            return _Record(item, now, None, now, now)
        if old is not None and old.item.sampled_at is not None and item.sampled_at < old.item.sampled_at:
            raise ObservationRejected("MONITORING_REPLAY")
        if isinstance(item, MonitoringLink):
            successes = [value for value in (item.last_success_at,
                         old.item.last_success_at if old is not None else None,
                         item.sampled_at if item.reachable is True else None) if value is not None]
            if successes:
                item = item.model_copy(update={"last_success_at": max(successes)})
        wall_age = (wall - item.sampled_at).total_seconds()
        if wall_age < -1:
            raise ObservationRejected("MONITORING_CLOCK")
        age = max(item.age_s + budget, max(0.0, wall_age - (1.0 if peer else 0.0)))
        source_until = now + max(0.0, min(item.remaining_s - budget, item.valid_for_s - age))
        report_until = now + max(0.0, min(item.report_remaining_s, envelope) - budget)
        if (old is not None and item.sample_id is not None and item.sample_id == old.item.sample_id
                and item.origin_collector == old.item.origin_collector
                and item.origin_source == old.item.origin_source):
            if item.sampled_at != old.item.sampled_at:
                raise ObservationRejected()
        if old is not None and item.sampled_at == old.item.sampled_at:
            current, previous = _fact(item), _fact(old.item)
            current.pop("sample_id")
            previous.pop("sample_id")
            if current != previous:
                raise ObservationRejected()
            source_until = min(source_until, old.source_until)
            if old.age is not None:
                age = max(age, old.age + now - old.at)
            source_until = min(source_until, now + max(0.0, item.valid_for_s - age))
        return _Record(item, now, age, source_until, report_until)

    def _compose(self, groups, sites, now, wall, sequence):
        nodes, links, used = [], [], set()
        for group in groups.values():
            for record in group.values():
                item = record.value(now)
                if item.site_id not in sites:
                    continue
                if item.id in used:
                    raise ObservationRejected()
                used.add(item.id)
                (nodes if isinstance(item, MonitoringNode) else links).append(item)
        for site in sorted(sites):
            own_id = f"{site}:collector:{self.config.collector_id}"
            if own_id in used:
                raise ObservationRejected()
            nodes.append(MonitoringNode(
                id=own_id, kind="collector", label="ROSY Monitoring", site_id=site,
                origin_collector=self.config.collector_id, origin_source="collector",
                sample_id=f"{self.generation}:{sequence}", sampled_at=wall, age_s=0.0,
                valid_for_s=15, remaining_s=15.0, report_remaining_s=15.0,
                freshness="fresh", reported_health="OK",
            ))
        return MonitoringSnapshot(schema_version=1, collector_id=self.config.collector_id,
                                  generation=self.generation, sequence=sequence, produced_at=wall,
                                  remaining_s=15.0, scope_sites=tuple(sorted(sites)),
                                  nodes=tuple(sorted(nodes, key=lambda item: item.id)),
                                  links=tuple(sorted(links, key=lambda item: item.id)))

    def _commit(self, key, records, now, wall, *, peer_cursor=None):
        remembered = self._latest | {(key, record.item.id): record for record in records.values()
                                     if record.item.sample_id is not None}
        if len(remembered) > MAX_REMEMBERED:
            raise ObservationRejected("MONITORING_CAPACITY")
        proposed = self._groups | {key: records}
        self._compose(proposed, self.scope_sites, now, wall, self._sequence)
        if self.store is not None:
            self.store.save(key, [record.value(now) for record in records.values()],
                            wall=wall, peer_cursor=peer_cursor)
        self._groups = proposed
        self._latest = remembered

    def update_local(self, source_id, *, nodes=(), links=(), complete=True):
        source = self._source(source_id)
        now, wall = self._now(), self._wall()
        scopes = set(source.peer_sites) if source.kind == "peer" else {source.site_id}
        if source.kind == "peer" and nodes:
            raise ObservationRejected()
        key = ("local", source_id)
        old = self._groups.get(key, {})
        records = {} if complete else dict(old)
        items = (*nodes, *links)
        if len(items) > 6144 or len({item.id for item in items}) != len(items):
            raise ObservationRejected()
        for item in items:
            if (item.site_id not in scopes or item.origin_collector != self.config.collector_id
                    or item.origin_source != source_id):
                raise ObservationRejected()
            if source.kind == "peer" and (not isinstance(item, MonitoringLink) or item.kind != "probe"):
                raise ObservationRejected()
            anchor = self._latest.get((key, item.id), old.get(item.id))
            records[item.id] = self._record(item, anchor, now, wall, 0.0, 15.0, peer=False)
        self._commit(key, records, now, wall)

    def receive_peer(self, source_id, snapshot: MonitoringSnapshot, *, request_started_at, elapsed_s):
        source = self._source(source_id)
        now, wall = self._now(), self._wall()
        if (source.kind != "peer" or snapshot.collector_id != source.id
                or set(snapshot.scope_sites) != set(source.peer_sites)):
            raise ObservationRejected()
        previous = self._peers.get(source_id)
        if (snapshot.generation in self._retired[source_id]
                or previous and snapshot.generation == previous[0] and snapshot.sequence <= previous[1]):
            raise ObservationRejected("MONITORING_REPLAY")
        if (type(elapsed_s) not in (int, float) or not math.isfinite(elapsed_s) or elapsed_s < 0
                or not isinstance(request_started_at, datetime) or request_started_at.utcoffset() is None):
            raise ObservationRejected("MONITORING_CLOCK")
        if (abs((wall - request_started_at).total_seconds() - elapsed_s) > 1.0
                or not request_started_at - timedelta(seconds=1) <= snapshot.produced_at <= wall + timedelta(seconds=1)):
            raise ObservationRejected("MONITORING_CLOCK")
        key = ("peer", source_id)
        old, records = self._groups.get(key, {}), {}
        items = (*snapshot.nodes, *snapshot.links)
        required = {f"{site}:collector:{source_id}" for site in source.peer_sites}
        if not required <= {node.id for node in snapshot.nodes}:
            raise ObservationRejected()
        for item in items:
            if (item.origin_collector == self.config.collector_id or item.site_id not in source.peer_sites
                    or item.id == f"{item.site_id}:collector:{self.config.collector_id}"):
                raise ObservationRejected()
            anchor = self._latest.get((key, item.id), old.get(item.id))
            records[item.id] = self._record(item, anchor, now, wall, elapsed_s + 1.0,
                                            snapshot.remaining_s, peer=True)
        retired = deque(self._retired[source_id], maxlen=64)
        if previous and snapshot.generation != previous[0]:
            retired.append(previous[0])
        cursor = (snapshot.generation, snapshot.sequence, list(retired))
        self._commit(key, records, now, wall, peer_cursor=cursor)
        self._retired[source_id] = retired
        self._peers[source_id] = (snapshot.generation, snapshot.sequence)

    def snapshot(self, sites: frozenset[str]) -> MonitoringSnapshot:
        if not sites or not sites <= self.scope_sites:
            raise ObservationRejected()
        now, wall = self._now(), self._wall()
        self._sequence += 1
        return self._compose(self._groups, sites, now, wall, self._sequence)
