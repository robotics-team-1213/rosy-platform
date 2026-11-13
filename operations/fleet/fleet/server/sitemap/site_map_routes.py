"""D-488 site map API: read the active map, edit one draft, activate it.

``GET /api/fleet/site-map`` (D-257 camera rectangle) stays as it is; these live below it.
Saving the draft and activating it need a named operator and are recorded as site map
events; activation is also in the HTTP audit and is refused while a lane route is running.
Errors use ``{"detail": {"code", "detail"}}`` like ``/trip``. Nothing here talks to a robot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Callable, Optional

import yaml
from fastapi import Depends, HTTPException, Query, Request, Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fleet.map_reality import compare, transform_map
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_camera_source import CameraDraftError, CameraDraftRequest, camera_draft
from fleet.server.site_map_store import SiteMapError
from fleet.site_map import MapProfileInfo, SiteMap, crosswalks_from_lane_graph

#: camera candidate points arrive over the wire; Infinity/NaN must refuse, not crash the judge
FiniteXY = tuple[Annotated[float, Field(allow_inf_nan=False)], Annotated[float, Field(allow_inf_nan=False)]]

if TYPE_CHECKING:
    from fleet.server.path_history import PathRecorder

#: A 20k-point map is about 0.5 MB of JSON; the draft body is read at most this far.
MAX_DRAFT_BYTES = 2 * 1024 * 1024

#: D-594 path history keeps 24 h; judging the default 6 h is one shift of driving.
DEFAULT_WINDOW_S = 6 * 3600.0
MAX_WINDOW_S = 24 * 3600.0


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    map: SiteMap
    expected_revision: Optional[str] = Field(default=None, min_length=1, max_length=64)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)


class ProfileRequest(DraftRequest, MapProfileInfo):
    name: str = Field(min_length=1, max_length=64, pattern=r"\S")


class RealityCheckRequest(BaseModel):
    """The read-only check with the camera as a second witness (Vision's draft-map lanes)."""

    model_config = ConfigDict(extra="forbid")
    last_s: float = Field(default=DEFAULT_WINDOW_S, gt=0, le=MAX_WINDOW_S)
    robot_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    camera_lanes: Optional[list[list[FiniteXY]]] = Field(
        default=None, min_length=1, max_length=200)


class RealityApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)
    last_s: float = Field(default=DEFAULT_WINDOW_S, gt=0, le=MAX_WINDOW_S)
    robot_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    camera_lanes: Optional[list[list[FiniteXY]]] = Field(
        default=None, min_length=1, max_length=200)


def invalid_errors(exc: ValidationError) -> list[dict]:
    """Field errors without the submitted values (``SITE_MAP_INVALID`` ``detail.errors``)."""
    return [{"loc": [str(part) for part in item["loc"]], "msg": item["msg"]}
            for item in exc.errors(include_url=False, include_context=False, include_input=False)[:20]]


