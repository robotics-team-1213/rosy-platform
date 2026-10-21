"""Download only a completed and hash-verified host policy artifact."""
import hashlib
import io
import zipfile


def version_root(root, row):
    value = row.get('progress', {}).get('latest_version')
    if not str(value).isdigit() or not 1 <= int(value) <= 999999:
        raise ValueError('completed continuous policy version required')
    return root / 'versions' / f'{int(value):06}'


def model_archive(root, result):
    names = ['normalization.json', 'profile.json', 'request.json', 'result.json',
             'evaluation.json', 'policy/config.json', 'policy/model.safetensors']
    if any((root / name).is_symlink() or not (root / name).is_file() for name in names):
        raise ValueError('regular model artifact files required')
    if sum((root / name).stat().st_size for name in names) > 256 * 1024 * 1024:
        raise ValueError('model archive exceeds 256 MiB')
    files = {name: (root / name).read_bytes() for name in names}
    if hashlib.sha256(files['policy/model.safetensors']).hexdigest() != result['policy_sha256']:
        raise ValueError('completed model weights changed')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()
