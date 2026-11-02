"""Subject: where each task's model pointers live on the robot (D-423 §3.1).

  <root>/<task>/shadow     what the shadow / advisory node runs next
  <root>/<task>/active     the promoted model (object_detector_node reads this)
  <root>/<task>/previous   the active one before the last promote; rollback target

Every pointer is a text file holding a model folder path (ModelSlot reads it,
model/deliver.py writes it under flock as root). lane_seg keeps the flat D-373
root (<root>/shadow, shadow.previous) for the transition, so the robots' lane
shadow keeps working without a migration step; a later release may move it.
"""
from __future__ import annotations

from .manifest import TASKS

MODELS_ROOT = '/var/lib/rosy/models'
SLOTS = ('shadow', 'active', 'previous')
FLAT_TASKS = ('lane_seg',)  # D-373 layout kept during the transition


def task_root(task: str, root: str = MODELS_ROOT) -> str:
    if task not in TASKS:
        raise ValueError(f'unknown task {task!r}; one of {TASKS}')
    return root if task in FLAT_TASKS else f'{root}/{task}'


def slot_pointer(task: str, slot: str, root: str = MODELS_ROOT) -> str:
    if slot not in SLOTS:
        raise ValueError(f'unknown slot {slot!r}; one of {SLOTS}')
    return f'{task_root(task, root)}/{slot}'
