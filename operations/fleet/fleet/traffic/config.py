"""Fleet traffic configuration parsing for the CLI."""

import sys
from pathlib import Path


def _traffic_zones(args) -> dict:
    """D-517 3: ``fleet.traffic.zones`` of ``--site-config``: ``{zone id: {edges: [...], capacity: 1}}``."""
    import yaml

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        raw = ((site_config.get("fleet") or {}).get("traffic") or {}).get("zones") or {}
        zones = {}
        for zone, spec in raw.items():
            edges, capacity = [str(edge) for edge in spec["edges"]], int(spec.get("capacity", 1))
            if not edges or capacity < 1:
                raise ValueError(f"zone {zone} needs edges and a capacity of at least 1")
            zones[str(zone)] = (edges, capacity)
        return zones
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"traffic config: {exc}")


def _traffic_signals(args) -> list:
    """D-525: ``fleet.traffic.signals`` of ``--site-config``: ``{signal id: {zone, phases: [{approach,
    green_s}], yellow_s, all_red_s}}``. The map check (approaches, capacity 1) runs on each map version."""
    import yaml

    from fleet.traffic.signal_phase import SignalPlan

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        raw = ((site_config.get("fleet") or {}).get("traffic") or {}).get("signals") or {}
        return [SignalPlan(str(signal_id), str(spec["zone"]),
                           tuple((str(p["approach"]), float(p["green_s"])) for p in spec["phases"]),
                           float(spec.get("yellow_s", 2.0)), float(spec.get("all_red_s", 1.0)))
                for signal_id, spec in raw.items()]
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"traffic config: signals: {exc}")


def _traffic_flag(args, key: str) -> bool:
    """``fleet.traffic.<key>`` (YAML true/false, default false) of ``--site-config``."""
    import yaml

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        value = ((site_config.get("fleet") or {}).get("traffic") or {}).get(key, False)
    except (OSError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"traffic config: {exc}")
    if not isinstance(value, bool):
        sys.exit(f"traffic config: fleet.traffic.{key} must be true or false")
    return value


def _traffic_authority(args) -> bool:
    """D-517 4 (M2): ``fleet.traffic.authority``."""
    return _traffic_flag(args, "authority")


def _traffic_signal_advice(args) -> bool:
    """D-551 6: ``fleet.traffic.signal_advice`` (display-only signal advice to CORE)."""
    return _traffic_flag(args, "signal_advice")


def _trip_lease(args) -> dict:
    """D-541 7: ``fleet.trip_lease_required`` (default false) and ``fleet.trip_lease_ttl_s`` (default 5, 1..10)."""
    import yaml

    from core_common.protocol.trip_lease import DEFAULT_TTL_S, MAX_TTL_S, MIN_TTL_S

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        fleet = site_config.get("fleet") or {}
        required, ttl_s = fleet.get("trip_lease_required", False), fleet.get("trip_lease_ttl_s", DEFAULT_TTL_S)
    except (OSError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"trip lease config: {exc}")
    if not isinstance(required, bool):
        sys.exit("trip lease config: fleet.trip_lease_required must be true or false")
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or not MIN_TTL_S <= ttl_s <= MAX_TTL_S:
        sys.exit(f"trip lease config: fleet.trip_lease_ttl_s must be within {MIN_TTL_S:g}..{MAX_TTL_S:g}")
    return {"required": required, "ttl_s": float(ttl_s)}
