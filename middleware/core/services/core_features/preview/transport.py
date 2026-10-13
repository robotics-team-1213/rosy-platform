"""High-bandwidth vision path. Core does not depend on NITROS.

Camera capture and road perception stay in `control`. This module names the
graph and the only handoff Core accepts: one JPEG preview. Perception facts
arrive on `road/observation`, not as image bytes.
"""

from __future__ import annotations

from core_features.vision.store import parse_preview_format

CAMERA_TOPIC = "camera/front"
PREVIEW_TOPIC = "camera/preview/compressed"
PERCEPTION_TOPIC = "road/observation"

STAGES = ("camera", "preprocess", "segmentation", "depth_pose")
PROVIDERS = (
    "standard_ros_image",
    "intra_process",
    "shared_memory",
    "nitros",
)


class TransportUnavailable(RuntimeError):
    """The selected vision transport is not wired in this process."""


def select(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown vision transport: {provider}")
    if provider != "standard_ros_image":
        raise TransportUnavailable(
            f"{provider} is not wired; Core does not depend on NITROS")
    return provider


def accept_preview(fmt: str, *, provider: str = "standard_ros_image") -> dict:
    """Admit one display JPEG. Other formats and NITROS are refused."""
    select(provider)
    metadata = parse_preview_format(fmt)
    if metadata is None:
        raise ValueError("camera preview format must be jpeg")
    return metadata
