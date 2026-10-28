"""Lab SSH endpoints stay out of the public tree (D-226).

Copy ``hosts.example.json`` to ``private/lab-hosts.json`` on the main checkout.
A linked worktree reads that same file. ``ROSY_LAB_HOSTS`` overrides the path.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main_checkout(start: Path | None = None) -> Path:
    """Directory of the shared checkout. Worktrees keep ``private/`` beside it."""
    start = (start or ROOT).resolve()
    git = start / ".git"
    if not git.is_file():
        return start
    line = git.read_text(encoding="utf-8").strip()
    if not line.lower().startswith("gitdir:"):
        return start
    raw = line.split(":", 1)[1].strip()
    gitdir = Path(raw)
    gitdir = gitdir.resolve() if gitdir.is_absolute() else (start / gitdir).resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return start


def host_file() -> Path | None:
    override = os.environ.get("ROSY_LAB_HOSTS", "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None
    candidates = [main_checkout() / "private" / "lab-hosts.json"]
    local = ROOT / "private" / "lab-hosts.json"
    if local not in candidates:
        candidates.append(local)
    for path in candidates:
        if path.is_file():
            return path
    return None


def load() -> dict:
    path = host_file()
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must be a JSON object")
    return data


def test_hosts() -> list[str]:
    raw = load().get("test_hosts") or []
    if not isinstance(raw, list):
        raise SystemExit("lab-hosts.json test_hosts must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


def site_host() -> str:
    return str(load().get("site_host") or "").strip()


def ssh_target(value, field: str) -> str:
    """One SSH destination, never command options, role suffixes or shell words."""
    if not isinstance(value, str) or not re.fullmatch(
            r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_][A-Za-z0-9_.-]*', value.strip()):
        raise SystemExit(f'lab-hosts.json {field} must contain SSH target strings')
    return value.strip()


def sim_roles(config: dict) -> dict[str, str]:
    """Simulation candidates; an unsuffixed candidate has no inventory service role."""
    raw = config.get('sim_hosts', [])
    if not isinstance(raw, list):
        raise SystemExit('lab-hosts.json sim_hosts must be a list')
    found = {}
    for entry in raw:
        if not isinstance(entry, str):
            raise SystemExit('lab-hosts.json sim_hosts must contain SSH target strings')
        target, separator, role = entry.partition('=')
        target = ssh_target(target, 'sim_hosts')
        role = role.strip()
        if target in found or (separator and role not in {'model', 'ai'}):
            raise SystemExit('lab-hosts.json sim_hosts has an unknown or duplicate role binding')
        found[target] = role if separator else ''
    return found


def omx_hosts(config: dict | None = None) -> list[str]:
    """Native service placement; an absent key preserves legacy site co-location."""
    config = load() if config is None else config
    if 'omx_hosts' not in config:
        site = config.get('site_host', '')
        raw = [site] if site else []
    else:
        raw = config['omx_hosts']
    if not isinstance(raw, list):
        raise SystemExit('lab-hosts.json omx_hosts must be a list')
    hosts = [ssh_target(item, 'omx_hosts') for item in raw]
    if len(set(hosts)) != len(hosts):
        raise SystemExit('lab-hosts.json omx_hosts must not contain duplicate targets')
    if set(hosts) & sim_roles(config).keys():
        raise SystemExit('lab-hosts.json omx_hosts conflicts with a simulation role')
    return hosts


def robots() -> dict[str, str]:
    raw = load().get("robots") or {}
    if not isinstance(raw, dict):
        raise SystemExit("lab-hosts.json robots must be an object")
    return {str(key): str(value).strip() for key, value in raw.items() if str(value).strip()}
