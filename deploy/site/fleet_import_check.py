"""Fail image construction when Fleet's process/model dependencies are missing."""

from fleet.server.cell_compiler import PalletizingCellJobCompiler
from fleet.server.device_care import DeviceCareStore
from fleet.server.mission_progress import MissionProgressService
from fleet.server.model_feedback_dispatch import MissionFeedbackToolDispatcher
from rosy.contracts.learning.inference import InferenceResult
from rosy.contracts.motion.characteristics import characteristics_digest


assert callable(PalletizingCellJobCompiler.compile_submission)
assert callable(DeviceCareStore)
assert callable(MissionProgressService.model_context_from_snapshot)
assert callable(MissionFeedbackToolDispatcher.dispatch)
assert callable(characteristics_digest)
assert InferenceResult.__dataclass_params__.frozen
