"""Exact signed model-job paths, including retained release layouts."""
from pathlib import Path

PREFIX = "tools/perception/"
LEGACY_LEARNING_PREFIXES = ("learning/training/perception/", "tools/perception/")

#: D-497: job names whose entry point is a signed file outside PREFIX. Exact name only;
#: aliases retain existing job names while resolving to exact signed canonical files.
JOB_ENTRY_POINTS = {"camera_lane_map.py": "operations/overhead/rosy_vision/lane_map.py"}
JOB_ENTRY_POINTS.update({'dataset/' + name: 'learning/curation/perception/' + name
                         for name in ('autolabel.py', 'bag_to_video.py', 'build.py', 'catalog.py',
                             'ceiling_pose.py', 'class_sets.py', 'clip_lane_draft.py', 'edge_capture.py',
                             'edge_capture_session.py', 'edge_review.py', 'edge_review_return.py',
                             'extract.py', 'fetch_http.py', 'frames.py', 'geometry.py', 'harvest.py',
                             'incident_feedback.py', 'labels.py', 'lane_derived_drivable.py',
                             'lane_failure.py', 'lane_failure_loop.py', 'learning_workspace.py',
                             'map_projected_drivable.py', 'mcap_proof.py', 'media_pipeline.py', 'object_boxes.py',
                             'pixel_label_job.py', 'prelabel.py', 'publish.py', 'qwen_points.py',
                             'qwen_review_completion.py', 'reclaim.py', 'review_app.py', 'review_eval_bootstrap.py',
                             'review_evidence.py', 'review_ingest.py', 'review_masks.py', 'review_pack.py',
                             'review_quality.py', 'review_return.py', 'road_draft.py', 'sam3_road_draft.py',
                             'shrink_session.py', 'stuck_markers.py', 'vision_review_drafts.py',
                             'vlm_mask_feedback.py',)})
JOB_ENTRY_POINTS.update({'model/' + name: 'learning/registry/perception/' + name
                         for name in ('bench_backends.py', 'compare_backends.py', 'convert.py', 'deliver.py',
                             'delivery_journal.py', 'drivable_versions.py', 'export_class_names.py',
                             'export_ncnn.py', 'export_ncnn_lane.py', 'export_onnx.py', 'intake.py',
                             'intake_eval_gate.py', 'peer_targets.py', 'sign_model.py', 'slot_cli.py',
                             'watch.py', 'watch_core.py',)})
JOB_ENTRY_POINTS['model/intake_eval_gate.py'] = 'learning/evaluation/perception/intake_eval_gate.py'
JOB_ENTRY_POINTS.update({'training/' + name: 'learning/training/perception/' + name
                         for name in ('capture_goal.py', 'check_manifest.py', 'drivable_head.py', 'export_cell.py',
                             'gen_notebook.py', 'handover.py', 'job_state.py', 'learning_cycle.py', 'recipes.py',
                             'recording_job.py', 'review_admission.py', 'review_migration.py', 'review_pipeline.py',
                             'rosy_lane_model.py', 'run_log.py', 'train_job.py',)})
JOB_ENTRY_POINTS.update({'training/' + name: 'learning/curation/perception/' + name
                         for name in ('review_authority.py', 'review_bridge.py', 'review_dataset.py',
                             'review_eval_companion.py', 'review_eval_package.py', 'review_provenance.py')})
JOB_ENTRY_POINTS.update({'road_replay.py': 'learning/evaluation/perception/road_replay.py', 'road_replay_inputs.py': 'learning/evaluation/perception/road_replay_inputs.py', 'road_replay_metrics.py': 'learning/evaluation/perception/road_replay_metrics.py', 'store.py': 'learning/registry/perception/store.py'})
CAMERA_MAP_ENTRY = JOB_ENTRY_POINTS["camera_lane_map.py"]


def job_entry(source, script):
    """(entry file, conflict base, conflict name, mapped path or None) for a job name.

    A JOB_ENTRY_POINTS name resolves to exactly its one signed file; any other name
    only under the CLI holder PREFIX. '../', absolute and symlinked escapes raise ValueError."""
    source = Path(source).resolve(strict=True)
    # Existing signed releases retain their original bytes, paths and job names.
    # New candidates require LEARNING_REQUIRED; this only resolves a retained release.
    if script != "camera_lane_map.py" and not (source / "learning/registry/perception/watch.py").is_file():
        for prefix in LEGACY_LEARNING_PREFIXES:
            perception = source / prefix
            if (perception / "model/watch.py").is_file():
                file = (perception / script).resolve(strict=True)
                file.relative_to(perception)
                return file, perception, script, None
    mapped = JOB_ENTRY_POINTS.get(script) if isinstance(script, str) else None
    if mapped and (script.startswith("training/") or script == "model/intake_eval_gate.py"):
        current = source / mapped
        if not current.exists() and not current.is_symlink():
            holder = "training" if script.startswith("training/") else "registry"
            mapped = f"learning/{holder}/perception/{current.name}"
    perception, name = (source, mapped) if mapped is not None else (source / PREFIX, script)
    file = (perception / name).resolve(strict=True)
    if file.relative_to(perception) != Path(name) and mapped is not None:
        raise ValueError("job entry point is not its mapped file")
    return file, perception, name, mapped
