"""UI surface DTOs; canonical imports remain in protocol.schemas."""
from pydantic import BaseModel


class UiSurfaceLink(BaseModel):
    id: str
    title: str


class UiPanelDescriptor(BaseModel):
    id: str
    title: str
    slot: str
    order: int
    module: str
    css: list[str]
    action_group: str | None = None
    state: str
    reason: str | None = None


class UiActionGroup(BaseModel):
    id: str
    title: str
    order: int


class UiSurfaceManifest(BaseModel):
    surface: str
    grammar: str
    role: str
    surfaces: list[UiSurfaceLink]
    action_groups: list[UiActionGroup]
    panels: list[UiPanelDescriptor]
    revision: str
