"""Stuck-side CLI adapters: `--site-config` `fleet.*` sections to config objects.

`fleet console` builds its stuck settings through these helpers so the frozen `cli.py` keeps
only the calls. They read the same `fleet.stuck_resolver` / `fleet.ai_first` keys as before and
exit with the same messages; nothing here touches a robot or the ledger.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _realign_config(args):
    """D-622 opt-in standalone recovery; empty areas and robot list by default."""
    import yaml
    from fleet.stuck.realign import RealignConfig
    try:
        site = (yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
                if getattr(args, "site_config", None) else {})
        return RealignConfig.from_mapping((site.get("fleet") or {}).get("stuck_resolver"))
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"realign config: {exc}")


def _ai_first(args):
    """D-610 3: ``fleet.ai_first`` of ``--site-config`` (robots default empty, keep_gates default trip_wait_only)."""
    import yaml

    from fleet.stuck.ai_first import AiFirst

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        return AiFirst.from_config((site_config.get("fleet") or {}).get("ai_first"))
    except (OSError, TypeError, AttributeError, ValueError, yaml.YAMLError) as exc:
        sys.exit(f"ai_first config: {exc}")


def _stuck_resolver_enrolled(args, key: str = "enrolled_robots") -> frozenset:
    """``fleet.stuck_resolver.<key>`` of ``--site-config``, a robot id list. ``enrolled_robots``: enrolled
    robots (D-361) the resolver answers with Fleet's enrolled CORE credential. ``ai_facts_acting``: robots
    whose acting AI facts may stop a resolver back-off (D-577 7). Empty (default) = none."""
    import yaml

    try:
        site_config = {}
        if getattr(args, "site_config", None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding="utf-8")) or {}
        section = (site_config.get("fleet") or {}).get("stuck_resolver") or {}
        ids = section.get(key) or []
    except (OSError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f"stuck resolver config: {exc}")
    if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
        sys.exit(f"stuck resolver config: fleet.stuck_resolver.{key} must be a list of robot ids")
    return frozenset(ids)
