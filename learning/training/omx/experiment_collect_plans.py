"""Draft OMX collection plans inside Learning Center (8768); never grants real-arm policy approval."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "learning" / "src"
if str(_CONTRACTS) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS))

from rosy.contracts.learning.omx_collect_plan import SCHEMA, problems, source_kind  # noqa: E402

MAX_BYTES = 65536
LIMIT_LIST = 100
APPROVAL_OWNER = "fleet_policy_approval_and_cell_gate"


class CollectPlans:
    def __init__(self, root: Path, lock):
        self.dir = Path(root) / "collect-plans"
        self.lock = lock

    def create(self, body: dict, principal: dict | None = None) -> dict:
        if not isinstance(body, dict) or len(json.dumps(body, default=str)) > MAX_BYTES:
            raise ValueError("bounded collection plan object required")
        plan = dict(body)
        plan.setdefault("schema", SCHEMA)
        if principal and principal.get("user_id"):
            plan["proposer"] = principal["user_id"]
        if bad := problems(plan, draft=True):
            raise ValueError("; ".join(bad))
        plan.pop("approver", None)
        plan["policy_real_approved"] = False
        plan_id = plan["plan_id"]
        target = self.dir / f"{plan_id}.json"
        record = {
            "ok": True,
            "schema": SCHEMA,
            "plan_id": plan_id,
            "arm": plan["arm"],
            "proposer": plan["proposer"],
            "values_from": plan.get("values_from", "taught"),
            "policy_real_approved": False,
            "approval_owner": APPROVAL_OWNER,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {
                    "item_id": item["item_id"],
                    "from": item["from"],
                    "to": item["to"],
                    "executor": item["executor"],
                    "source_kind": source_kind(plan, item),
                }
                for item in plan["items"]
            ],
            "plan": plan,
        }
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError(f"수집 계획 '{plan_id}'이 이미 있습니다")
            tmp = self.dir / f"{plan_id}.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, target)
        return record

    def list(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        out = []
        with self.lock:
            files = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
            for path in files:
                if len(out) >= LIMIT_LIST:
                    break
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES * 2:
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
                    out.append(doc)
        return out
