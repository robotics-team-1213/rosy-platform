"""Mission, proposal, audit and claim owners share one durable host journal."""


def validate_mission_storage(task_service, mission_service, proposal_store, goal_evidence_service):
    database_paths = {
        task_service.store.path.resolve(), mission_service.store.path.resolve(),
        proposal_store.path.resolve(),
    }
    if goal_evidence_service is not None:
        database_paths.add(goal_evidence_service.store.path.resolve())
    if len(database_paths) != 1:
        raise ValueError("Mission, proposal, audit, and resource claims must share one SQLite database")
