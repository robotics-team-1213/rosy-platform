"""PR C tests: Fleet AI Assistant categorical cell-objects facts and jitter invariance."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from fleet.server.assistant import context as ctx_mod
from fleet.server.assistant.journal import AssistantJournal
from fleet.server.assistant.service import AssistantService
from fleet.server.task_store import FleetTaskStore
from core_common.protocol.assistant import AssistantMessage


def _fake_app(now_s: float, detected_objects: dict):
    clock = lambda: now_s
    gather_called = False

    async def gather():
        nonlocal gather_called
        gather_called = True

    gather._snapshot = {"robots": [], "observed_at": now_s}
    gather.gathered_at = now_s
    gather._console = SimpleNamespace(_clock=clock)
    state = SimpleNamespace(
        fleet_gather=gather,
        omx_cell_states={"cell_s": {"phase": "IDLE"}},
        omx_cell_tasks={},
        arm_holds={},
        cell_detected_objects=detected_objects,
    )
    return SimpleNamespace(state=state)


def test_build_context_includes_fresh_catalog_summary_and_filters_stale_or_unmatched(monkeypatch):
    now_s = time.time()
    monkeypatch.setattr(ctx_mod, "fresh_snapshot", lambda snap, g, clk: snap)
    detected = {
        "cell_s": {
            "by_arm": {
                "arm_s": {
                    "received_at": now_s,
                    "observed_at": now_s,
                    "ttl_s": 15.0,
                    "objects": [
                        {"object_ref": "det:1:0", "catalog_id": "container-1", "site": "pinky", "pickable": True, "centre_mm": [10.12, 20.34]},
                        {"object_ref": "det:1:1", "catalog_id": "unmatched", "site": "pinky", "pickable": True, "centre_mm": [0.0, 0.0]},
                        {"object_ref": "det:1:2", "catalog_id": "container-2", "site": "belt", "pickable": False, "centre_mm": [99.9, 10.0]},
                    ],
                }
            }
        },
        "cell_ab": {
            "by_arm": {
                "arm_a": {
                    "received_at": now_s - 40.0,
                    "observed_at": now_s - 40.0,
                    "ttl_s": 15.0,
                    "objects": [{"object_ref": "det:2:0", "catalog_id": "stale-box", "site": "stand", "pickable": True}],
                }
            }
        },
    }
    app = _fake_app(now_s, detected)
    app.state.arm_holds = {"arm_a": {"held": True, "reason": "collision"}}
    facts = asyncio.run(ctx_mod.build_context(app, principal="alice", selected_robot_id=None, locale="ko-KR"))
    obj_facts = {f.ref: f for f in facts if f.ref.startswith("cell_objects:")}
    assert set(obj_facts) == {"cell_objects:cell_s"}
    fact = obj_facts["cell_objects:cell_s"]
    assert 0 <= time.time() - fact.observed_at <= 5
    assert "container-1@pinky(1개, 선택가능)" in fact.text
    assert "container-2@belt(1개, 제한)" in fact.text
    assert "unmatched" not in fact.text
    assert "10.12" not in fact.text and "99.9" not in fact.text
    hold_fact = next(f for f in facts if f.ref == "incident:arm_a")
    assert "collision" in hold_fact.text

    facts_en = asyncio.run(ctx_mod.build_context(app, principal="alice", selected_robot_id=None, locale="en-US"))
    fact_en = next(f for f in facts_en if f.ref == "cell_objects:cell_s")
    assert "container-1@pinky(x1, pickable)" in fact_en.text
    assert "container-2@belt(x1, blocked)" in fact_en.text


def test_assistant_service_tolerates_coordinate_and_seq_jitter_between_context_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(ctx_mod, "fresh_snapshot", lambda snap, g, clk: snap)
    store = FleetTaskStore(tmp_path / "tasks.sqlite")
    clock_now = time.time()
    journal = AssistantJournal(store._connect, clock=lambda: clock_now)
    seq = [10]
    detected = {
        "cell_s": {
            "by_arm": {
                "arm_s": {
                    "received_at": clock_now,
                    "observed_at": clock_now,
                    "ttl_s": 15.0,
                    "source_seq": 10,
                    "objects": [
                        {"object_ref": "det:10:0", "catalog_id": "container-1", "site": "pinky", "pickable": True, "centre_mm": [10.1, 20.2]},
                    ],
                }
            }
        }
    }
    app = _fake_app(clock_now, detected)

    async def context(principal, selected, locale="ko-KR"):
        return await ctx_mod.build_context(app, principal, selected, locale)

    async def provider(question, _remaining):
        # Simulate camera coordinate & frame jitter between pre-check and post-check
        seq[0] += 1
        snap = detected["cell_s"]["by_arm"]["arm_s"]
        snap["source_seq"] = seq[0]
        snap["observed_at"] = time.time()
        snap["received_at"] = time.time()
        snap["objects"][0]["centre_mm"] = [10.45, 20.67]
        return dict(kind="STATUS", response="cell_s 카탈로그 객체를 확인했습니다.", evidence_refs=["cell_objects:cell_s"])

    service = AssistantService(
        journal,
        context=context,
        provider=provider,
        admitted=lambda: True,
        authorized=lambda p: p == "alice",
        clock=time.time,
    )
    msg = AssistantMessage(request_id="req-obj-1", conversation_id="conv-1", text="셀 객체 보여줘")
    service.submit("alice", msg)
    asyncio.run(service.step("alice", "req-obj-1"))
    result = service.read("alice", "req-obj-1")
    assert result.state == "ANSWERED" and result.kind == "STATUS"
    assert any(f.ref == "cell_objects:cell_s" for f in result.facts)

    # Verify CONTROL stays D-810 compliant (answer returns clean without ASSISTANT_CONTEXT_CHANGED on jitter)
    async def ctrl_provider(question, _remaining):
        detected["cell_s"]["by_arm"]["arm_s"]["objects"][0]["centre_mm"] = [11.01, 19.88]
        return dict(kind="CONTROL", response="실행을 준비합니다.", evidence_refs=[])

    svc2 = AssistantService(
        journal, context=context, provider=ctrl_provider, admitted=lambda: True, authorized=lambda p: p == "alice", clock=time.time,
    )
    svc2.submit("alice", AssistantMessage(request_id="req-obj-2", conversation_id="conv-1", text="container-1 옮겨줘"))
    asyncio.run(svc2.step("alice", "req-obj-2"))
    res2 = svc2.read("alice", "req-obj-2")
    assert res2.state == "ANSWERED" and res2.kind == "CONTROL" and res2.facts == []
