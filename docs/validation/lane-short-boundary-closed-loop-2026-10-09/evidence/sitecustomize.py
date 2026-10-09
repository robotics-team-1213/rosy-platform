"""SIM-only length experiment; imported in the control process through PYTHONPATH."""

import os

try:
    from control.sensing.perception import lane_keep
except Exception:
    lane_keep = None

if lane_keep is not None:
    original_update = lane_keep.LaneKeeper.update

    def update_with_bend(self, bgr, ground, **kwargs):
        kwargs.setdefault("bend_expected", True)
        return original_update(self, bgr, ground, **kwargs)

    lane_keep.LaneKeeper.update = update_with_bend
    length = float(os.environ.get("LEN_GATE", "0.06"))
    if length > 0.06:
        original_extract = lane_keep.extract_lines

        def extract_with_length(*args, **kwargs):
            lines, blobs = original_extract(*args, **kwargs)
            return [line for line in lines
                    if line["along"][1] - line["along"][0] >= length], blobs

        lane_keep.extract_lines = extract_with_length
