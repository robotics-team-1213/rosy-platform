"""core_common.capability — CAP-001~003 (P1-15, D-11). ROS 무의존."""

from __future__ import annotations

from typing import Any


class CapabilityError(Exception):
    def __init__(self, feature: str, concept_id: str | None = None) -> None:
        super().__init__(f"capability not supported: {feature}")
        self.feature = feature
        self.concept_id = concept_id


def _walk(data: Any, dotted: str) -> Any:
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class Capability:
    """capabilities.yaml 로드 결과 (HWA-003: Profile이 원천)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def capability_version(self) -> int:
        return int(self._data.get("capability_version", 1))

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def supports(self, dotted: str) -> bool:
        value = _walk(self._data, dotted)
        return bool(value) if isinstance(value, bool) else value is not None

    def require(self, dotted: str) -> None:
        """CAP-003: 미지원 기능 요청 → CapabilityError (API 501 매핑)."""
        if not self.supports(dotted):
            raise CapabilityError(dotted)
