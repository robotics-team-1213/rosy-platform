# Fleet site-map web/server seam

Owner: fleet. Dated 2026-10-07 for the package re-judge at 38952 lines.

This does not split the package. It names the first seam so later growth has a boundary.

- Web owner: `operations/fleet/fleet/server/web/site-map.js`, `site-map-model.js`, `site-map.html`, `site-map.css`. The page stays here.
- Server owner: `site_map_routes.py`, `trip_routes.py`, `site_map_store.py`, `site_map.py`, and `operations/fleet/fleet/routing/` (`graph.py`, `trip.py`, `planner.py`, `cost.py`, `snap.py`). Route handlers and routing math stay out of the page scripts.

Since the 37182 verdict the counted production and web lines grew by 1770, inside these owners. Tests are outside the package count. The +150 allowance is unchanged. The B2 server/UI split remains unscheduled beyond this seam.

## Camera backdrop seam (2026-10-08)

Named at the map-view.js re-judge (903 lines, web ceiling 800). The D-513 7 camera turn and the D-515 top-down warp gave `map-view.js` a second job, the camera picture path.

- Move `cameraMapCalibration`, `drawCameraTopDown`, `warpOnto`, the top-down cache, `setCameraFrame`, `frameTurn`, `turnedUrl` and `bindCamera` to a new `operations/fleet/fleet/server/web/camera-backdrop.js` beside `camera-warp.js`.
- `map-view.js` keeps map drawing (grid, robots, formation, mediation, metre site view) and passes a draw hook and its `toPx` projection to the backdrop.
- The backdrop needs only the calibrations, `view`, `el`, `scope` and that draw callback. Expected `map-view.js` size after the move is about 790 lines. Re-judge after the move.
