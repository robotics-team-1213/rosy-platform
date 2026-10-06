"""D-489/D-490 route planning on the D-488 site map. Standard library only.

No network, DB, clock or FastAPI here: ``server/trip_routes.py`` reads the active map and
the robot snapshot and calls ``trip.plan_trip``.
"""
