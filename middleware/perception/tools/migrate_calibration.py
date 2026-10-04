"""Merge legacy cliff/drive YAML into a new, explicitly selected calibration file.

Sources are never modified. Conflicting values require operator review; this
does not invent device identity, revalidate measurements, or activate values.
"""
import argparse
from pathlib import Path

import yaml

from control.calibration_storage import _parameters, merge_calibration
from control.calibration_record import HEADER


def migrate(sources, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Destination already exists; choose a new calibration file')
    combined = {}
    for source in sources:
        text = Path(source).read_text(encoding='utf-8')
        if text.startswith(HEADER):
            raise ValueError('Bound records require an explicit identity-aware migration')
        document = yaml.safe_load(text)
        _parameters(document)
        for name, content in document.items():
            selector = '/**/' + name if '/' not in name else name
            parameters = combined.setdefault(selector, {'ros__parameters': {}})['ros__parameters']
            for key, value in content['ros__parameters'].items():
                if key in parameters and parameters[key] != value:
                    raise ValueError(f'Conflicting calibration value: {selector}/{key}')
                parameters[key] = value
    _parameters(combined)
    merge_calibration(str(destination), yaml.safe_dump(combined, sort_keys=False), create_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    migrate(args.source, args.output)
    print(f'Saved {args.output}; source measurements preserved, runtime not activated')


if __name__ == '__main__':
    main()
