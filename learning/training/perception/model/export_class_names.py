"""Model PC only: write a review data.yaml from an Ultralytics .pt (D-485).

The review app never unpickles models; run this where ultralytics is installed:

    python learning/training/perception/model/export_class_names.py best.pt --out data.yaml
"""
import argparse
from pathlib import Path

import yaml


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('model', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    from ultralytics import YOLO  # AGPL-3.0: used as an installed library on the model PC, not vendored
    model = YOLO(str(args.model))
    args.out.write_text(yaml.safe_dump({'task': model.task, 'names': dict(model.names)}, allow_unicode=True),
                        encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
