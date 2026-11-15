"""Mission, proposal, audit and claim owners share one durable host journal."""

from pathlib import Path


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


def validate_model_turn_worker(mission_model_turn_worker, mission_model_turn_scheduler, mission_model_turn_store,
                               post_action_observation_source) -> None:
    """An injected model-turn worker and post-action observation source must fit the configured Mission services."""
    if mission_model_turn_worker is not None:
        worker_store = getattr(mission_model_turn_worker, "store", None)
        consume_next = getattr(mission_model_turn_worker, "consume_next", None)
        if mission_model_turn_scheduler is None:
            raise ValueError("Mission model-turn worker requires persistent Mission services")
        if (worker_store is None or not callable(consume_next)
                or Path(worker_store.path).resolve() != Path(mission_model_turn_store.path).resolve()):
            raise ValueError("Mission model-turn worker must consume the configured shared SQLite outbox")
    if post_action_observation_source is not None:
        if mission_model_turn_worker is None:
            raise ValueError("post-action observation source requires an injected Mission model-turn worker")
        tool_dispatcher = getattr(mission_model_turn_worker, "dispatcher", None)
        if not hasattr(tool_dispatcher, "post_action_observation_source"):
            raise ValueError("Mission model-turn worker must use the Fleet feedback tool dispatcher")
        configured_source = tool_dispatcher.post_action_observation_source
        if configured_source is not None and configured_source is not post_action_observation_source:
            raise ValueError("Mission worker and app must share one post-action observation source")
        tool_dispatcher.post_action_observation_source = post_action_observation_source
