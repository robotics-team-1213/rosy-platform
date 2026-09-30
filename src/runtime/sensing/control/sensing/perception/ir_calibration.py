"""IR line calibration from placed-robot samples (D-143, D-344 §12). Pure, ROS-free.

The operator places the robot four times and records raw `ir_sensor/range`
samples (robot left, centre, right order):

  carpet  all three sensors on bare floor         -> black endpoints
  left    tape under the left sensor only         -> left white endpoint
  centre  tape under the centre sensor only       -> centre white endpoint
  right   tape under the right sensor only        -> right white endpoint

Endpoints are per-channel medians, so a few bad reads do not move them. The
result is only accepted when every channel is physically separated
(`IRLineCalibration.min_span`), separated well beyond its own noise, and the
captured phases decode with the right sign through `detect_ir_line` (left tape
-> negative error, right tape -> positive error, carpet -> no line).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .lane import IRLineCalibration, detect_ir_line

PHASES = ("carpet", "left", "centre", "right")
CHANNELS = ("left", "centre", "right")
#: 12-bit ADC rails. A channel pinned there cannot show a line.
ADC_MIN = 0
ADC_MAX = 4095
#: MAD -> standard deviation for normally distributed noise.
_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class ChannelLevel:
    median: float
    sigma: float
    count: int
    saturated: int


@dataclass(frozen=True)
class IRCalibrationResult:
    black: tuple[float, float, float]
    white: tuple[float, float, float]
    min_span: float
    levels: Mapping[str, tuple[ChannelLevel, ...]]
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    phase_errors: Mapping[str, Optional[float]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def calibration(self) -> IRLineCalibration:
        return IRLineCalibration(black=self.black, white=self.white, min_span=self.min_span)

    @property
    def revision(self) -> Optional[str]:
        return self.calibration.revision if self.ok else None


def channel_levels(samples: Sequence[Sequence[float]]) -> tuple[ChannelLevel, ...]:
    """Median, robust sigma (MAD), usable count and rail count per channel."""
    levels = []
    for index in range(3):
        values = []
        saturated = 0
        for sample in samples:
            if len(sample) != 3:
                continue
            value = sample[index]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            value = float(value)
            if not math.isfinite(value):
                continue
            if value <= ADC_MIN or value >= ADC_MAX:
                saturated += 1
                continue
            values.append(value)
        if values:
            median = statistics.median(values)
            mad = statistics.median(abs(value - median) for value in values)
            levels.append(ChannelLevel(median, mad * _MAD_TO_SIGMA, len(values), saturated))
        else:
            levels.append(ChannelLevel(math.nan, math.nan, 0, saturated))
    return tuple(levels)


def compute_ir_calibration(session: Mapping[str, Sequence[Sequence[float]]], *,
                           min_span: float = 100.0,
                           min_samples: int = 20,
                           separation_sigmas: float = 6.0,
                           max_saturated_fraction: float = 0.1,
                           min_white: float = 0.55,
                           min_contrast: float = 0.15,
                           edge_error: float = 0.3) -> IRCalibrationResult:
    """Endpoints and every reason they cannot be trusted yet."""
    errors: list[str] = []
    warnings: list[str] = []
    # The node reads min_span back from the printed YAML (one decimal); hash the same value.
    min_span = round(float(min_span), 1)
    levels = {phase: channel_levels(session.get(phase) or ()) for phase in PHASES}
    for phase in PHASES:
        for name, level in zip(CHANNELS, levels[phase]):
            total = level.count + level.saturated
            if level.count < min_samples:
                errors.append(f"{phase}: {name} has {level.count} usable samples (< {min_samples})")
            elif total and level.saturated / total > max_saturated_fraction:
                errors.append(f"{phase}: {name} is at the ADC rail in "
                              f"{level.saturated}/{total} samples")
    black = tuple(round(level.median, 1) for level in levels["carpet"])
    white = tuple(round(levels[phase][index].median, 1)
                  for index, phase in enumerate(CHANNELS))
    for index, phase in enumerate(CHANNELS):
        # The channel that moved most off carpet must be the one the tape was put under;
        # otherwise the published channel order (or the placement) is wrong.
        moved = [abs(level.median - base) for level, base in zip(levels[phase], black)]
        if all(math.isfinite(value) for value in moved):
            strongest = max(range(3), key=moved.__getitem__)
            if strongest != index:
                errors.append(f"{phase} tape moved the {CHANNELS[strongest]} channel most - "
                              "channel order swapped or tape under the wrong sensor")
    polarity = []
    for index, name in enumerate(CHANNELS):
        b, w = black[index], white[index]
        if not (math.isfinite(b) and math.isfinite(w)):
            continue
        span = abs(w - b)
        if span < min_span:
            errors.append(f"{name}: tape/carpet span {span:.1f} < min_span {min_span:g}")
        noise = levels["carpet"][index].sigma + levels[CHANNELS[index]][index].sigma
        if noise > 0 and span < separation_sigmas * noise:
            errors.append(f"{name}: span {span:.1f} is under {separation_sigmas:g}x noise "
                          f"({noise:.1f})")
        polarity.append(w > b)
    if len(set(polarity)) > 1:
        warnings.append("channels disagree on polarity (tape reads higher on some, lower on "
                        "others) - check sensor wiring and tape placement")
    phase_errors: dict[str, Optional[float]] = {}
    if not errors:
        try:
            calibration = IRLineCalibration(black=black, white=white, min_span=min_span)
        except ValueError as exc:
            errors.append(f"IRLineCalibration rejected the endpoints: {exc}")
        else:
            for phase in PHASES:
                medians = tuple(level.median for level in levels[phase])
                observation = detect_ir_line(medians, calibration, min_white=min_white,
                                             min_contrast=min_contrast)
                phase_errors[phase] = None if observation is None else observation.error
            errors.extend(sign_errors(phase_errors, edge_error=edge_error))
    return IRCalibrationResult(black=black, white=white, min_span=float(min_span),
                               levels=levels, errors=tuple(errors), warnings=tuple(warnings),
                               phase_errors=phase_errors)


def sign_errors(phase_errors: Mapping[str, Optional[float]], *,
                edge_error: float = 0.3) -> list[str]:
    """Left tape must decode negative, right positive, centre near 0, carpet as no line.

    CORE's IR guard (D-344 §12) steers right when error <= -edge_error, so a
    swapped left/right would steer the robot onto the boundary.
    """
    problems = []
    if phase_errors.get("carpet") is not None:
        problems.append(f"carpet decodes as a line (error {phase_errors['carpet']:+.2f})")
    left = phase_errors.get("left")
    if left is None or left > -edge_error:
        problems.append(f"left tape must decode <= -{edge_error:g}, got {_fmt(left)}")
    right = phase_errors.get("right")
    if right is None or right < edge_error:
        problems.append(f"right tape must decode >= +{edge_error:g}, got {_fmt(right)}")
    centre = phase_errors.get("centre")
    if centre is None or abs(centre) >= edge_error:
        problems.append(f"centre tape must decode within +-{edge_error:g}, got {_fmt(centre)}")
    return problems


def ir_side(error: Optional[float], *, edge_error: float = 0.3) -> str:
    """none | left | centre | right — the same split CORE's IR guard uses."""
    if error is None:
        return "none"
    if error <= -edge_error:
        return "left"
    if error >= edge_error:
        return "right"
    return "centre"


def render_config(result: IRCalibrationResult) -> str:
    """The rosy-io line_follow.yaml block and the matching CORE rosy.yaml key."""
    if not result.ok:
        raise ValueError("calibration has errors; refusing to render a config")

    def floats(values):
        return "[" + ", ".join(f"{float(value):.1f}" for value in values) + "]"

    return (
        "# /etc/rosy/ir_calibration.yaml (rosy-camera line_observer_node; this block only)\n"
        "/**/line_observer_node:\n"
        "  ros__parameters:\n"
        "    ir_calibration_enabled: true\n"
        f"    ir_black: {floats(result.black)}\n"
        f"    ir_white: {floats(result.white)}\n"
        f"    ir_min_span: {result.min_span:.1f}\n"
        "\n"
        "# CORE local config (native: /var/lib/rosy/core/.rosy/rosy.yaml) - must equal the digest\n"
        "line_follow:\n"
        f"  ir_calibration_revision: {result.revision}\n"
    )


def _fmt(value: Optional[float]) -> str:
    return "no line" if value is None else f"{value:+.2f}"
