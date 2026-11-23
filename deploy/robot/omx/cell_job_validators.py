"""Regex rules, range checkers, and AMR-bed site inspection helpers for `cell_job_spec`."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ARM = re.compile(r"arm_[abs]")
ACTOR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}")
NAME = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,62}")
TWO_ARM_SITE = re.compile(r"[a-z0-9_:-]{1,48}")
FILE = re.compile(r"(?:object-)?(cell|catalog|chunks)-[a-z0-9_.-]{1,60}\.json")
TASK_FILE = re.compile(r"(?:task|plan)-[a-z0-9_.-]{1,60}\.json")
FILTER_OBJ = re.compile(r"[a-z0-9_,-]{1,120}")
FILTER_COL = re.compile(r"[a-z0-9_,-]{1,64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_PATH = re.compile(r"[A-Za-z0-9_./~:-]{1,240}")
HTTP_URL = re.compile(r"^https?://[A-Za-z0-9._:\[\]-]+(?:/[A-Za-z0-9_./-]*)?$")
FIELD = re.compile(r"\{(\w+)\}")


def _num(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"a number in [{lo}, {hi}]")
        return str(v)

    return check


def _int_range(lo: int, hi: int):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"an integer in [{lo}, {hi}]")
        return str(v)

    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("a boolean")
    return v


def _match(rx):
    def check(v):
        if not isinstance(v, str) or not rx.fullmatch(v):
            raise ValueError(f"must match {rx.pattern}")
        return v

    return check


def _safe_path(v):
    if not isinstance(v, str) or not SAFE_PATH.fullmatch(v) or ".." in Path(v).parts:
        raise ValueError("must be a safe path without '..'")
    return v


def _actor(v):
    if not isinstance(v, str) or not ACTOR.fullmatch(v) or ".." in str(v).replace("\\", "/").split("/"):
        raise ValueError(f"must match {ACTOR.pattern}")
    return v


def _http_url(v):
    if not isinstance(v, str) or len(v) > 240 or not HTTP_URL.fullmatch(v):
        raise ValueError("must be an http(s) URL without query or credentials")
    parsed = urlsplit(v)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("must be an http(s) URL without query or credentials")
    return v


def _two_arm_task_sites(v: str) -> tuple[str, str]:
    if not isinstance(v, str) or v.count("->") != 1:
        raise ValueError("must be '<src>-><dst>'")
    src, dst = (p.strip() for p in v.split("->", 1))
    if not TWO_ARM_SITE.fullmatch(src) or not TWO_ARM_SITE.fullmatch(dst):
        raise ValueError("task endpoint must be a valid site name")
    if src == dst:
        raise ValueError("task source and destination must differ")
    return src, dst


def _two_arm_task(v):
    src, dst = _two_arm_task_sites(v)
    return f"{src}->{dst}"


def _roi(v):
    if not (isinstance(v, list) and len(v) == 4 and all(not isinstance(i, bool) and isinstance(i, int) and 0 <= i <= 1280 for i in v)):
        raise ValueError("four integer pixels")
    return [str(i) for i in v]


METRE = _num(-0.5, 0.5)


def _is_amr_bed_site(v: str) -> bool:
    if not isinstance(v, str) or not v:
        return False
    s = v.strip().lower()
    if s.startswith("not_places:"):
        s = s[len("not_places:"):]
    base = re.sub(r"-l[0-9]+$", "", s.split(":", 1)[0])
    return base.startswith(("pinky", "bed")) or base in ("tray", "vehicle_tray")


def _task_site_names(task_path: Path, config_path: Path | None) -> set[str]:
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("task: invalid JSON object") from exc
    if not isinstance(task, dict):
        raise ValueError("task: invalid JSON object")
    names: set[str] = set()

    def _add(val):
        if isinstance(val, str):
            names.add(val)

    for k in ("from", "to", "a", "b", "buffer"):
        _add(task.get(k))
    for k in ("columns", "sources", "destinations"):
        seq = task.get(k)
        if isinstance(seq, list):
            for v in seq:
                _add(v)
    for k in ("layout", "initial", "goal"):
        mp = task.get(k)
        if isinstance(mp, dict):
            for s in mp:
                _add(s)
    smap = task.get("site_map")
    if isinstance(smap, dict):
        for sk, sv in smap.items():
            _add(sk)
            _add(sv)
    steps = task.get("steps")
    if isinstance(steps, list):
        for st in steps:
            if isinstance(st, dict):
                _add(st.get("from"))
                _add(st.get("to"))
    if config_path is not None and config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            sites = cfg.get("sites") if isinstance(cfg, dict) else None
            if isinstance(sites, dict):
                if task.get("kind") in ("goal_stack", "outbound", "rehandle"):
                    if not task.get("layout"):
                        for k, v in sites.items():
                            if isinstance(v, dict) and "layer" not in v and v.get("kind", "temp") == "temp" and _is_amr_bed_site(k):
                                _add(k)
                    try:
                        import cell_task_runner

                        for st in cell_task_runner.plan_steps(task, sites):
                            _add(st.get("from"))
                            _add(st.get("to"))
                    except (ValueError, KeyError):
                        pass
                for s in list(names):
                    base = s.rsplit("-l", 1)[0]
                    for key in (s, base, f"{base}-l0", f"{base}-l1", f"{base}-l2"):
                        alts = (sites.get(key) or {}).get("alternates") if isinstance(sites.get(key), dict) else None
                        if isinstance(alts, list):
                            for a in alts:
                                _add(a)
        except (OSError, ValueError):
            pass
    return names
