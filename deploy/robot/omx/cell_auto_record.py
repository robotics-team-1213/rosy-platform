"""Ledger rows around one real carry, split from cell_auto_pick; executor choice lives in cell_executor."""


def capture_problem(config, source, dest, moved) -> None:
    try:
        import cell_problem_pipeline

        cell_problem_pipeline.capture_from_attempt(config, {
            "from": source, "dest": dest, "result": moved["result"], "fail_stage": moved.get("at"),
            "why": moved.get("error"), "grasp_debate": moved.get("grasp_debate"), "wrist": moved.get("wrist")})
    except Exception:
        pass
