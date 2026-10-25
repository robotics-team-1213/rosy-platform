"""``fleet console`` 사이트 설정 helper — ``--site-config`` YAML의 ``fleet.*`` 절 해석.

D-766 4 나누기: cli.py(레칫 872)에서 그대로 옮겼다(정의 순서·본문 불변). 새 helper도
이 모듈에 추가하고 cli.py는 줄을 늘리지 않는다. 결과 없이 잘못된 설정은 sys.exit로
끝난다(cli_config 패턴 그대로).
"""

import sys
from pathlib import Path


def _goal_lease_ttl_s(args) -> float:
    """D-550 10: ``fleet.goal_lease_ttl_s`` of ``--site-config``; 0 (default) = no goal lease.
    Otherwise floor..5 s: CORE takes at most 5 s; the floor is 2 x ``fleet.trip.port_timeout_s`` +
    ``period_s`` (3.5 s by default), so a trip step that times out once on its pose read and once
    on its renewal still renews before the lease runs out."""
    import yaml

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        value = (site_config.get("fleet") or {}).get("goal_lease_ttl_s", 0)
    except (OSError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"goal lease config: {exc}")
    trip = _trip_config(args)
    floor = 2 * trip.port_timeout_s + trip.period_s
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
            value == 0 or floor <= value <= 5):
        sys.exit(f"goal lease config: fleet.goal_lease_ttl_s must be 0 (off) or {floor:g}..5")
    return float(value)


def _trip_config(args):
    """D-494 5: the trip loop's ``fleet.trip`` section of ``--site-config`` (e.g. ``stall_s``)."""
    import yaml

    from fleet.server.trip_runner import TripConfig

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        trip = (site_config.get("fleet") or {}).get("trip") if isinstance(site_config, dict) else None
        return TripConfig.from_mapping(trip)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        sys.exit(f"trip config: {exc}")


def _build_site_map(args, tasks_db):
    """D-488/D-490: site map store (+ first import) and the planner's ``fleet.routing`` costs."""
    import yaml

    from fleet.routing.cost import RoutingConfig
    from fleet.server.site_map_store import SiteMapStore
    from fleet.site_map import from_lane_graph

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        routing = ((site_config.get("fleet") or {}).get("routing") if isinstance(site_config, dict) else None)
        routing_config = RoutingConfig.from_mapping(routing)
        site_maps = SiteMapStore(tasks_db, routing_config=routing_config)
        source = getattr(args, "site_map_import", None)
        if source is not None:
            site_maps.import_source = Path(source)
            # map/<map_id>/lane_graph.yaml: the folder names the map frame the sighting sources
            # report; the default "site" would filter every sighting (map pose UNKNOWN).
            site_maps.import_if_empty(from_lane_graph(source, map_id=Path(source).parent.name),
                                      source=Path(source).name)
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"site map / routing config: {exc}")
    if tasks_db is None:
        print("warning: no --tasks-db; the D-488 site map lives in memory and is lost on restart",
              file=sys.stderr, flush=True)
    if site_maps.active() is None:
        print("warning: no active D-488 site map; /route and /trip are refused until one is "
              "imported (--site-map-import) or activated", file=sys.stderr, flush=True)
    return site_maps, routing_config


def _map_pose_config(args):
    """D-494 3: the site YAML's ``fleet.map_pose`` limits; defaults without a site config."""
    import yaml

    from rosy.world.state.projections.map_pose import MapPoseConfig

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        return MapPoseConfig.from_mapping((site_config.get("fleet") or {}).get("map_pose"))
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"map_pose config: {exc}")


def _lane_compliance_config(args):
    """D-511 2: the site YAML's ``fleet.lane_compliance`` thresholds; provisional defaults without."""
    import yaml

    from fleet.localization.lane_compliance import LaneComplianceConfig

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        return LaneComplianceConfig.from_mapping((site_config.get("fleet") or {}).get("lane_compliance"))
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"lane_compliance config: {exc}")


def _policy_admission_core(args):
    """D-865: ``fleet.policy_admission`` of ``--site-config`` → core (disabled when absent)."""
    import yaml
    from datetime import datetime, timezone

    from fleet.server.missions.policy_admission import (
        PolicyAdmissionCore, PolicyAdmissionSettings)

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(
                Path(args.site_config).read_text(encoding="utf-8")) or {}
        settings = PolicyAdmissionSettings.from_config(
            (site_config.get("fleet") or {}).get("policy_admission"))
    except (OSError, TypeError, AttributeError, ValueError, yaml.YAMLError) as exc:
        sys.exit(f"policy_admission config: {exc}")
    return PolicyAdmissionCore(
        settings, now=lambda: datetime.now(timezone.utc).isoformat())
