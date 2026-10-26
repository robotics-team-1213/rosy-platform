-- Pre-D-856 parent schema, captured from commit ab4f12f12b.
CREATE TABLE IF NOT EXISTS fleet_component_migrations (
                    component TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY(component, version)
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_jobs (
                    mission_id TEXT PRIMARY KEY,
                    proposal_principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    recipe_digest TEXT NOT NULL,
                    cell_digest TEXT NOT NULL,
                    process_artifact_digest TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    ledger_markers_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                        'GOAL_CONFIRMED', 'HOLD'
                    )),
                    current_step_index INTEGER NOT NULL DEFAULT 0 CHECK(current_step_index >= 0),
                    authority_epoch INTEGER,
                    dispatch_generation INTEGER,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
                    step_index INTEGER,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
