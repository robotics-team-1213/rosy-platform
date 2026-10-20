"""CLI composition of map storage, first import and routing configuration."""
from pathlib import Path
import sys

import yaml

from fleet.routing.cost import RoutingConfig
from fleet.server.site_map_store import SiteMapStore
from fleet.server.site_map_assets import SiteMapAssetStore
from fleet.site_map import from_lane_graph


def build_site_map(args, tasks_db):
    try:
        site_config = {}
        if getattr(args, 'site_config', None) is not None:
            site_config = yaml.safe_load(Path(args.site_config).read_text(encoding='utf-8')) or {}
        routing = ((site_config.get('fleet') or {}).get('routing') if isinstance(site_config, dict) else None)
        routing_config = RoutingConfig.from_mapping(routing)
        assets = (SiteMapAssetStore(Path(tasks_db).parent / (Path(tasks_db).name + '.site-map-assets'))
                  if tasks_db is not None else None)
        site_maps = SiteMapStore(tasks_db, routing_config=routing_config, drawing_assets=assets)
        source = getattr(args, 'site_map_import', None)
        if source is not None:
            site_maps.import_source = Path(source)
            # The containing folder names the frame reported by the sighting sources.
            site_maps.import_if_empty(from_lane_graph(source, map_id=Path(source).parent.name),
                                      source=Path(source).name)
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        sys.exit(f'site map / routing config: {exc}')
    if tasks_db is None:
        print('warning: no --tasks-db; the D-488 site map lives in memory and is lost on restart',
              file=sys.stderr, flush=True)
    if site_maps.active() is None:
        print('warning: no active D-488 site map; /route and /trip are refused until one is '
              'imported (--site-map-import) or activated', file=sys.stderr, flush=True)
    return site_maps, routing_config
