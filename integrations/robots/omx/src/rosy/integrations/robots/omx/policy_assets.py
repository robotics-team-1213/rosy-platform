"""Verify portable SmolVLA metadata before LeRobot loads a model or tokenizer."""
import hashlib
import json
from pathlib import Path

MARKER = 'rosy-bundled-vlm'
SCHEMA = 'rosy.omx.smolvla-assets/1'
REQUIRED = frozenset({'config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json'})
VLM_FILES = REQUIRED | {'processor_config.json', 'special_tokens_map.json', 'chat_template.json',
                        'chat_template.jinja', 'added_tokens.json', 'vocab.json', 'merges.txt',
                        'generation_config.json'}


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def vlm_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('local VLM metadata directory is required')
    files = {}
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or path.name not in VLM_FILES:
            raise ValueError('unexpected or linked VLM metadata')
        files[path.name] = file_hash(path)
    if not REQUIRED <= files.keys():
        raise ValueError('missing local VLM configuration or tokenizer metadata')
    return files


def loading_overrides(checkpoint, config):
    if config.type != 'smolvla' or config.vlm_model_name != MARKER:
        return {}
    root = Path(checkpoint)
    manifest = root/'rosy-smolvla-assets.json'
    if manifest.is_symlink():
        raise ValueError('linked SmolVLA asset manifest')
    recorded = json.loads(manifest.read_text(encoding='utf-8'))
    actual = vlm_files(root/'vlm')
    if recorded != dict(schema=SCHEMA, files=actual):
        raise ValueError('SmolVLA metadata differs from its asset manifest')
    config.vlm_model_name = str((root/'vlm').resolve())
    config.load_vlm_weights = False
    return {'tokenizer_processor': {'tokenizer_name': config.vlm_model_name}}
