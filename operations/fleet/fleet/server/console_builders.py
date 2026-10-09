"""Lazy, feature-local console construction; CLI keeps startup refusals and lifecycle."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def build_mission_services(*, mission_api, tasks_db, goal_evidence_config, cell_job_tol_m):
    mission_service = None
    proposal_store = None
    goal_evidence_service = None
    cell_job_compiler = None
    if cell_job_tol_m is not None:  # the palletizing wheel is needed only with this flag
        from fleet.server.cell_compiler import PalletizingCellJobCompiler
        cell_job_compiler = PalletizingCellJobCompiler(tol_m=cell_job_tol_m)
    if mission_api:
        from fleet.server.mission_service import MissionService
        from fleet.server.mission_store import MissionStore
        from fleet.server.proposal_store import ProposalStore

        mission_service = MissionService(MissionStore(tasks_db))
        proposal_store = ProposalStore(tasks_db)
        if goal_evidence_config is not None:
            from fleet.server.goal_evidence_registry import load_goal_evidence_registry
            from fleet.server.goal_evidence_service import GoalEvidenceService
            from fleet.server.goal_evidence_store import GoalEvidenceStore

            registry = load_goal_evidence_registry(goal_evidence_config)
            goal_evidence_service = GoalEvidenceService(
                mission_service, registry, GoalEvidenceStore(tasks_db),
            )
    return mission_service, proposal_store, goal_evidence_service, cell_job_compiler


def build_pairing(args: argparse.Namespace, *, tls_cert, tasks_db, sighting_service, site_name):
    """D-341 2: pairing exists only on a TLS Fleet with a site CA and a durable store."""
    pairing_ca = getattr(args, "pairing_ca", None)
    sync_env = getattr(args, "pairing_sync_token_env", None)
    if pairing_ca is None:
        if sync_env is not None:
            sys.exit("--pairing-sync-token-env requires --pairing-ca")
        return None, None
    if tls_cert is None:
        sys.exit("--pairing-ca requires --tls-cert: pairing routes exist only over TLS (D-341 2)")
    if tasks_db is None:
        sys.exit("--pairing-ca requires --tasks-db for credential digests and the pairing audit")
    tls_host = getattr(args, "pairing_tls_host", None)
    if not tls_host:
        sys.exit("--pairing-ca requires --pairing-tls-host (the <name>.local in the site certificate)")
    from core_common.protocol.pairing import der_sha256
    from fleet.server.pairing import PairingService
    from fleet.server.pairing_store import PairingStore

    sources = ({source.source_id: source.credential for source in sighting_service.sources}
               if sighting_service is not None else {})
    if "paired" not in sources.values():
        print("warning: D-341 pairing is on but no sighting source is credential: paired; "
              "requests can be listed but not approved", file=sys.stderr)
    try:
        served_leaf_pem = Path(tls_cert).read_text(encoding="utf-8-sig")
        leaf_sha256 = der_sha256(served_leaf_pem)
        site_ca_pem = Path(pairing_ca).read_text(encoding="utf-8-sig")
        service = PairingService(PairingStore(tasks_db), leaf_cert_sha256=leaf_sha256,
                                 site_ca_pem=site_ca_pem, tls_host=tls_host,
                                 site_name=site_name, sources=sources, served_leaf_pem=served_leaf_pem)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        sys.exit(f"D-341 pairing configuration refused: {exc}")
    sync_token = None
    if sync_env is not None:
        sync_token = os.environ.get(sync_env)
        if not sync_token:
            sys.exit(f"pairing sync token environment variable {sync_env} is required")
    return service, sync_token


def build_enrollment(*, console, task_service, sighting_service, enrollment_store,
                     robot_key, robot_key_error, discovery, tls_file, hub_link=None):
    from fleet.server.enrollment import EnrollmentService
    from fleet.server.roster import SiteRoster

    roster = SiteRoster(console, task_service=task_service, sightings=sighting_service)
    from fleet.server.enrollment_tls import EnrolledTlsBindings
    enrollment = EnrollmentService(enrollment_store, roster, key=robot_key,
                                   key_error=robot_key_error,
                                   fleet_name=console.fleet_name, discovery=discovery,
                                   tls_bindings=EnrolledTlsBindings(tls_file, enrollment_store) if tls_file else None,
                                   hub_link=hub_link)
    enrollment.load()
    roster.sync()
    return enrollment, roster
