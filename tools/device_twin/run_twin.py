#!/usr/bin/env python3
"""D-410 device twin: validate robot auto-update end to end without a robot (twin only).

    python tools/device_twin/run_twin.py --scenario all
    python tools/device_twin/run_twin.py --scenario b,f       # a subset
    python tools/device_twin/run_twin.py --list

Builds, under --work (default X:/DevTemp/d406-twin):
- a throwaway Ed25519 key (never the operator's release key);
- signed payload releases made with the repo's real tooling (build_twin_release.py);
- an ubuntu:24.04 container with systemd as PID 1, the real native runtime and
  rosy units from `git archive HEAD`, and fake ROS programs inside each release;
- a fake GitHub container serving the store the fake `gh` writes.

Every scenario runs on a fresh twin and checks real systemd state. The report is
<work>/report.md. Exit 0 only if every selected scenario passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import Result, Scenarios  # noqa: E402
from twin_lib import (API_BASE, GH, HOSTNAME, IMAGE, KEY_NAME, RELEASES, REPO, TRUSTED_STEM, TWIN,  # noqa: E402
                      Build, log, run)


def write_report(path: Path, results: list[Result], build: Build, started: dt.datetime) -> None:
    lines = [
        "# D-410 device twin report", "",
        f"- Run: {started.strftime('%Y-%m-%d %H:%M:%S')} (local), HEAD `{build.revision}`",
        f"- Twin: image `{IMAGE}` (ubuntu:24.04, systemd PID 1), hostname `{HOSTNAME}`; fake GitHub `{API_BASE}`, "
        f"repo `{REPO}`",
        "- Releases: " + ", ".join(f"{name}={rid} ({variant})" for name, (rid, variant, _m) in RELEASES.items()),
        f"- Key: throwaway `{KEY_NAME}`, installed as the device trust file `{TRUSTED_STEM}.pem`",
        "- Rerun: `python tools/device_twin/run_twin.py --scenario all`", "",
        "| Scenario | Result | Time |", "|---|---|---|",
    ]
    for result in results:
        lines.append(f"| ({result.key}) {result.title} | {'PASS' if result.passed else 'FAIL'} | {result.seconds:.0f} s |")
    for result in results:
        lines += ["", f"## ({result.key}) {result.title} — {'PASS' if result.passed else 'FAIL'}", ""]
        if result.error:
            lines += ["```text", result.error.strip(), "```", ""]
        for description, ok, detail in result.checks:
            shown = detail.replace("`", "'")[:500]
            lines.append(f"- {'PASS' if ok else 'FAIL'}: {description}" + (f" — `{shown}`" if detail else ""))
        if result.evidence:
            lines += ["", "<details><summary>evidence</summary>", ""]
            for command, output in result.evidence:
                lines += [f"`{command}`", "", "```text", output.strip() or "(no output)", "```", ""]
            lines.append("</details>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", default="all", help=f"all, or a comma list of {','.join(Scenarios.ORDER)}")
    parser.add_argument("--work", type=Path, default=Path("X:/DevTemp/d406-twin"))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--keep", action="store_true", help="leave the last twin and the fake GitHub running")
    args = parser.parse_args(argv)
    if args.list:
        for key in Scenarios.ORDER:
            print(f"{key:3} {getattr(Scenarios, key).__doc__}")
        return 0
    selected = Scenarios.ORDER if args.scenario == "all" else [item.strip() for item in args.scenario.split(",")]
    unknown = [item for item in selected if item not in Scenarios.ORDER]
    if unknown:
        parser.error(f"unknown scenario(s) {unknown}")

    started = dt.datetime.now()
    build = Build(args.work)
    build.prepare()
    build.base_image()
    build.key()
    build.build_releases()
    build.twin_image()
    build.network()
    scenarios = Scenarios(build)
    results: list[Result] = []
    for key in selected:
        method = getattr(scenarios, key)
        result = Result(key, method.__doc__.strip().splitlines()[0])
        scenarios.r = result
        log(f"scenario ({key}) {result.title}")
        clock = time.monotonic()
        try:
            scenarios.twin.start()
            method()
        except Exception:  # noqa: BLE001 - a crash is this scenario's FAIL; the others still run
            result.error = traceback.format_exc()
            log(result.error)
        result.seconds = time.monotonic() - clock
        log(f"scenario ({key}) {'PASS' if result.passed else 'FAIL'} in {result.seconds:.0f} s")
        results.append(result)
        write_report(args.work / "report.md", results, build, started)
    if not args.keep:
        run(["docker", "rm", "-f", TWIN, GH], check=False)
    log(f"report: {args.work / 'report.md'}")
    for result in results:
        log(f"  ({result.key}) {'PASS' if result.passed else 'FAIL'} {result.title}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
