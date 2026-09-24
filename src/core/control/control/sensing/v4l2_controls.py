"""Fail-closed V4L2 exposure and white-balance locking helpers."""

import math


def freeze_v4l2_controls(capture, cv2_module):
    """Freeze settled V4L2 auto controls and return an auditable summary.

    OpenCV backends vary in their numeric manual-exposure convention. 0.25 is
    the V4L2 convention and 1.0 is used by some wrappers; a backend must accept
    one plus disabling auto white balance or the camera remains unavailable to
    line following.
    """
    exposure = capture.get(cv2_module.CAP_PROP_EXPOSURE)
    gain = capture.get(cv2_module.CAP_PROP_GAIN)
    white_balance = capture.get(cv2_module.CAP_PROP_WB_TEMPERATURE)
    values = (exposure, gain, white_balance)
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(float(value)) for value in values):
        return None

    exposure_locked = any(
        capture.set(cv2_module.CAP_PROP_AUTO_EXPOSURE, manual)
        for manual in (0.25, 1.0)
    )
    white_balance_locked = capture.set(cv2_module.CAP_PROP_AUTO_WB, 0.0)
    if not exposure_locked or not white_balance_locked:
        return None
    auto_exposure = capture.get(cv2_module.CAP_PROP_AUTO_EXPOSURE)
    auto_white_balance = capture.get(cv2_module.CAP_PROP_AUTO_WB)
    if (not isinstance(auto_exposure, (int, float))
            or not math.isfinite(float(auto_exposure))
            or min(abs(float(auto_exposure) - 0.25),
                   abs(float(auto_exposure) - 1.0)) > 0.05):
        return None
    if (not isinstance(auto_white_balance, (int, float))
            or not math.isfinite(float(auto_white_balance))
            or float(auto_white_balance) > 0.5):
        return None
    if not capture.set(cv2_module.CAP_PROP_EXPOSURE, exposure):
        return None
    # Some V4L2 drivers report but do not expose gain/WB setters. Their auto
    # loops are already disabled; reapply only when the value is meaningful.
    if gain > 0.0:
        capture.set(cv2_module.CAP_PROP_GAIN, gain)
    if white_balance > 0.0:
        capture.set(cv2_module.CAP_PROP_WB_TEMPERATURE, white_balance)
    return {
        "exposure": float(exposure),
        "gain": float(gain),
        "white_balance": float(white_balance),
    }


def v4l2_lock_summary(controls) -> str:
    if not controls:
        return "auto"
    return (f'v4l2 exposure={controls["exposure"]:.3f} '
            f'gain={controls["gain"]:.3f} '
            f'white_balance={controls["white_balance"]:.3f}')
