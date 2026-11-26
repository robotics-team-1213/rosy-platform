"""Unified site points route (``GET /api/fleet/site-points?view=full|port``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from fleet.pipeline.cell_site_targets import _map_path, list_canonical_sites
from fleet.server.site_map_store import SiteMapError
from fleet.site_points import build_site_points


def _coerce_web_common(raw) -> Path | None:
    if isinstance(raw, Path):
        return raw
    if isinstance(raw, str) and raw:
        return Path(raw)
    return None


def _load_legacy_station_zones(web_common: Path | None) -> dict:
    doc = json.loads(_map_path(web_common).read_text(encoding="utf-8"))
    aliases = doc.get("aliases")
    legacy = aliases.get("legacy_station_zones") if isinstance(aliases, dict) else None
    return dict(legacy) if isinstance(legacy, dict) else {}


def install_site_points_routes(app, *, site_maps, read_guard) -> None:
    """Register read-only unified site-points endpoint synthesizing active map, rules and 37-site topology."""

    @app.get("/api/fleet/site-points", dependencies=read_guard, tags=["site-map"])
    async def fleet_site_points(
        view: Literal["full", "port"] = "full",
        include_junctions: bool = False,
    ) -> dict:
        try:
            active_view = site_maps.active_view()
            rules_obj = site_maps.rules.active_rules()
            raw_rules_view = site_maps.rules.active_view()
            rules_view = raw_rules_view if rules_obj is not None else None
        except SiteMapError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "detail": {"message": str(exc)}},
            ) from exc
        active = site_maps.active()
        if active_view is None or active is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SITE_MAP_NOT_ACTIVE", "detail": {"message": "activate a site map first (D-488)"}},
            )
        _, site_map, _graph, _painted = active
        web_common = _coerce_web_common(getattr(app.state, "web_common", None))
        cell_sites = list_canonical_sites(web_common, include_zone_layout=view == "full")
        legacy_aliases = _load_legacy_station_zones(web_common) if view == "full" else None
        return build_site_points(
            site_map_view=active_view,
            site_map=site_map,
            site_rules_view=rules_view,
            site_rules=rules_obj,
            cell_sites=cell_sites,
            legacy_station_zones=legacy_aliases,
            view=view,
            include_junctions=include_junctions,
        )