def site_map_error(status: int, code: str, message: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": {"message": message} if message else {}})


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and (len(declared) > 12 or not declared.isdigit() or int(declared) > MAX_DRAFT_BYTES):
        raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"draft body is limited to {MAX_DRAFT_BYTES} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_DRAFT_BYTES:
            raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"draft body is limited to {MAX_DRAFT_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def install_site_map_routes(app, *, site_maps, route_active, read_guard, require_named_operator,
                            paths: Optional[Callable[[], Optional["PathRecorder"]]] = None) -> None:
    if paths is None:  # app.state.paths is wired later in create_app; read it lazily at request time
        def paths():
            return getattr(app.state, "paths", None)
    app.state.site_maps = site_maps
    from fleet.server.site_map_drawing_routes import install_site_map_drawing_routes
    install_site_map_drawing_routes(app, assets=site_maps.drawing_assets, read_guard=read_guard,
                                   require_named_operator=require_named_operator)

    from fleet.server.site_rules_routes import install_site_rules_routes  # D-982: beside the map it is judged on
    install_site_rules_routes(app, site_maps=site_maps, route_active=route_active, read_guard=read_guard,
                              require_named_operator=require_named_operator)
    try:
        from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
        install_pipeline_routes(app, site_maps=site_maps, read_guard=read_guard)
    except ImportError:
        try:
            from fleet.server.pipeline_routes import install_pipeline_routes
            install_pipeline_routes(app, site_maps=site_maps, read_guard=read_guard)
        except ImportError:
            pass

    def fail(exc: SiteMapError) -> HTTPException:
        return site_map_error(exc.status_code, exc.code, str(exc))

    def judged_map() -> tuple[dict, str, object]:
        """The map a correction would touch: the draft when there is one, else the active map."""
        draft = site_maps.draft_view()
        if draft["map"] is not None:
            return draft["map"], "draft", draft["revision"]
        try:
            active = site_maps.active_view()
        except SiteMapError as exc:  # D-1010: a tampered active row is not judged
            raise fail(exc) from exc
        if active is None:
            raise site_map_error(404, "SITE_MAP_NO_MAP", "save or activate a site map first")
        return active["map"], "active", active["version"]

    def evidence(last_s: float, robot_id: Optional[str]) -> tuple[list, list[str], float, float]:
        """Driven tracks in the map frame from D-594 path history, newest points per robot."""
        recorder = paths()
        if recorder is None:
            raise site_map_error(503, "SITE_MAP_NO_PATH_HISTORY", "Fleet is not recording robot paths")
        if robot_id is not None and not recorder.knows(robot_id):
            raise site_map_error(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        until = recorder.wall()
        robots = [robot_id] if robot_id is not None else (
            recorder.robot_ids() if hasattr(recorder, "robot_ids") else sorted(set(recorder._roster()))
        )
        tracks = []
        for rid in robots:
            points, _ = recorder.store.query(rid, since=until - last_s, until=until)
            if len(points) >= 2:  # a single point has no lane to compare with
                tracks.append([[point["x"], point["y"]] for point in points])
        return tracks, robots, until - last_s, until

    def judge(last_s: float, robot_id: Optional[str], camera_lanes: Optional[list] = None
              ) -> tuple[dict, dict]:
        body, source, revision = judged_map()
        tracks, robots, since, until = evidence(last_s, robot_id)
        report = compare(SiteMap.model_validate(body), tracks, camera_lanes=camera_lanes)
        report["map"] = {"source": source, "revision": revision}
        report["evidence"] = {**report["evidence"], "robots": robots, "since": since, "until": until,
                              "limit": "newest 5000 points per robot"}
        return report, body

    @app.get("/api/fleet/site-map/profiles", dependencies=read_guard, tags=["site-map"])
    def site_map_profiles() -> dict:
        return {"profiles": site_maps.profiles()}

    @app.put("/api/fleet/site-map/profiles/{profile_id}", tags=["site-map"])
    async def site_map_save_profile(request: Request,
                                    profile_id: str = Path(pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
                                    principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            body = ProfileRequest.model_validate_json(await _bounded_body(request))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_INVALID",
                                                         "detail": {"errors": invalid_errors(exc)}}) from exc
        try:
            return site_maps.save_profile(profile_id, name=body.name, site_map=body.map,
                                          info=(MapProfileInfo(kind=body.kind, description=body.description,
                                                               soccer_field=body.soccer_field)
                                                if body.model_fields_set & {"kind", "description", "soccer_field"}
                                                else None),
                                          expected_revision=body.expected_revision,
                                          principal_id=principal.principal_id)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.get("/api/fleet/site-map/active", dependencies=read_guard, tags=["site-map"])
    def site_map_active() -> dict:
        try:
            view = site_maps.active_view()
        except SiteMapError as exc:  # D-1010: a tampered active row refuses, never a 500
            raise site_map_error(exc.status_code, exc.code, exc.args[0]) from exc
        if view is None:
            raise site_map_error(404, "SITE_MAP_NOT_ACTIVE")
        return view

    @app.get("/api/fleet/site-map/lane-graph-crosswalks", dependencies=read_guard, tags=["site-map"])
    def site_map_lane_graph_crosswalks() -> dict:
        """D-573 1: the import lane graph's crosswalks for the editor to merge into the draft."""
        source = site_maps.import_source
        if source is None:
            raise site_map_error(404, "SITE_MAP_NO_LANE_GRAPH", "no --site-map-import lane graph is configured")
        try:
            crosswalks = crosswalks_from_lane_graph(source)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
            raise site_map_error(422, "SITE_MAP_NO_LANE_GRAPH", f"the lane graph cannot be read: {type(exc).__name__}") from exc
        return {"source": source.name, "crosswalks": [c.model_dump(mode="json") for c in crosswalks]}

    @app.get("/api/fleet/site-map/draft", dependencies=read_guard, tags=["site-map"])
    def site_map_draft() -> dict:
        return site_maps.draft_view()

    @app.put("/api/fleet/site-map/draft", tags=["site-map"])
    async def site_map_save_draft(request: Request,
                                  principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            body = DraftRequest.model_validate_json(await _bounded_body(request))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_INVALID",
                                                         "detail": {"errors": invalid_errors(exc)}}) from exc
        try:
            return site_maps.save_draft(body.map, expected_revision=body.expected_revision,
                                        principal_id=principal.principal_id)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post("/api/fleet/site-map/activate", tags=["site-map"])
    async def site_map_activate(body: ActivateRequest,
                          principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return site_maps.activate(expected_revision=body.expected_revision,
                                      principal_id=principal.principal_id, route_active=route_active())
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post("/api/fleet/site-map/draft-from-camera", tags=["site-map"])
    async def site_map_camera_draft(request: Request,
                                    principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """Vision's draft-map candidates as a save-ready draft body; nothing is written."""
        try:
            body = CameraDraftRequest.model_validate_json(await _bounded_body(request))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_CAMERA_INVALID",
                                                         "detail": {"errors": invalid_errors(exc)}}) from exc
        try:
            return camera_draft(body)
        except CameraDraftError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_CAMERA_INVALID",
                                                         "detail": {"message": str(exc)}}) from exc

    @app.get("/api/fleet/site-map/reality-check", dependencies=read_guard, tags=["site-map"])
    def site_map_reality_check(last_s: float = Query(DEFAULT_WINDOW_S, gt=0, le=MAX_WINDOW_S),
                               robot_id: Optional[str] = Query(None, min_length=1, max_length=64)) -> dict:
        """Does the map match where robots actually drove (D-594 path history)? Reads only."""
        report, _ = judge(last_s, robot_id)
        return report

    @app.post("/api/fleet/site-map/reality-check", dependencies=read_guard, tags=["site-map"])
    async def site_map_reality_check_with_camera(request: Request) -> dict:
        """The same check with the camera as a second witness (Vision's draft-map lanes).

        The browser fetched the candidates from Vision with a Fleet-issued lease (the D-375
        pattern) and posts them here; the report's ``camera`` verdict says whose word is the
        odd one out among map·camera·drive. Reads only.
        """
        try:
            body = RealityCheckRequest.model_validate_json(await _bounded_body(request))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_INVALID",
                                                         "detail": {"errors": invalid_errors(exc)}}) from exc
        report, _ = judge(body.last_s, body.robot_id, body.camera_lanes)
        return report

    @app.post("/api/fleet/site-map/reality-check/apply", tags=["site-map"])
    def site_map_reality_apply(body: RealityApplyRequest,
                               principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """Move the draft onto the driven track. The fit is recomputed here, never sent by the browser."""
        draft = site_maps.draft_view()
        if draft["map"] is None:
            raise site_map_error(409, "SITE_MAP_NO_DRAFT", "save the draft to correct first")
        if draft["revision"] != body.expected_revision:
            raise site_map_error(409, "SITE_MAP_DRAFT_CHANGED", "another operator changed the draft; reload first")
        report, _ = judge(body.last_s, body.robot_id, body.camera_lanes)
        camera = report.get("camera") or {}
        if camera.get("verdict") == "drive_outlier":
            raise site_map_error(409, "SITE_MAP_NO_CORRECTION",
                                 f"{camera.get('reason')} (the camera agrees with the map; "
                                 "check the drive recording instead of moving the map)")
        fit = report["fit"] or {}                      # None when the window had no drive at all
        if not fit.get("accepted"):
            raise site_map_error(409, "SITE_MAP_NO_CORRECTION",
                                 fit.get("reason") or "; ".join(report["notes"]))
        try:
            corrected = SiteMap.model_validate(transform_map(draft["map"], fit))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_INVALID",
                                                         "detail": {"errors": invalid_errors(exc)}}) from exc
        try:
            view = site_maps.save_draft(corrected, expected_revision=body.expected_revision,
                                        principal_id=principal.principal_id)
        except SiteMapError as exc:
            raise fail(exc) from exc
        site_maps.record_event("reality_corrected", principal.principal_id,
                               {"from_revision": body.expected_revision, "revision": view["revision"],
                                "fit": fit, "verdict": report["verdict"],
                                "evidence": report["evidence"]})
        return {"draft": view, "report": report}
