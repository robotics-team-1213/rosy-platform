"""Image and lane perception. Lidar, body, and dock tags stay in sensing."""

from .camera import classify_frame

__all__ = ["classify_frame"]
