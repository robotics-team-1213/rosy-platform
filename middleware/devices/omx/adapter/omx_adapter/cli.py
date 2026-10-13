"""Command-line profile validator for commissioning and CI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .profile import OmxAdapterProfile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    data = yaml.safe_load(args.profile.read_text(encoding="utf-8")) or {}
    profile = OmxAdapterProfile.from_mapping(data.get("omx", data))
    print(json.dumps(profile.ros2_control_contract(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
