"""Bind an existing native RGB episode to independently measured SIM object truth."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
from rosy.contracts.learning.omx import validate_demonstration
from rosy.contracts.learning.sim_object_truth import SCHEMA, TASK, validate_truth
from common_episode import _in_checkout


def build(run, native_manifest, output, *, source_root=ROOT):
    run, output, source_root = Path(run).resolve(), Path(output).resolve(), Path(source_root).resolve()
    native_manifest = Path(native_manifest).resolve()
    if output.exists() or _in_checkout(output) or output.is_relative_to(run) or run.is_relative_to(output):
        raise ValueError('new proof directory outside recording and source checkout required')
    result = json.loads((run/'teacher-result.json').read_bytes())
    source = run/'recordings'/result['episode_id']
    validated = validate_demonstration(source)
    original = validated['manifest']
    files = {
        'manifest': source/'manifest.json', 'samples': source/'samples.jsonl', 'events': source/'events.jsonl',
        'result': run/'teacher-result.json', 'observations': run/'observations.json',
        'phases': run/'teacher-phases.json', 'commands': run/'teacher-commands.json',
        'world': run/'camera-world.sdf', 'native_manifest': native_manifest,
        'cell': source_root/'operations/processes/cell/examples/omx_sim/cell.yaml',
        'recipe': source_root/'operations/processes/cell/examples/omx_sim/recipe.yaml',
        'profile': source_root/'deploy/robot/omx/sim/cell_profile.yaml',
        'source_world': source_root/'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf',
        'camera_source': source_root/'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf',
    }
    payloads = {name: file.read_bytes() for name, file in files.items()}
    output.mkdir(parents=True)
    references = {}
    for name, payload in payloads.items():
        target = output/'files'/(('source-manifest' if name == 'manifest' else name)+files[name].suffix)
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(payload)
        references[name] = {'path': target.relative_to(output).as_posix(), 'bytes': len(payload),
                            'sha256': hashlib.sha256(payload).hexdigest()}
    document = {'schema': SCHEMA, 'task': TASK, 'episode_id': original['episode_id'],
        'instance_id': original['provenance']['instance_id'], 'source': original['provenance'],
        'sim_aid': True, 'files': references}
    path = output/'truth.json'
    path.write_text(json.dumps(document, indent=2), encoding='utf-8')
    truth = validate_truth(path, validated, source=source)
    return {'truth': str(path), 'episode_id': original['episode_id'], 'metrics': truth['metrics']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--native-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.run, args.native_manifest, args.out)))
