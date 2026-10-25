"""Signed model-code path inventory; imported by the installed controller."""
from model_code_jobs import PREFIX, LEGACY_LEARNING_PREFIXES
LEARNING_CODE_PREFIXES = ("learning/curation/perception/", "learning/registry/perception/",
                          "learning/training/perception/", "learning/evaluation/perception/",
                          "learning/curation/omx/", "learning/training/omx/", PREFIX)
LEARNING_REQUIRED = ("learning/registry/perception/watch.py", PREFIX + "rosy_ml.py",
                     PREFIX + "operator_ssh.py", "learning/registry/perception/store.py",
                     "learning/curation/perception/review_app.py",
                     "learning/training/perception/train_job.py",
                     "learning/evaluation/perception/road_replay.py",
                     "learning/curation/perception/classes/lane_lr5.yaml",
                     "learning/curation/perception/classes/lane_lr6_drivable.yaml",
                     "learning/curation/perception/classes/object_review_obstacle_v1.yaml",
                     "learning/curation/perception/review_app_web/index.html",
                     "learning/curation/perception/review_app_web/pixels.html",
                     *("learning/curation/perception/" + name for name in
                       ("omx_web.py", "omx_center_web.py", "camera_setup.py", "camera_setup_web.py",
                        "learning_pipeline.py", "learning_tasks.py", "learning_tasks_web.py",
                        "review_app_web/tasks.html", "review_app_web/tasks.js",
                        "review_app_web/omx.html", "review_app_web/omx.js",
                        "review_app_web/omx-review.js", "review_app_web/omx-profiles.js",
                        "review_app_web/camera.html", "review_app_web/camera.js")),
                     *("learning/curation/omx/" + name for name in
                       ("native_review.py", "native_capture.py", "native_environment.py", "native_segments.py",
                        "collection_intake.py", "collection_pipeline.py", "camera_reference.py")),
                     "learning/training/omx/native_cycle.py",
                     *("learning/training/omx/experiment_" + name + ".py" for name in
                       ("artifact", "catalog", "center", "dataset", "evaluation", "export", "inbox", "io",
                        "jobs", "native", "online", "owner_status", "preview", "process", "profile",
                        "profiles", "reviews", "scope", "smoke", "train", "transfer")),
                     *("contracts/learning/src/rosy/contracts/learning/" + name for name in
                       ("__init__.py", "artifacts.py", "digest.py", "omx.py", "png.py", "camera_setup.py")))
CAMERA_PROFILE = "middleware/devices/pinky/profile/config/camera_nominal.yaml"
CAMERA_MAP_FILES = tuple("operations/overhead/rosy_vision/" + name
                         for name in ("__init__.py", "lane_map.py", "map_register.py"))
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
                  'middleware/drive/runtime/goal_escape.py',
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
CODE_PREFIXES = (*LEARNING_CODE_PREFIXES, "middleware/perception/control/", "contracts/foundation/core_common/",
                 "contracts/learning/src/", "shared/web/", CAMERA_PROFILE, *CAMERA_MAP_FILES, *SPLIT_CODE_PREFIXES)
# Observe enrolled pre-migration checkouts too; new signed archives stay canonical.
CHECKOUT_PREFIXES = CODE_PREFIXES + (*LEGACY_LEARNING_PREFIXES, "src/runtime/sensing/control/",
                                    "src/contracts/foundation/core_common/")
LIMIT = 512 * 1024 * 1024
FORBIDDEN = {"data", "private", "runs", "scratch", "checkpoints", "store", ".git", ".venv", "__pycache__", "secrets"}
IMPORT_PATHS = tuple(p.rstrip("/") for p in LEARNING_CODE_PREFIXES) + (
                "middleware/perception", "contracts/foundation", "contracts/learning/src", "operations/overhead",
                *(prefix + name for prefix in LEGACY_LEARNING_PREFIXES for name in ("model", "dataset", "training")),
                "src/runtime/sensing", "src/contracts/foundation")
PATH_SETUP = ("import pathlib,sys,runpy;root=pathlib.Path(sys.argv.pop(1)).resolve();"
              f"sys.path[:0]=[str(root/p) for p in {IMPORT_PATHS!r}]")
