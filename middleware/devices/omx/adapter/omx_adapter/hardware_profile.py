"""Validate the D-496 measured document; never authorize or configure hardware."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .contracts.hardware_profile import (  # noqa: F401
    _fields,
    _number,
    _vector,
    _range,
    validate_profile,
    _UniqueLoader,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_profile(yaml.load(args.profile.read_text(encoding="utf-8"), Loader=_UniqueLoader))
    except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError) as error:
        print(json.dumps({"profile_document_valid": False, "motion_admitted": False, "error": str(error)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
