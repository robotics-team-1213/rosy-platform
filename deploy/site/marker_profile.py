#!/usr/bin/env python3
"""Site marker profile: which owner holds which ArUco ids, so no two owners print the same picture (D-954).

DICT_4X4_50, _100, _250 and _1000 share their first ids (id n is the same picture in each), so overlap is checked
per family on the id itself. An allocation with "use": "calibration" is a sheet held up only while calibrating
(the ChArUco board); its shared ids are warnings, not errors.

"container_tags" maps a container tag id (owner container_tags, D-996 6) to the object_ref a business app declared.
ROSY owns this table; an app never sees the tag id.

  marker_profile.py check PROFILE.json [--site-cameras /etc/rosy/site/site-cameras.yaml]
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

SCHEMA = "rosy.marker-profile.v1"
_DICT = re.compile(r"^DICT_(\d+X\d+)_(\d+)$")
# site-cameras.yaml key -> the owner whose ids it may name
CAMERA_KEYS = {"corner_marker_ids": "field_corners", "place_markers": "place_markers"}


def _span(ids: list[int]) -> str:
    if len(ids) > 1 and ids == list(range(ids[0], ids[-1] + 1)):
        return f"{ids[0]}-{ids[-1]}"
    return ", ".join(map(str, ids))


def owned(profile: dict) -> dict:
    """{owner: [ids]} of a profile that passed check()."""
    return {row["owner"]: list(range(row["ids"][0], row["ids"][1] + 1)) for row in profile["allocations"]}


def check(profile: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one profile."""
    errors, rows = [], []
    if profile.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    names = set()
    for row in profile.get("allocations") or []:
        owner, ids = row.get("owner"), row.get("ids")
        match = _DICT.match(str(row.get("dictionary", "")))
        if not owner or owner in names:
            errors.append(f"owner {owner!r} is missing or repeated")
            continue
        names.add(owner)
        if not match:
            errors.append(f"{owner}: unknown dictionary {row.get('dictionary')!r}")
            continue
        size = int(match.group(2))
        if not (isinstance(ids, list) and len(ids) == 2 and all(type(i) is int for i in ids)
                and 0 <= ids[0] <= ids[1] < size):
            errors.append(f"{owner}: ids must be [first, last] within {row['dictionary']} (0-{size - 1})")
            continue
        rows.append((owner, match.group(1), set(range(ids[0], ids[1] + 1)), row.get("use") == "calibration"))
    warnings = []
    for (a, family, a_ids, a_cal), (b, other, b_ids, b_cal) in itertools.combinations(rows, 2):
        both = sorted(a_ids & b_ids) if family == other else []
        if both:
            (warnings if a_cal or b_cal else errors).append(f"{a} and {b} share {family} ids {_span(both)}")
    for slot in profile.get("arms") or {}:
        if f"arm_slot_{slot}" not in names:
            errors.append(f"arms names slot {slot} but no arm_slot_{slot} allocation")
    errors += _check_tags(profile, {owner: ids for owner, _, ids, _ in rows})
    return errors, warnings


def _check_tags(profile: dict, ids_of: dict) -> list[str]:
    tags = profile.get("container_tags") or {}
    if not tags:
        return []
    if "container_tags" not in ids_of:
        return ["container_tags names tags but there is no container_tags allocation"]
    errors, refs = [], {}
    for key, ref in tags.items():
        if not (str(key).isdigit() and int(key) in ids_of["container_tags"]):
            errors.append(f"container tag {key!r} is not a container_tags id")
        elif not (isinstance(ref, str) and 0 < len(ref) <= 128 and ref.strip() == ref):
            errors.append(f"container tag {key}: object_ref must be 1-128 characters without edge spaces")
        elif ref in refs:
            errors.append(f"container tags {refs[ref]} and {key} name the same object_ref")
        else:
            refs[ref] = key
    return errors


def object_ref_of(profile: dict, tag: int) -> str | None:
    """The object_ref a checked profile gives a container tag, or None when the tag is not in the table."""
    return (profile.get("container_tags") or {}).get(str(tag))


def check_cameras(profile: dict, cameras: dict) -> list[str]:
    """Ids a site-cameras.yaml names that its profile gives to another owner (or to none)."""
    table, errors = owned(profile), []
    for source in cameras.get("sources") or []:
        named = {key: set(source.get(key) or []) for key in CAMERA_KEYS}
        named["robot_markers"] = set((source.get("robot_markers") or {}).values())
        for key, ids in named.items():
            owner = CAMERA_KEYS.get(key, "robots")
            stray = sorted(ids - set(table.get(owner, [])))
            if stray:
                errors.append(f"{source.get('source_id')}: {key} {_span(stray)} are not {owner} ids")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="refuse shared ids; optionally the ids a site-cameras.yaml names")
    c.add_argument("profile", type=Path)
    c.add_argument("--site-cameras", type=Path)
    args = parser.parse_args(argv)
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    errors, warnings = check(profile)
    if not errors and args.site_cameras:
        import yaml

        errors += check_cameras(profile, yaml.safe_load(args.site_cameras.read_text(encoding="utf-8")) or {})
    for line in warnings:
        print(f"warning: {line}")
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    print("marker profile: " + ("REFUSED" if errors else "ok"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
