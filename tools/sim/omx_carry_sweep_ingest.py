"""Real-result ingest and verdict scoring helpers split from `omx_carry_sweep`."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

_PASS, _FAIL = {"PASS", "VERIFIED", "ACCEPTED"}, {"FAIL", "FAILED", "REFUSED"}


def _tier_of(site: str) -> int:
    m = re.search(r"-l(\d)$", site or "")
    return int(m.group(1)) + 1 if m else 1


def tier_verdict(v):
    """True / False / None (UNKNOWN) from one tier-proof verdict. Shapes read: a bool; a string; the z_gate block of
    cell_area_zones.verify_stack_outcome_z_mm (verdict PASS/FAIL/UNKNOWN, with verified); a cell_stack_check.check result
    (accepted). A gate that could not see (no empty-slot floor, face hidden, S5_VIEW_OR_GATE_MISMATCH) is None, never True."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return True if v.upper() in _PASS else False if v.upper() in _FAIL else None
    if not isinstance(v, dict):
        return None
    if isinstance(v.get("z_gate"), dict):
        z = tier_verdict(v["z_gate"].get("verdict"))
        return None if z and v.get("verified") is False else z  # telemetry-only basis: the height was not measured
    if "verdict" in v:
        return tier_verdict(v["verdict"])
    if isinstance(v.get("accepted"), bool):
        if v["accepted"]:
            return True
        rows = [r for r in (v.get("tiers") or {}).values() if isinstance(r, dict)]
        blind = str(v.get("reason", "")).startswith("empty slot floor") or any(
            not r.get("ok") and ("hidden" in str(r.get("reason")) or "no top face" in str(r.get("reason"))) for r in rows)
        return None if blind else False
    return tier_verdict(v["verified"]) if isinstance(v.get("verified"), bool) else None


