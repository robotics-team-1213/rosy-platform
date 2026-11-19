"""Host choice for remote_pytest (moved out of it to keep the file under its size cap).

place() ranks the hosts that pass admission (floors, site reserve, alone exclusion); among them the host with the
least work this process already placed on it goes first, then the most headroom (which already counts the jobs the
probe saw running), then list order. A host skipped for a floor says which metric failed, once per host per run.
"""
from __future__ import annotations

import sys

PLACED_S: dict[str, float] = {}  # host -> estimated seconds of jobs this process placed there
REPORTED: set[str] = set()  # hosts whose floor failure was already reported this run


def reset() -> None:
    PLACED_S.clear()
    REPORTED.clear()


def charge(host: str, seconds: float) -> None:
    PLACED_S[host] = PLACED_S.get(host, 0.0) + seconds


def place(r, cls: str, hosts: list[str], probes: list[dict | None], cores: int = 0) -> tuple[list[str], list[str]]:
    """(hosts above the cls floor, least placed work then most headroom first, light ones after, the site PC only when no other fits; notes).
    ``cores``: an invocation's own ``ROSY_JOB_CORES`` (its lock's reservation) raises the core floor to it.
    ``r`` is remote_pytest (its HEADROOM, BLOCKED, SITES and constants stay patchable there)."""
    need_c, need_m = max(r.NEEDS[cls][0], cores), r.NEEDS[cls][1]
    floor_m = r.LIGHT_GB.get(cls, need_m)
    ranked, notes = [], []
    for i, (host, p) in enumerate(zip(hosts, probes)):
        if p is None:
            notes.append(f"{host}: unreachable")
            r.BLOCKED.discard(host)
            continue
        site = host in r.SITES or p.get("site", False)
        cores = p["nproc"] - max(p["load1"], p["lock_cores"]) - ((2 if cls == "sim" else r.SITE_RESERVE[0]) if site else 0)
        mem = min(p["avail_gb"], p["total_gb"] - p["lock_gb"]) - (r.SITE_RESERVE[1] if site else 0)
        short = [m for m in (("cores", cores, need_c), ("RAM", mem, floor_m)) if m[1] < m[2]]
        why = ("marked busy (~/rosy-jobs/busy)" if p["busy"] else "alone job running or waiting"
               if cls == "pytest" and p.get("pytest_blocked") else f"no {cls} capability" if not p[cls]
               else f"below disk floor {r.DISK_FLOOR_GB} GB" if r.disk_full(p)
               else f"below {cls} floor {need_c} cores/{floor_m} GB ({', '.join(f'{n} {v:.1f} < {f}' for n, v, f in short)})" if short
               else f"light (under {need_m} GB): serial, smallest invocations" if mem < need_m else "ok")
        disk = f", disk {p['disk_free_gb']:.1f} GB free ({p['disk_use']}%)" if "disk_free_gb" in p else ""
        stale = f"; busy marker {p['busy_ignored']} (ignored)" if p.get("busy_ignored") else ""
        notes.append(f"{host}: {cores:.1f} cores, {mem:.1f} GB free{disk}{' (site PC)' if site else ''} - {why}{stale}")
        (r.BLOCKED.add if why.startswith("alone job") else r.BLOCKED.discard)(host)
        if short and why.startswith("below") and host not in REPORTED:  # floor data for tuning: one event per host per run
            REPORTED.add(host)
            print(f"[remote-pytest] floor-skip host={host} class={cls} " + " ".join(
                f"{n.lower()}={v:.1f} floor={f}" for n, v, f in short), file=sys.stderr, flush=True)
        if why == "ok" or why.startswith("light"):
            r.HEADROOM[host] = {"cores": cores, "mem": mem, "site": site, "light": mem < need_m,
                                "sim_held": p.get("sim_held", 0), "browser_jobs": p.get("browser_jobs", 0), "caps": p.get("caps", ())}
            ranked.append((site, mem < need_m, PLACED_S.get(host, 0.0), -min(cores / need_c, mem / need_m), i, host))
    ranked.sort()
    non_site = [x[-1] for x in ranked if not x[0]]
    return (non_site + [x[-1] for x in ranked if x[0]] if not any(not x[0] and not x[1] for x in ranked) else non_site) or [x[-1] for x in ranked], notes
