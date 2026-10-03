"""rosy_ml's model-slot commands (D-423 §3.2), kept out of rosy_ml.py's line budget.

deliver ROBOT REVISION [--task T] [--allow-unsigned] [--check KEYS]
promote ROBOT [--task T]                active <- shadow (CLI only; no CORE write API)
rollback ROBOT [--task T] [--slot shadow|active]
release-hold ROBOT [--task T]

They add no behaviour: each becomes one model/deliver.py argument list."""

from __future__ import annotations

COMMANDS = ("deliver", "promote", "rollback", "release-hold")


def add_parsers(sub) -> None:
    for name in COMMANDS:
        p = sub.add_parser(name)
        p.add_argument("robot")
        p.add_argument("--task", default="lane_seg")
        if name == "deliver":
            p.add_argument("revision")
            p.add_argument("--allow-unsigned", action="store_true")
            p.add_argument("--check", help="trusted-keys folder to verify the signature against")
        if name == "rollback":
            p.add_argument("--slot", choices=("shadow", "active"), default="shadow")


def deliver_argv(args, host: str, models: str) -> list[str]:
    """The deliver.py arguments for one slot command (ssh and operator flags come after)."""
    if args.cmd == "deliver":
        head = ["push", host, args.revision, "--models", models]
        head += ["--allow-unsigned"] if args.allow_unsigned else []
        head += ["--check", args.check] if args.check else []
    else:
        head = [args.cmd, host]
    head += ["--task", args.task]
    return head + (["--slot", args.slot] if args.cmd == "rollback" else [])
