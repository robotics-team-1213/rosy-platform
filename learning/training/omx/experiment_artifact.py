"""Download only a completed and hash-verified host policy artifact."""
import hashlib
import io
import json
import zipfile

from experiment_jobs import check_learning_task


def version_root(root, row):
    value = row.get('progress', {}).get('latest_version')
    if not str(value).isdigit() or not 1 <= int(value) <= 999999:
        raise ValueError('completed continuous policy version required')
    return root / 'versions' / f'{int(value):06}'


def model_archive(root, result, learning_task=None):
    names = ['normalization.json', 'profile.json', 'request.json', 'result.json',
             'evaluation.json', 'policy/config.json', 'policy/model.safetensors']
    if any((root / name).is_symlink() or not (root / name).is_file() for name in names):
        raise ValueError('regular model artifact files required')
    if sum((root / name).stat().st_size for name in names) > 256 * 1024 * 1024:
        raise ValueError('model archive exceeds 256 MiB')
    files = {name: (root / name).read_bytes() for name in names}
    if hashlib.sha256(files['policy/model.safetensors']).hexdigest() != result['policy_sha256']:
        raise ValueError('completed model weights changed')
    if learning_task is not None:
        check_learning_task(learning_task)
        if result.get('learning_task') != learning_task:
            raise ValueError('completed result task lineage differs from run')
        for name in ('request.json', 'result.json', 'evaluation.json'):
            if json.loads(files[name]).get('learning_task') != learning_task:
                raise ValueError('model artifact task lineage differs from run')
        if (json.loads(files['result.json']) != result
                or not isinstance(result.get('evaluation'), dict)
                or json.loads(files['evaluation.json']) != result['evaluation']):
            raise ValueError('completed task evaluation differs from stored result')
        files['learning-task.json'] = json.dumps(dict(learning_task=learning_task,
            evaluation_sha256=hashlib.sha256(files['evaluation.json']).hexdigest()),
            ensure_ascii=False, allow_nan=False).encode('utf-8')
    elif result.get('learning_task') is not None or any(
            json.loads(files[name]).get('learning_task') is not None
            for name in ('request.json', 'result.json', 'evaluation.json')):
        raise ValueError('task lineage requires a task-bound learning run')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()
