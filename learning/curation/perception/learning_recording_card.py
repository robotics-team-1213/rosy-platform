"""Prepare the existing guarded native recorder's task card without opening hardware."""
import math
from pathlib import PurePosixPath
import re
import uuid


def make_card(task, options):
    required = {'root_prefix', 'episode_time_s', 'reset_time_s', 'num_episodes'}
    if (not isinstance(options, dict) or not required <= set(options)
            or set(options) - required - {'repo_id'}):
        raise ValueError('explicit recording storage, episode/reset times and count required')
    root = options['root_prefix']
    if (not isinstance(root, str) or not root.startswith('/') or len(root) > 1024
            or '..' in PurePosixPath(root).parts or any(ord(c) < 32 for c in root)
            or root == '/' or '.git' in PurePosixPath(root).parts):
        raise ValueError('explicit absolute recorder storage prefix required')
    for key in ('episode_time_s', 'reset_time_s', 'num_episodes'):
        value = options[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
            raise ValueError('bounded positive recording budgets required')
    if type(options['num_episodes']) is not int or options['num_episodes'] > 10000:
        raise ValueError('recording episode count must be an integer in 1..10000')
    if 'repo_id' in options and (not isinstance(options['repo_id'], str)
            or not re.fullmatch(r'[\w-]+/[\w.-]+', options['repo_id']) or '..' in options['repo_id']):
        raise ValueError('local dataset identity must be namespace/name')
    identity = str(uuid.UUID(task['id']))
    return dict(schema='rosy.omx-task-card.v1', task_id='learning-' + identity.replace('-', ''), revision=1,
        single_task=task['objective'], record=dict(options), success=task['success'], failure=task['failure'],
        reset=task['reset'], rosy_learning_task=dict(id=identity, revision=task['revision']))
