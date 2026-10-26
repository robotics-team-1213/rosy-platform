"""Read the selected workcell's observer identities without changing or probing devices."""
import json
import re
import shlex
from pathlib import Path


def env_values(path, names):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        key, separator, raw = line.partition('=')
        if separator and key.strip() in names:
            parts = shlex.split(raw, comments=True)
            if len(parts) != 1 or key.strip() in values:
                raise ValueError('ambiguous selected configuration')
            values[key.strip()] = parts[0]
    return values


def collect(home=None):
    import yaml
    root = (home or Path.home()) / '.config/rosy'
    try:
        env = env_values(root / 'omx-observation-bridge.env', {'ROSY_WORKCELL_OBSERVATIONS', 'ROSY_OBSERVATION_WORKCELL'})
        manifest = Path(env['ROSY_WORKCELL_OBSERVATIONS'])
        if not manifest.is_absolute():
            raise ValueError('manifest must be absolute')
        cells = yaml.safe_load(manifest.read_text(encoding='utf-8'))['workcells']
        matches = [cell for cell in cells if cell['workcell_id'] == env['ROSY_OBSERVATION_WORKCELL']]
        if len(matches) != 1:
            raise ValueError('selected workcell must be unique')
        arms = [arm['arm_id'] for arm in matches[0]['arms']]
        if (not 1 <= len(arms) <= 8 or len(set(arms)) != len(arms)
                or any(not isinstance(arm, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', arm) for arm in arms)):
            raise ValueError('invalid selected arm identities')
        selected = {}
        for arm in arms:
            try:
                values = env_values(root / f'omx-observer-{arm}.env', {'ROSY_OBSERVER_DEVICE'})
                device = Path(values['ROSY_OBSERVER_DEVICE'])
                configured = device.parent == Path('/dev/serial/by-id')
                selected[arm] = {'configured': configured, 'connected': configured and device.is_symlink() and device.exists()}
            except (OSError, ValueError, KeyError):
                selected[arm] = {'configured': False, 'connected': False}
        return {'arms': selected}
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return {'error': 'selected workcell configuration unavailable or invalid'}


if __name__ == '__main__':
    try:
        result = collect()
    except ImportError:
        result = {'error': 'workcell configuration reader unavailable'}
    print('topology ' + json.dumps(result, sort_keys=True))
