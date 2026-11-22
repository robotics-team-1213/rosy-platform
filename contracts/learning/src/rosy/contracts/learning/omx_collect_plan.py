"""Shared OMX real-arm collection plan schema (`rosy.omx-collect-plan.v1`) and rule-first outcome label.

8768 Learning Center uses `problems(plan, draft=True)` to author and persist unsigned collection drafts; it can
never stamp `policy_real_approved: True` or pick the Fleet/Cell approver. Cell tooling validates `draft=False`
before translating accepted items into `cell_job_api` requests.
"""
from __future__ import annotations

import re

SCHEMA = "rosy.omx-collect-plan.v1"
EXECUTORS = ("ik_chunk", "act", "hybrid")
SOURCE_KINDS = ("policy", "sim_optimized", "scripted_teacher", "teleop")
VALUES_FROM = ("sim_optimized", "taught")
MAX_ITEMS = 20
PLACED = ("released", "placed")
STOPPED = ("refused", "contact", "fault", "nothing_to_pick", "park", "aborted")

ARM = re.compile(r"arm_[abs]")
ACTOR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}")
NAME = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,62}")
SITE = re.compile(r"[a-z0-9_][a-z0-9_.:-]{0,62}")
FILE = re.compile(r"(cell|catalog|chunks)-[a-z0-9_.-]{1,60}\.json")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_PATH = re.compile(r"[A-Za-z0-9_./~:-]{1,240}")


def _has_dotdot(value) -> bool:
    return ".." in str(value).replace("\\", "/").split("/")


def source_kind(plan: dict, item: dict) -> str:
    """Where this episode's motion came from: a learned policy, sim-optimized carry values, or a taught chunk."""
    if item["executor"] != "ik_chunk":
        return "policy"
    return "sim_optimized" if plan.get("values_from") == "sim_optimized" else "scripted_teacher"


def problems(plan: dict, sites=None, *, draft: bool = False) -> list[str]:
    """Every reason a collection plan cannot be accepted; `draft=True` forbids pre-approving real policy execution."""
    out = []
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA}"]
    for key, rx in (("plan_id", NAME), ("arm", ARM)):
        if not isinstance(plan.get(key), str) or not rx.fullmatch(plan[key]):
            out.append(f"{key} is missing or malformed")
    if plan.get("values_from", "taught") not in VALUES_FROM:
        out.append(f"values_from is one of {VALUES_FROM}")
    proposer, approver = plan.get("proposer"), plan.get("approver")
    if not isinstance(proposer, str) or not ACTOR.fullmatch(proposer) or _has_dotdot(proposer):
        out.append("proposer is required")
    if draft:
        if "approver" in plan:
            out.append("Learning Center(8768) 수집 계획 초안에는 approver를 지정할 수 없습니다(D-1024)")
        if "policy_real_approved" in plan and plan.get("policy_real_approved") is not False:
            out.append("Learning Center(8768)는 수집 계획 초안만 생성하며 policy_real_approved를 발급할 수 없습니다(D-1024)")
    elif approver is not None and approver != "":
        if isinstance(approver, str) and isinstance(proposer, str) and approver.casefold() == proposer.casefold():
            out.append("approver must differ from proposer (D-1024)")
        elif not isinstance(approver, str) or not ACTOR.fullmatch(approver) or _has_dotdot(approver):
            out.append("approver is malformed")
    items = plan.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        return out + [f"items: 1..{MAX_ITEMS} carries"]
    cell = plan.get("cell") if isinstance(plan.get("cell"), dict) else {}
    for key in ("config", "catalog"):
        if not FILE.fullmatch(str(cell.get(key, ""))):
            out.append(f"cell.{key} must be a cell-/catalog- json name")
    if "max_chunks" in cell:
        mc = cell["max_chunks"]
        if type(mc) is not int or not 1 <= mc <= 6:
            out.append("cell.max_chunks must be an integer in 1..6")
    if "roi" in cell:
        roi = cell["roi"]
        if not (isinstance(roi, list) and len(roi) == 4 and all(type(v) is int and 0 <= v <= 1280 for v in roi) and roi[2] > 0 and roi[3] > 0):
            out.append("cell.roi must be [x, y, w, h] with positive w, h in 0..1280")
    seen = set()
    for n, item in enumerate(items):
        where = f"items[{n}]"
        if not isinstance(item, dict) or item.get("executor") not in EXECUTORS:
            out.append(f"{where}: executor is one of {EXECUTORS}")
            continue
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or item_id in seen or not NAME.fullmatch(item_id):
            out.append(f"{where}: item_id must be a unique name")
        if isinstance(item_id, str):
            seen.add(item_id)
        for key in ("from", "to"):
            val = item.get(key, "")
            rx = SITE if (key == "to" and item["executor"] != "ik_chunk") else NAME
            if not isinstance(val, str) or not rx.fullmatch(val) or _has_dotdot(val):
                out.append(f"{where}: {key} must be a site name")
            elif sites is not None and val not in sites:
                out.append(f"{where}: unknown site {val} (no silent substitute)")
        if item.get("from") == item.get("to"):
            out.append(f"{where}: from and to are the same site")
        if item["executor"] != "ik_chunk":
            pol = item.get("policy") if isinstance(item.get("policy"), dict) else {}
            root = pol.get("root", "")
            if not SHA256.fullmatch(str(pol.get("revision", ""))) or not isinstance(root, str) or not SAFE_PATH.fullmatch(root) or _has_dotdot(root):
                out.append(f"{where}: policy needs safe root and a sha256 revision")
            if not FILE.fullmatch(str(cell.get("library", ""))):
                out.append(f"{where}: cell.library must be a chunks- json name")
            cal = cell.get("cell_calibration", "")
            if not isinstance(cal, str) or not SAFE_PATH.fullmatch(cal) or _has_dotdot(cal):
                out.append(f"{where}: cell.cell_calibration must be a safe path")
            if not draft:
                if not approver:
                    out.append(f"{where}: approver is required for a real-arm policy run (D-1024)")
                if plan.get("policy_real_approved") is not True:
                    out.append(f"{where}: a real-arm policy run needs policy_real_approved: true (user decision, D-1024)")
    return out


def rule_verdict(result: dict) -> dict:
    """Rule-first outcome label from the runner's result and exact single-object source count drop."""
    res = result.get("result")
    if res in STOPPED:
        return {"outcome": "failure", "by": "rule", "reason": f"result {res}"}
    if result.get("parked") is False:
        return {"outcome": "failure", "by": "rule", "reason": f"result {res} but park failed"}
    if res in PLACED and result.get("took_one") is True:
        return {"outcome": "success", "by": "rule", "reason": "placed and the source count fell"}
    if res in PLACED and result.get("took_one") is False:
        return {"outcome": "failure", "by": "rule", "reason": "released but the source count did not fall"}
    return {"outcome": "unknown", "by": "rule", "reason": f"no measured proof (result {res})"}
