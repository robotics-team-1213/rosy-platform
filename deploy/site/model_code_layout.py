"""Allowlisted signed payload layout and retained import identities."""

PREFIX = "tools/perception/"
LEARNING_CODE_PREFIXES = ("learning/curation/perception/", "learning/registry/perception/",
                          "learning/training/perception/", "learning/evaluation/perception/", PREFIX)
LEGACY_LEARNING_PREFIXES = ("learning/training/perception/", "tools/perception/")
LEARNING_REQUIRED = ("learning/registry/perception/watch.py", PREFIX + "rosy_ml.py",
                     PREFIX + "operator_ssh.py", "learning/registry/perception/store.py",
                     "learning/curation/perception/review_app.py",
                     "learning/curation/perception/review_store.py",
                     "learning/curation/perception/sim_web.py",
                     "learning/curation/perception/review_app_web/sim.html",
                     "learning/curation/perception/review_app_web/sim.js",
                     "learning/curation/perception/vlm_judge.py",
                     "learning/curation/perception/vlm_judge_web.py",
                     "learning/curation/perception/review_app_web/vlm.html",
                     "learning/curation/perception/review_app_web/vlm.js",
                     "learning/curation/perception/review_app_web/vlm.css",
                     "learning/training/perception/train_job.py",
                     "learning/evaluation/perception/road_replay.py",
                     "learning/curation/perception/classes/lane_lr5.yaml",
                     "learning/curation/perception/classes/lane_lr6_drivable.yaml",
                     "learning/curation/perception/classes/object_review_obstacle_v1.yaml",
                     "learning/curation/perception/review_app_web/index.html",
                     "learning/curation/perception/review_app_web/pixels.html")
CAMERA_PROFILE = "middleware/devices/pinky/profile/config/camera_nominal.yaml"
CAMERA_MAP_FILES = tuple("operations/overhead/rosy_vision/" + name
                         for name in ("__init__.py", "lane_map.py", "map_register.py"))
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
JOB_ENTRY_POINTS.update({'training/' + name: 'learning/training/perception/' + name
                         for name in ('capture_goal.py', 'check_manifest.py', 'drivable_head.py',
                             'export_cell.py', 'gen_notebook.py', 'handover.py', 'job_state.py',
                             'learning_cycle.py', 'recipes.py', 'recording_job.py', 'review_admission.py',
                             'review_authority.py', 'review_bridge.py', 'review_dataset.py',
                             'review_eval_companion.py', 'review_eval_package.py', 'review_migration.py',
                             'review_pipeline.py', 'review_provenance.py', 'rosy_lane_model.py',
                             'run_log.py', 'train_job.py',)})
JOB_ENTRY_POINTS.update({'road_replay.py': 'learning/evaluation/perception/road_replay.py', 'road_replay_inputs.py': 'learning/evaluation/perception/road_replay_inputs.py', 'road_replay_metrics.py': 'learning/evaluation/perception/road_replay_metrics.py', 'store.py': 'learning/registry/perception/store.py'})
CAMERA_MAP_ENTRY = JOB_ENTRY_POINTS["camera_lane_map.py"]
SPLIT_CODE_PREFIXES = ("middleware/perception/nodes/", "middleware/perception/localization/",
                       "middleware/perception/graph_health/", "middleware/perception/snapshots/",
                       "middleware/perception/sensors/", "middleware/perception/front_camera/",
                       "middleware/perception/package.xml",
                       *("middleware/drive/" + name + "/" for name in
                         ("motion_limits", "recovery", "tracking", "calibration", "planning/grid", "runtime")))
