"""HTTP adapter for CORE mode, teleop, and safety/stop.

PlayerClient lives next to MatchHost; this module re-exports it. OpenCV,
core, and fleet stay out.
"""

from __future__ import annotations

import httpx

from games.host.loop import PlayerClient
from games.host.robots import RobotEndpoint

__all__ = ["HttpPlayerClient", "PlayerClient"]


class HttpPlayerClient:
    def __init__(
        self,
        endpoint: RobotEndpoint,
        *,
        http: httpx.Client | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.robot_id = endpoint.id
        self._ep = endpoint
        self._owns_http = http is None
        self._http = http or httpx.Client(
            base_url=endpoint.url.rstrip("/"),
            timeout=timeout_s,
        )

    def _headers(self) -> dict[str, str]:
        if not self._ep.token:
            return {}
        return {"Authorization": f"Bearer {self._ep.token}"}

    def _post(self, path: str, body: dict | None = None) -> None:
        response = self._http.post(path, json=body, headers=self._headers())
        response.raise_for_status()

    def _put(self, path: str, body: dict | None = None) -> None:
        response = self._http.put(path, json=body, headers=self._headers())
        response.raise_for_status()

    def set_manual(self) -> None:
        self._post("/api/v1/mode", {"mode": "MANUAL"})

    def set_limits(self, linear: float, angular: float) -> None:
        self._put("/api/v1/safety/limits", {"manual_linear": linear, "manual_angular": angular})

    def teleop(self, linear: float, angular: float) -> None:
        self._post("/api/v1/teleop", {"linear": linear, "angular": angular})

    def estop(self) -> None:
        self._post("/api/v1/safety/stop")

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
