"""Cell workspace composition: documents and canonical preview, never admission.

A recipe/3 document previews through ``compile_mixed`` (D-781 §5): the candidate envelope is the
same, and ``summary.multi_arm`` lists the arms and each step's placement. recipe/1-2 previews have
no ``multi_arm`` key and are unchanged.
"""

import base64
import os

from fastapi import Depends, HTTPException

from core_common.protocol.schemas import (
    CellAppCompileRequest, CellAppDocumentSaveRequest, CellAppProposalRequest,
)
from fleet.server.cell_app_store import CellAppStore, DocumentChanged
from fleet.server.cell_mixed_submission import MixedCellCompilation, is_mixed
from fleet.server.mission_routes import MissionCandidateRequest


def mixed_preview(compiler, recipe, cell):
    """recipe/3 (D-781): the same candidate envelope, previewed as a multi-arm Job (arms and each
    step's sku, arm, alternates, zone, coupling and depends_on). No ledger, claim or grant."""
    if not callable(getattr(compiler, "compile_mixed", None)):
        raise ValueError("the process compiler does not compile recipe/3")
    compiled = compiler.compile_mixed(recipe, cell)
    if not isinstance(compiled, MixedCellCompilation):
        raise ValueError("process compiler returned an unsupported mixed compilation")
    skus = [step["sku"] for step in compiled.job["plan"]["steps"]]
    steps = [{"index": index, "sku": skus[index], **{key: step["placement"][key] for key in (
        "arm", "alternates", "zone", "coupling", "depends_on")}} for index, step in enumerate(compiled.steps)]
    candidate = {"kind": "cell_job", "recipe": recipe, "cell": cell, "recipe_sha256": compiled.recipe_digest,
                 "cell_sha256": compiled.cell_digest, "job": dict(compiled.job)}
    return {"candidate": candidate, "process_artifact_digest": compiled.process_artifact_digest,
            "summary": {"transfer_count": len(steps), "pallet_markers": [dict(m) for m in compiled.ledger_markers],
                        "multi_arm": {"arms": [dict(arm) for arm in compiled.arms], "steps": steps}}}


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
            if is_mixed({"recipe": recipe}):
                return mixed_preview(compiler, recipe, cell)
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

    @app.get("/api/fleet/cell-app/print-sheets/{kind}", dependencies=[Depends(require_viewer)])
    def print_sheet(kind: str, ids: str = "35", sizes_mm: str = "20,25", cols: int = 8, rows: int = 6,
                    square_mm: float = 15.0, arm: int = 1):
        """A real-size calibration sheet (gripper or one arm slot's markers, checkerboard, ChArUco) as base64 PDF."""
        from fleet.server.cell_print_sheets import sheet

        try:
            name, pdf = sheet(kind, ids=[int(v) for v in ids.split(",") if v.strip()],
                              sizes_mm=[float(v) for v in sizes_mm.split(",") if v.strip()],
                              cols=cols, rows=rows, square_mm=square_mm, arm=arm)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "CELL_PRINT_SHEET_INVALID", "message": str(exc)}) from exc
        return {"filename": name, "media_type": "application/pdf", "pdf_base64": base64.b64encode(pdf).decode()}

    @app.get("/api/fleet/cell-app/object-catalog", dependencies=[Depends(require_viewer)])
    def object_catalog():
        """The arm's object catalogue with measured masses (D-934, D-935); read only, from this host's file."""
        from fleet.server.cell_object_catalog import ENV, view

        path = os.environ.get(ENV)
        try:
            if not path:
                raise OSError(f"{ENV} is not set")
            return view(path)
        except OSError as exc:
            raise HTTPException(503, detail={"code": "CELL_OBJECT_CATALOG_UNAVAILABLE", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "CELL_OBJECT_CATALOG_INVALID", "message": str(exc)}) from exc

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

    return propose
