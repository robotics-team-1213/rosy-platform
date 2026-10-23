"""D-499: link address status reuses address_reasons. It does not gather again."""

from pathlib import Path
import ast

from fleet.server.ingest_routes import address_reasons


def test_dispatch_loop_does_not_read_link():
    text = Path("operations/fleet/fleet/server/background_workers.py").read_text(encoding="utf-8")
    function = next(node for node in ast.parse(text).body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == '_task_dispatch_loop')
    body = ast.get_source_segment(text, function)
    assert '["link"]' not in body
    assert '.get("link")' not in body


def test_link_status_uses_the_address_reasons_rows():
    """The app wires set_link_address_status to address_reasons robot statuses."""
    app = Path("operations/fleet/fleet/server/app.py").read_text(encoding="utf-8")
    assert "set_link_address_status" in app
    assert "address_reasons" in app
    # The classifier stays the only place that names the protocol exception.
    assert "RemoteProtocolError" not in app


def test_address_reasons_status_map_shape():
    class Console:
        registered_endpoints = {"rosy_01": "http://127.0.0.1:8080"}

    class Hub:
        def __init__(self):
            self.registry = self

        def identity_snapshot(self):
            return {}

    class Discovery:
        def snapshot(self, endpoints, identities, enrolled):
            return {"scanner_online": False, "scanner_state": "off", "devices": None}

    class Enrollment:
        def enrolled_names(self):
            return {}

        def listing(self):
            return None

    result = address_reasons(console=Console(), hub=Hub(), discovery=Discovery(),
                             enrollment=Enrollment())
    assert {row["robot_id"]: row["status"] for row in result["robots"]} == {"rosy_01": "unknown"}
