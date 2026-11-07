"""D-982 site rules API: read the active document, edit one draft, activate it, ask what the rules say.

Saving and activating need a named operator and are site map events; activation is refused while
a route runs. ``POST /api/fleet/site-rules/judge`` is advice from a hypothetical state: it reads
and computes, sends nothing to a robot and changes nothing, so it needs only read access.
Errors use ``{"detail": {"code", "detail"}}`` like the site map routes.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_routes import site_map_error
from fleet.server.site_map_store import SiteMapError
from fleet.site_rules import SiteRules
from fleet.site_rules_judge import State, judge


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: SiteRules
    expected_revision: Optional[str] = Field(default=None, min_length=1, max_length=64)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)


class JudgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: State = Field(discriminator="kind")
    #: Rules to judge by: a document given here, else the saved draft or the active document.
    rules: Optional[SiteRules] = None
    source: Literal["active", "draft"] = "active"


def install_site_rules_routes(app, *, site_maps, route_active, read_guard, require_named_operator) -> None:
    rules = site_maps.rules

    def fail(exc: SiteMapError) -> HTTPException:
        return site_map_error(exc.status_code, exc.code, str(exc))

    @app.get("/api/fleet/site-rules/active", dependencies=read_guard, tags=["site-rules"])
    def site_rules_active() -> dict:
        view = rules.active_view()
        return view if view is not None else {"version": None, "rules": SiteRules().body()}

    @app.get("/api/fleet/site-rules/draft", dependencies=read_guard, tags=["site-rules"])
    def site_rules_draft() -> dict:
        return rules.draft_view()

    @app.put("/api/fleet/site-rules/draft", tags=["site-rules"])
    def site_rules_save_draft(body: DraftRequest, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return rules.save_draft(body.rules, expected_revision=body.expected_revision,
                                    principal_id=principal.principal_id)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post("/api/fleet/site-rules/activate", tags=["site-rules"])
    def site_rules_activate(body: ActivateRequest,
                            principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return rules.activate(expected_revision=body.expected_revision,
                                  principal_id=principal.principal_id, route_active=route_active())
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post("/api/fleet/site-rules/judge", dependencies=read_guard, tags=["site-rules"])
    def site_rules_judge(body: JudgeRequest) -> dict:
        draft = rules.draft_view()["rules"] if body.source == "draft" else None
        if body.rules is not None:
            chosen, source = body.rules, "given"
        elif draft is not None:
            chosen, source = SiteRules.model_validate(draft), "draft"
        elif rules.active_rules() is not None:
            chosen, source = rules.active_rules(), "active"
        else:
            chosen, source = SiteRules(), "default"
        return {**judge(chosen, body.state), "rules_source": source, "dispatch": False}
