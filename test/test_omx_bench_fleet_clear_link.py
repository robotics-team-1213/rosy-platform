"""Only Fleet's authenticated console can perform an operator clearance."""
from test_omx_bench_record import _setup, bench_record


def test_fleet_clear_entry_only_opens_the_configured_operator_console(tmp_path, monkeypatch):
    import http.client
    import threading
    from contextlib import closing
    from types import SimpleNamespace

    bench, _, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("omx_incident_fleet.link_for", lambda arm: SimpleNamespace(source_id=f"omx_{arm}"))
    srv = bench_record.make_server(bench, 0, fleet_console_origin="https://fleet.example.test:8443")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def request(method, query):
            with closing(http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)) as conn:
                conn.request(method, "/api/recover/fleet_clear" + query, headers={"X-Bench": "1"})
                response = conn.getresponse()
                response.read()
                return response.status, response.getheader("Location")

        assert request("GET", "?arm=arm_b") == (
            303, "https://fleet.example.test:8443/console/cell?focus=arm:omx_arm_b"
        )
        assert request("GET", "?arm=arm_b&arm=arm_s") == (400, None)
        assert request("GET", "?arm=arm_ab") == (400, None)
        assert request("GET", "?arm=arm_b&origin=https://elsewhere.test") == (400, None)
        assert request("POST", "?arm=arm_b") == (404, None)
        assert not calls and not commands
    finally:
        srv.shutdown()
        srv.server_close()
