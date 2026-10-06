"""D-485/D-486 route planning on the D-484 site map. Standard library only.

No network, DB, clock or FastAPI here: ``server/trip_routes.py`` reads the active map and
the robot snapshot and calls ``trip.plan_trip``.
"""
