"""core_api_web.api.ui_manifest — 화면 매니페스트 (D-204). 순수 함수, ROS 무의존.

CAP-001은 기능 게이트, inventory descriptors는 동적 상태다(D-68). 둘을 읽기만 하고
합치지 않는다. `not_provided`는 회색이 아니라 생략이다(concept 16 §8).

`revision`은 조립 구조만의 해시다 — 셸은 이 값이 바뀔 때만 패널을 다시 mount하고,
바뀌지 않으면 매니페스트의 `state`/`reason`만 그 자리에서 갱신한다(D-204 §4).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from core_common.capability import Capability

from core_api_web.api.deps import ROLE_RANK
from core_api_web.api.ui_registry import Panel, Registry

ASSET_PREFIX = "/assets/"
NOT_PROVIDED = "not_provided"


def _visible(panel: Panel, role: str, capability: Capability, by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    if ROLE_RANK.get(role, -1) < ROLE_RANK[panel.min_role]:
        return False
    if not all(capability.supports(key) for key in panel.requires):
        return False
    descriptor = by_id.get(panel.inventory) if panel.inventory else None
    return not (descriptor and descriptor.get("state") == NOT_PROVIDED)


def build_manifest(
    registry: Registry,
    surface_id: str,
    role: str,
    capabilities: Mapping[str, Any],
    descriptors: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    surface = registry.surfaces[surface_id]
    capability = Capability(dict(capabilities))
    by_id = {str(item.get("id")): item for item in descriptors}
    visible = [panel for panel in registry.panels if _visible(panel, role, capability, by_id)]
    slot_rank = {slot: index for index, slot in enumerate(surface.slots)}
    mine = sorted((p for p in visible if p.surface == surface.id), key=lambda p: (slot_rank[p.slot], p.order))
    panels = []
    for panel in mine:
        descriptor = by_id.get(panel.inventory, {}) if panel.inventory else {}
        panels.append({
            "id": panel.id,
            "title": panel.title,
            "slot": panel.slot,
            "order": panel.order,
            "module": ASSET_PREFIX + panel.module,
            "css": [ASSET_PREFIX + path for path in panel.css],
            "action_group": panel.action_group,
            "state": descriptor.get("state", "available"),
            "reason": descriptor.get("reason"),
        })
    body = {
        "surface": surface.id,
        "grammar": surface.grammar,
        "role": role,
        "surfaces": [{"id": s.id, "title": s.title} for s in registry.surfaces.values()
                      if ROLE_RANK.get(role, -1) >= ROLE_RANK[s.min_role]],
        "panels": panels,
    }
    # revision은 조립 구조(어떤 패널이 어느 슬롯·순서에 있는가)만 본다. state/reason은
    # inventory descriptor가 바뀔 때마다(e-stop, health) 같이 바뀌는데, 그때마다
    # revision이 움직이면 셸이 매 폴링마다 전체 패널을 재mount하게 된다 — 셸은
    # revision으로 재조립 여부를 정하고 state는 그 자리에서 갱신한다.
    structural_panels = [
        {key: panel[key] for key in ("id", "title", "slot", "order", "module", "css", "action_group")}
        for panel in panels
    ]
    structural_body = {**body, "panels": structural_panels}
    digest = hashlib.sha256(
        json.dumps(structural_body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {**body, "revision": f"sha256:{digest}"}