SPLIT_REQUIRED = (
                  'middleware/perception/nodes/calib_node.py',
                  'middleware/perception/nodes/calibrated_values.py',
                  'middleware/perception/nodes/calibration_atomic.py',
                  'middleware/perception/nodes/calibration_camera.py',
                  'middleware/perception/nodes/calibration_lock.py',
                  'middleware/perception/nodes/calibration_record.py',
                  'middleware/perception/nodes/calibration_relocation.py',
                  'middleware/perception/nodes/calibration_rotation.py',
                  'middleware/perception/nodes/calibration_sequence.py',
                  'middleware/perception/nodes/calibration_snapshot.py',
                  'middleware/perception/nodes/calibration_storage.py',
                  'middleware/perception/nodes/camera_detect_node.py',
                  'middleware/perception/nodes/camera_lock.py',
                  'middleware/perception/nodes/camera_region_range.py',
                  'middleware/perception/nodes/dock_observer_node.py',
                  'middleware/perception/nodes/executor_choice.py',
                  'middleware/perception/nodes/goal_escape.py',
                  'middleware/perception/nodes/ir_adc_node.py',
                  'middleware/perception/nodes/learned_lane_node.py',
                  'middleware/perception/nodes/obstacle_observer_node.py',
                  'middleware/perception/nodes/pilot_recorder_node.py',
                  'middleware/perception/nodes/pilot_recording.py',
                  'middleware/perception/nodes/record_session.py',
                  'middleware/perception/nodes/recording.py',
                  'middleware/perception/nodes/road_observer_node.py',
                  'middleware/perception/nodes/road_state_node.py',
                  'middleware/perception/nodes/sensor_provider.py',
                  'middleware/perception/nodes/startup_calibration_node.py',
                  'middleware/perception/nodes/tf_buffer.py',
                  'middleware/perception/nodes/web_http.py',
                  'middleware/perception/nodes/web_map_control.py',
                  'middleware/perception/nodes/web_node.py',
                  'middleware/perception/nodes/web_render.py',
                  'middleware/perception/nodes/web_state.py',

                  'middleware/perception/localization/loc_assist.py',
                  'middleware/perception/localization/loc_assist_node.py',
                  'middleware/perception/localization/localization_node.py',
                  'middleware/perception/graph_health/watch.py',
                  'middleware/perception/graph_health/watch_node.py',
                  'middleware/perception/front_camera/object_observation/object_detector.py',
                  'middleware/perception/front_camera/object_observation/object_detector_node.py',
                  'middleware/perception/sensors/line_observation/ir_overlay.py',
                  'middleware/perception/sensors/line_observation/line_observer_overrides.py',
                  'middleware/perception/sensors/line_observation/core_law_input.py',
                  'middleware/perception/sensors/line_observation/route_context_input.py',
                  'middleware/perception/sensors/line_observation/route_followers.py',
                  'middleware/perception/sensors/line_observation/line_observer_node.py',
                  'middleware/perception/snapshots/capture_trigger.py',
                  'middleware/perception/snapshots/capture_trigger_node.py',
                  "middleware/perception/package.xml",
                  "middleware/perception/sensors/sensing/__init__.py",
                  "middleware/perception/front_camera/perception/__init__.py",
                  "middleware/drive/motion_limits/command_gate.py",
                  "middleware/drive/recovery/recover.py",
                  "middleware/drive/tracking/path_follow.py",
                  "middleware/drive/calibration/modes.py",
                  "middleware/drive/planning/grid/__init__.py",
                  "middleware/drive/runtime/control_node.py",
                  "middleware/drive/motion_limits/adapter/__init__.py",
                  "middleware/drive/tracking/wander/__init__.py")
FITNESS_ENTRY = "learning/evaluation/perception/road_fitness_replay.py"
FITNESS_CONTRACT_FILES = ("contracts/foundation/core_common/observation.py",)
OMX_REVIEW_FILES = (
    *("learning/curation/omx/" + name for name in
      ("native_review.py", "native_capture.py", "native_environment.py", "native_segments.py", "omx_output_paths.py")),
    *("contracts/learning/src/rosy/contracts/learning/" + name for name in
      ("__init__.py", "omx.py", "artifacts.py", "png.py", "camera_setup.py", "action_space.py")))
CODE_PREFIXES = (*LEARNING_CODE_PREFIXES, "middleware/perception/control/", "contracts/foundation/core_common/",
                 "shared/web/", "tools/data_paths.py", CAMERA_PROFILE, *CAMERA_MAP_FILES, *SPLIT_CODE_PREFIXES,
                 *OMX_REVIEW_FILES)
# Observe enrolled pre-migration checkouts too; new signed archives stay canonical.
CHECKOUT_PREFIXES = CODE_PREFIXES + (*LEGACY_LEARNING_PREFIXES, "src/runtime/sensing/control/",
                                    "src/contracts/foundation/core_common/")
LIMIT = 512 * 1024 * 1024
FORBIDDEN = {"data", "private", "runs", "scratch", "checkpoints", "store", ".git", ".venv", "__pycache__", "secrets"}
IMPORT_PATHS = tuple(p.rstrip("/") for p in LEARNING_CODE_PREFIXES) + (
                "middleware/perception", "contracts/foundation", "operations/overhead",
                *(prefix + name for prefix in LEGACY_LEARNING_PREFIXES for name in ("model", "dataset", "training")),
                "src/runtime/sensing", "src/contracts/foundation")
PATH_SETUP = ("import pathlib,sys,runpy;root=pathlib.Path(sys.argv.pop(1)).resolve();"
              f"sys.path[:0]=[str(root/p) for p in {IMPORT_PATHS!r}]")

