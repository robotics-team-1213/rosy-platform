"""Mission, proposal, audit and claim owners share one durable host journal."""


def configure_mission_storage(task_service, mission_service, proposal_store, goal_evidence_service,
                              candidate_resolver, cell_job_compiler):
    configured = mission_service is not None or proposal_store is not None
    if (mission_service is None) != (proposal_store is None):
        raise ValueError("Mission API requires both MissionService and ProposalStore")
    if candidate_resolver is not None and not configured:
        raise ValueError("Mission candidate resolver requires MissionService and ProposalStore")
    if candidate_resolver is not None and not callable(candidate_resolver):
        raise ValueError("Mission candidate resolver must be callable")
    if cell_job_compiler is not None and not configured:
        raise ValueError("Cell Job compiler requires the persistent Mission API")
    if cell_job_compiler is not None and not callable(getattr(cell_job_compiler, "compile", None)):
        raise ValueError("Cell Job compiler must implement compile(recipe, cell)")
    if goal_evidence_service is not None and not configured:
        raise ValueError("goal evidence requires the persistent Mission API")
    if goal_evidence_service is not None and goal_evidence_service.missions is not mission_service:
        raise ValueError("goal evidence service must use the configured MissionService")
    if configured and task_service is None:
        raise ValueError("Mission API requires persistent API audit and dispatch-control storage")
    if configured:
        validate_mission_storage(task_service, mission_service, proposal_store, goal_evidence_service)
    return configured


def validate_mission_storage(task_service, mission_service, proposal_store, goal_evidence_service):
    database_paths = {
        task_service.store.path.resolve(), mission_service.store.path.resolve(),
        proposal_store.path.resolve(),
    }
    if goal_evidence_service is not None:
        database_paths.add(goal_evidence_service.store.path.resolve())
    if len(database_paths) != 1:
        raise ValueError("Mission, proposal, audit, and resource claims must share one SQLite database")
