"""Prepare research input references only after direct raw-message verification."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from pinky_episode import ref
from verify_raw import verify


def prepare(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if (output.exists() or output.drive.upper() == 'F:' or output.is_relative_to(root)
            or root.is_relative_to(output)):
        raise ValueError('new behavior input directory separate from source, outside F: required')
    report = verify(root)  # Never trust an externally supplied pass report or marker.
    context = report['episode_context']  # Same validated object; no unchecked metadata reread.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pinky-input-', dir=output.parent) as scratch:
        stage = Path(scratch) / 'input'; stage.mkdir()
        path = stage / 'raw-verification.json'
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        doc = {'schema': 'rosy.pinky-behavior-input/1', 'dataset_revision': report['dataset_revision'],
               'episode_revision': report['episode_revision'], 'frames': report['frames'],
               'device': context['device'], 'robot_type': context['robot_type'],
               'environment': context['environment'], 'clock_domain': context['clock_domain'],
               'revisions': context['revisions'], 'source_streams': context['streams'],
               'action': {'semantics': 'recorded_core_final_velocity', 'names': ['linear_x', 'angular_z'],
                          'units': ['m/s', 'rad/s'], 'alignment': 'latest_at_or_before_frame_log',
                          'expert_status': 'unverified'}, 'raw_verification': ref(path, stage),
               'split': 'unassigned', 'eligibility': 'research_input_only',
               'holds': ['pixel_provenance', 'expert_action_semantics', 'fixed_behavior_eval', 'task_acceptance']}
        if context['revisions']['camera_profile'] is None:
            doc['holds'].append('camera_profile')
        (stage / 'behavior-input.json').write_text(json.dumps(doc, indent=2), encoding='utf-8')
        os.rename(stage, output)
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output)))


if __name__ == '__main__':
    main()
