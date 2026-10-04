"""Cell workspace composition: documents and canonical preview, never admission."""

from fastapi import Depends, HTTPException

from core_common.protocol.schemas import (
    CellAppCompileRequest, CellAppDocumentSaveRequest, CellAppProposalRequest,
)
from fleet.server.cell_app_store import CellAppStore, DocumentChanged
from fleet.server.mission_routes import MissionCandidateRequest


def install_cell_app_routes(app, *, mission_service, compiler, service_id, principals,
                            proposal_create, proposal_resolve, require_viewer, require_named_operator):
    service_principal = None
    if service_id is not None:
        service_principal = next((principal for principal in principals.values()
                                  if principal.principal_id == service_id and principal.role == "service"), None)
        if service_principal is None or compiler is None:
            raise ValueError("Cell app requires a configured service principal and Cell Job compiler")
    store = CellAppStore(mission_service.store.path) if mission_service is not None else None

    def unavailable():
        if store is None or compiler is None:
            raise HTTPException(503, detail={"code": "CELL_APP_UNCONFIGURED"})

    def read(kind, identifier, expected=None):
        unavailable()
        try:
            document = store.get(kind, identifier)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "CELL_APP_DOCUMENT_INVALID", "message": str(exc)}) from exc
        if document is None:
            raise HTTPException(404, detail={"code": "CELL_APP_DOCUMENT_NOT_FOUND"})
        if expected is not None and document["digest"] != expected:
            raise HTTPException(409, detail={"code": "CELL_APP_DOCUMENT_CHANGED"})
        return document

    def compile_documents(body):
        recipe = read("recipe", body.recipe_id, body.recipe_digest)["document"]
        cell = read("cell", body.cell_id, body.cell_digest)["document"]
        try:
            compilation = compiler.compile(recipe, cell)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, detail={"code": "CELL_APP_COMPILE_INVALID", "message": str(exc),
                                             "problems": list(getattr(exc, "problems", ()))}) from exc
        bundle = compilation.plan_bundle
        candidate = {"kind": "cell_job", "recipe": recipe, "cell": cell,
                     "recipe_sha256": bundle.recipe_digest, "cell_sha256": bundle.cell_digest,
                     "job": dict(compilation.job)}
        return {"candidate": candidate, "process_artifact_digest": bundle.process_artifact_digest,
                "summary": {"transfer_count": len(bundle.steps),
                            "pallet_markers": list(compilation.ledger_markers)}}

    @app.get("/api/fleet/cell-app/documents", dependencies=[Depends(require_viewer)])
    def documents():
        unavailable()
        return {"documents": store.list()}

    @app.get("/api/fleet/cell-app/documents/{kind}/{identifier}", dependencies=[Depends(require_viewer)])
    def document_read(kind: str, identifier: str):
        return read(kind, identifier)

    @app.post("/api/fleet/cell-app/documents/{kind}/{identifier}",
              dependencies=[Depends(require_named_operator)])
    def document_save(kind: str, identifier: str, body: CellAppDocumentSaveRequest):
        unavailable()
        try:
            return store.save(kind, identifier, body.document, expected_digest=body.expected_digest)
        except DocumentChanged as exc:
            raise HTTPException(409, detail={"code": "CELL_APP_DOCUMENT_CHANGED", "message": str(exc)}) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail={"code": "CELL_APP_DOCUMENT_INVALID", "message": str(exc)}) from exc

    @app.post("/api/fleet/cell-app/compile", dependencies=[Depends(require_named_operator)])
    def document_compile(body: CellAppCompileRequest):
        return compile_documents(body)

    @app.post("/api/fleet/cell-app/proposals", dependencies=[Depends(require_named_operator)])
    def propose(body: CellAppProposalRequest):
        if service_principal is None or proposal_create is None or proposal_resolve is None:
            raise HTTPException(503, detail={"code": "CELL_APP_UNCONFIGURED"})
        compiled = compile_documents(body)
        # Reuse exactly the service-only proposal path. The operator's initiating
        # HTTP request is audited; Fleet persists the configured service author.
        result = proposal_create(MissionCandidateRequest(
            request_key=body.request_key, workcell_id=body.workcell_id,
            instance_id=body.instance_id, candidate=compiled["candidate"],
        ), principal=service_principal)
        return proposal_resolve(result["proposal"]["proposal_id"], principal=service_principal)
