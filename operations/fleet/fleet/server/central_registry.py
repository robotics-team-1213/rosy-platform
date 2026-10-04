"""중앙 Fleet 레지스트리 읽기 모델 (D-454 1단계, API Ref §10.1).

세 출처를 한 행으로 합친다 — 정적/등록 로스터(`SiteRoster`), hub 온라인·스냅샷
(D-447a), 발견 주소. Fleet은 상태를 다시 계산하지 않는다(D-309): 로봇이 만든
증거 필드를 그대로 흘린다. 새 저장소가 없고 기존 객체를 읽기만 한다.
"""

from __future__ import annotations


class CentralRegistry:
    """`GET /api/v1/fleet/robots` 의 데이터. 로스터가 정본, hub·발견은 보강이다."""

    def __init__(self, roster, console=None, discovery=None) -> None:
        self._roster = roster
        self._console = console
        self._discovery = discovery

    @property
    def roster(self):
        """§10.1 등록 해제(REG-001a)가 부르는 로스터 정본."""
        return self._roster

    def _hub_record(self, robot_id: str):
        hub = getattr(self._console, "hub", None) if self._console is not None else None
        registry = getattr(hub, "registry", None) if hub is not None else None
        find = getattr(registry, "find", None)
        return find(robot_id) if callable(find) else None

    def _address_last_seen(self, robot_id: str):
        if self._discovery is None:
            return None
        if self._console is None:
            return None
        # Bind hints only through the existing approved endpoints; names alone are not identity.
        snapshot = self._discovery.snapshot(
            self._console.registered_endpoints, self._console.hub.registry.identity_snapshot())
        addresses = {row["address"] for row in snapshot["devices"]
                     if row.get("robot_id") == robot_id and row["status"] != "conflict"}
        return next(iter(addresses)) if len(addresses) == 1 else None

    def row(self, robot_id: str) -> dict | None:
        """로스터에 없는 로봇은 중앙 레지스트리에도 없다(등록이 정본)."""
        if robot_id not in self._roster.robot_ids:
            return None
        source = "static" if self._roster.source_of(robot_id) == "file" else "enrolled"
        record = self._hub_record(robot_id)
        snapshot = getattr(record, "snapshot", None)
        state = snapshot.model_dump(mode="json") if snapshot is not None else None
        capabilities = state.get("capabilities") if isinstance(state, dict) else None
        return {
            "robot_id": robot_id,
            "source": source,
            "online": bool(getattr(record, "online", False)),
            "state": state,
            "capabilities": capabilities,
            "address_last_seen": self._address_last_seen(robot_id),
        }

    def rows(self) -> list[dict]:
        """robot_id 오름차순. 정렬·페이지는 이 단계에 없다(§10.1 요구 밖)."""
        return [row for robot_id in sorted(self._roster.robot_ids)
                if (row := self.row(robot_id)) is not None]
