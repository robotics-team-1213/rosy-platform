"""B9 SIM only (never on a robot): stand-in for the B11/B12 route context.

Puts the keeper's bend_expected input on for every frame of this SIM process (the D-495 trip
probe drives the west lane, the W->S corner and the SW bend; the route expects the bend there).
Loaded through PYTHONPATH by b9_run.sh when GATE=1; a process without the perception package
is left alone.
"""
try:
    from control.sensing.perception import lane_keep as _keep
except Exception:  # noqa: BLE001 - CORE, the bridges and the CLI do not carry the keeper
    _keep = None

if _keep is not None:
    _update = _keep.LaneKeeper.update

    def _update_with_bend_expected(self, bgr, ground, **kwargs):
        kwargs.setdefault("bend_expected", True)
        return _update(self, bgr, ground, **kwargs)

    _keep.LaneKeeper.update = _update_with_bend_expected
    # No stderr here: ros2 launch rejects a substitution command that writes stderr.
