"""Device kinds that connect to a site as clients (D-391 4.1, D-370 S5).

One place for the `device_kind` values shared by the Fleet enrollment and
pairing stores, the site-link record `role` field and the pairing audit.
The strings match the DNS-SD TXT `role` values (discovery-txt.v1.json).
"""

from __future__ import annotations

OVERHEAD_CAMERA = "overhead-camera"
ROBOT = "robot"

ALL = (OVERHEAD_CAMERA, ROBOT)
