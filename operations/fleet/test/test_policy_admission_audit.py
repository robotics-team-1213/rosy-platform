"""D-865 P2c policy admission audit log: durable budget and newest-first readback."""

from fleet.server.missions.policy_admission_audit import PolicyAdmissionAuditLog


def _log(tmp_path):
    return PolicyAdmissionAuditLog(str(tmp_path / "audit.db"))


class TestPolicyAdmissionAuditLog:
    def test_append_and_latest_newest_first(self, tmp_path):
        log = _log(tmp_path)
        log.append(at="2026-10-25T00:00:00Z", mission_id="m-1",
                   outcome="ADMITTED", scope_revision="rev-1", generation=2)
        log.append(at="2026-10-25T00:00:01Z", mission_id="m-2",
                   outcome="HELD", scope_revision="rev-1", generation=-1,
                   reason="ROBOT_OUT_OF_SCOPE")
        rows = log.latest()
        assert [row["mission_id"] for row in rows] == ["m-2", "m-1"]
        assert rows[0]["reason"] == "ROBOT_OUT_OF_SCOPE"

    def test_issued_count_counts_only_admits_per_revision(self, tmp_path):
        log = _log(tmp_path)
        for mission_id in ("m-1", "m-2"):
            log.append(at="t", mission_id=mission_id, outcome="ADMITTED",
                       scope_revision="rev-1", generation=1)
        log.append(at="t", mission_id="m-3", outcome="HELD",
                   scope_revision="rev-1", generation=-1, reason="EXHAUSTED")
        log.append(at="t", mission_id="m-4", outcome="ADMITTED",
                   scope_revision="rev-2", generation=1)
        assert log.issued_count("rev-1") == 2
        assert log.issued_count("rev-2") == 1
        assert log.issued_count("rev-none") == 0

    def test_budget_survives_reconnect(self, tmp_path):
        path = str(tmp_path / "audit.db")
        first = PolicyAdmissionAuditLog(path)
        first.append(at="t", mission_id="m-1", outcome="ADMITTED",
                     scope_revision="rev-1", generation=1)
        reopened = PolicyAdmissionAuditLog(path)  # 같은 파일 다시 열기 = 재시작
        assert reopened.issued_count("rev-1") == 1
        assert reopened.latest()[0]["mission_id"] == "m-1"