def load_verdicts(path: Path) -> dict:
    """{attempt_id (or episode id): True | False | None} from a mapping, a json list or json lines of tier-proof rows."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = [json.loads(x) for x in text.splitlines() if x.strip()]
    if isinstance(doc, dict) and "attempt_id" not in doc:
        return {k: tier_verdict(v) for k, v in doc.items()}
    return {r.get("attempt_id") or r.get("episode_id"): tier_verdict(r) for r in ([doc] if isinstance(doc, dict) else doc)}


def verified_episode_rows(joined: Path) -> dict:
    from cell_attempt_episodes import PARTS, episode_ref

    refs = {}
    for item in json.loads(joined.read_text(encoding="utf-8"))["joined"]:
        if item["status"] != "ok":
            continue
        attempt, episode = item["attempt"], item["episode"]
        attempt_id = attempt.get("attempt_id")
        folder = Path(episode["path"])
        if attempt_id in refs:
            refs[attempt_id] = None
        elif attempt_id and episode.get("sha") and all((folder / part).is_file() for part in PARTS):
            ref = attempt.get("episode")
            if ref:
                bound = (ref.get("id"), ref.get("sha")) == (episode["id"], episode["sha"])
            else:
                task = folder / "task.json"
                bound = task.is_file() and json.loads(task.read_text(encoding="utf-8")).get("attempt_id") == attempt_id
            if bound and episode_ref(folder) == episode:
                refs[attempt_id] = (attempt, episode["id"])
    return refs


def real_rows(attempts: Path, stack_check: Path | None = None, *, joined: Path | None = None) -> list:
    """One row per real carry attempt: outcome "ok" | "fail" | "unknown". A placed attempt is "ok" only on a
    True verdict (found by attempt_id, else by the row's optional episode id), False is a "verify" failure, and a missing or UNKNOWN
    verdict is "unknown": counted apart, never a success. A failed attempt stays failed whatever the proof says."""
    verdict = load_verdicts(stack_check) if stack_check else {}
    refs = verified_episode_rows(joined) if joined else None
    out = []
    for line in attempts.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        used = (r.get("context") or {}).get("choices_used") or {}
        for name, c in used.items():
            if name.startswith("carry.tier") and isinstance(c, dict):
                row = dict(attempt_id=r.get("attempt_id"), candidate=c["candidate"], tier=_tier_of(r.get("to")))
                mark = (r.get("tried") or {}).get("carry_shadowed")
                if mark and mark.get("candidate", c["candidate"]) == c["candidate"]:  # a site's own value won: the offer never ran
                    out.append(dict(row, outcome="shadowed", phase="shadowed"))
                    continue
                ep = (r.get("episode") or {}).get("id")
                if refs is not None:
                    checked = refs.get(r.get("attempt_id"))
                    if checked is None or checked[0] != r:
                        out.append(dict(row, outcome="unknown", phase="evidence_unlinked"))
                        continue
                    ep = checked[1]
                if r.get("outcome") != "placed":
                    out.append(dict(row, outcome="fail", phase=r.get("fail_stage") or "verify"))
                    continue
                got = verdict.get(r.get("attempt_id"), verdict.get(ep))
                out.append(dict(row, outcome="ok" if got else "unknown" if got is None else "fail", phase="verify"))
    return out


def real_table(attempts: Path, stack_check: Path | None = None, unknown: Counter | None = None, shadowed: Counter | None = None) -> dict:
    """{(candidate, tier): Counter(outcome)}: "ok" or the real failure phase; `unknown` (when given) takes the unverified count."""
    return tally_real_rows(real_rows(attempts, stack_check), unknown, shadowed)


def tally_real_rows(rows, unknown, shadowed):
    table = defaultdict(Counter)
    for r in rows:
        if r["outcome"] == "shadowed":  # never credited to the offered candidate, success or failure
            if shadowed is not None:
                shadowed[(r["candidate"], r["tier"])] += 1
        elif r["outcome"] == "unknown":
            if unknown is not None:
                unknown[(r["candidate"], r["tier"])] += 1
        else:
            table[(r["candidate"], r["tier"])]["ok" if r["outcome"] == "ok" else r["phase"]] += 1
    return table


def phase_of(cls):
    return "ok" if cls is None else cls.split(":")[0]


def ingest(out: Path, attempts: Path, stack_check=None, episodes=None, cell=None, *, joined=None):
    import omx_carry_sweep as sw

    unknown, shadowed = Counter(), Counter()
    outcomes = real_rows(attempts, stack_check, joined=joined)
    rows, real = sw.load_trials(out), tally_real_rows(outcomes, unknown, shadowed)
    sim = defaultdict(Counter)
    for r in rows:
        sim[(r["cand"], r["tier"])][phase_of(r.get("cls"))] += 1
    logw = defaultdict(list)  # scenario -> log importance weights, one per (candidate, tier) with real data
    for (c, t), rc in real.items():
        sc, n_r, K = sim.get((c, t)), sum(real[(c, t)].values()), 6
        if not sc:
            continue
        for r in rows:
            if r["cand"] == c and r["tier"] == t:
                o = phase_of(r.get("cls"))
                logw[r["scen"]].append(math.log(((rc[o] + .5) / (n_r + .5 * K)) / (sc[o] / sum(sc.values()))))
    w = {s: math.exp(sum(v) / len(v)) for s, v in logw.items()}
    z = sum(w.values()) or 1.0
    w = {s: v / z for s, v in w.items()}
    scen = {r["scen"]: r for r in rows}

    def wq(key, q):
        pts = sorted((scen[s][key], v) for s, v in w.items() if s in scen)
        acc = 0.0
        for x, v in pts:
            acc += v
            if acc >= q:
                return x
        return pts[-1][0] if pts else None
    phys = defaultdict(float)
    for s, v in w.items():
        phys[scen[s]["physics"]] += v
    next_dr = dict(tcp_m=sorted({scen[s]["tcp_m"] for s in w if w[s] >= 0.5 / max(len(w), 1)}) or sw.DR["tcp_m"],
                   sag_mm=sorted({scen[s].get("sag_mm", 0.0) for s in w if w[s] >= 0.5 / max(len(w), 1)}) or sw.DR["sag_mm"],
                   zero_deg=[wq("zero_deg", .1) or 0.0, wq("zero_deg", .9) or sw.DR["zero_deg"][1]],
                   physics={p: round(max(v, 0.02), 4) for p, v in phys.items()} or sw.DR["physics"], vision_frac=sw.DR["vision_frac"])
    missing = [dict(cand=c, tier=t, real_phase=ph, real_n=n) for (c, t), rc in real.items() for ph, n in rc.items()
               if ph != "ok" and not sim.get((c, t), {}).get(ph)]
    rescored = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["scen"] in w:
            rescored[r["tier"]][r["cand"]] += w[r["scen"]] * r["ok"]
    report = dict(real={f"{c}@t{t}": dict(rc) for (c, t), rc in real.items()}, real_unknown={f"{c}@t{t}": n for (c, t), n in unknown.items()},
                  shadowed={f"{c}@t{t}": n for (c, t), n in shadowed.items()},
                  missing_mechanisms=missing, next_dr=next_dr,
                  weighted_sim_success={t: dict(sorted(v.items(), key=lambda kv: -kv[1])[:6]) for t, v in rescored.items()},
                  note="a missing mechanism = a real failure phase sim never produced for that candidate: record it in sim2real-gaps, do not tune the sim to hide it")
    if episodes and cell:  # physics candidates against real episodes: reported beside the sweep, never a selection rule
        import omx_sysid
        report["sysid_score"] = omx_sysid.score(episodes, cell, list(sw.PHYSICS))
    (out / "real_outcomes.jsonl").write_text("\n".join(json.dumps(r) for r in outcomes), encoding="utf-8")  # sysid task --real
    (out / "ingest.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / "dr_next.json").write_text(json.dumps(next_dr, indent=1), encoding="utf-8")
    return report
