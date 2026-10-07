# Fleet site-map web/server seam

Owner: fleet. Dated 2026-10-07 for the package re-judge at 38952 lines.

This does not split the package. It names the first seam so later growth has a boundary.

- Web owner: `operations/fleet/fleet/server/web/site-map.js`, `site-map-model.js`, `site-map.html`, `site-map.css`. The page stays here.
- Server owner: `site_map_routes.py`, `trip_routes.py`, `site_map_store.py`, `site_map.py`, and `operations/fleet/fleet/routing/` (`graph.py`, `trip.py`, `planner.py`, `cost.py`, `snap.py`). Route handlers and routing math stay out of the page scripts.

Since the 37182 verdict the counted production and web lines grew by 1770, inside these owners. Tests are outside the package count. The +150 allowance is unchanged. The B2 server/UI split remains unscheduled beyond this seam.
