"""D-773: weekly structure picks become Jira tasks; existing open tasks only get a comment."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/harness"))

import structure_jira  # noqa: E402

PICK = {"unit": "fleet", "group": "operations/fleet/fleet/server/tracking*", "lines": 1271,
        "files": ["operations/fleet/fleet/server/tracking.py", "operations/fleet/fleet/server/tracking_routes.py"],
        "epic": "KAN-19"}
URL = "https://github.com/robotics-team-1213/rosy-platform/issues/1"


class FakeJira:
    def __init__(self, existing=None, fail=False, summary=None, done=False):
        self.calls, self.existing, self.fail = [], existing, fail
        self.summary, self.done = summary or structure_jira.summary(PICK), done

    def __call__(self, request, timeout):
        body = json.loads(request.data.decode())
        self.calls.append((request.get_method(), request.full_url, body, dict(request.header_items())))
        if self.fail:
            raise structure_jira.urllib.error.URLError("down")
        if request.full_url.endswith("/search/jql"):
            status = {"statusCategory": {"key": "done" if self.done else "indeterminate"}}
            reply = {"issues": [{"key": self.existing, "fields": {"summary": self.summary, "status": status}}]
                     if self.existing else []}
        elif request.full_url.endswith("/issue"):
            reply = {"key": "KAN-99"}
        else:
            reply = {}
        return io.BytesIO(json.dumps(reply).encode())


def _jira(fake):
    return structure_jira.Jira("https://example.atlassian.net/", "bot@example.com", "token", opener=fake)


def test_a_new_pick_becomes_an_unassigned_task_under_its_epic():
    fake, out = FakeJira(), io.StringIO()
    assert structure_jira.run([PICK], URL, _jira(fake), "KAN", "Task", out=out) == 0
    search, create = fake.calls
    assert "summary ~" in search[2]["jql"] and "*" not in search[2]["jql"]
    fields = create[2]["fields"]
    assert fields["parent"] == {"key": "KAN-19"} and "assignee" not in fields
    assert fields["summary"] == "[구조] fleet — operations/fleet/fleet/server/tracking* 분리 (1271줄)"
    assert URL in fields["description"] and "tracking_routes.py" in fields["description"]
    assert "[KAN-<번호>]" in fields["description"]  # KAN-31: the task key goes in the branch and PR title
    assert create[3]["Authorization"].startswith("Basic ")
    assert "created KAN-99" in out.getvalue()


def test_an_open_task_for_the_same_group_only_gets_a_comment():
    fake = FakeJira(existing="KAN-50")
    assert structure_jira.run([PICK], URL, _jira(fake), "KAN", "Task", out=io.StringIO()) == 0
    assert [c[1].rsplit("/", 2)[-2:] for c in fake.calls][-1] == ["KAN-50", "comment"]
    assert not any(c[1].endswith("/issue") for c in fake.calls)


def test_a_closed_task_for_the_same_group_is_never_recreated():
    fake, out = FakeJira(existing="KAN-51", done=True), io.StringIO()
    assert structure_jira.run([PICK], URL, _jira(fake), "KAN", "Task", out=out) == 0
    assert len(fake.calls) == 1 and "skipped KAN-51" in out.getvalue()


def test_a_text_match_on_another_group_is_not_taken_for_this_one():
    other = structure_jira.summary({**PICK, "group": "operations/fleet/fleet/server/tracking/x*"})
    fake, out = FakeJira(existing="KAN-52", summary=other), io.StringIO()
    structure_jira.run([PICK], URL, _jira(fake), "KAN", "Task", out=out)
    assert "created KAN-99" in out.getvalue()


def test_an_http_refusal_names_jiras_reason():
    def refuse(request, timeout):
        raise structure_jira.urllib.error.HTTPError(request.full_url, 400, "Bad Request", {},
                                                    io.BytesIO(b'{"errors":{"issuetype":"invalid"}}'))
    out = io.StringIO()
    assert structure_jira.run([PICK], URL, _jira(refuse), "KAN", "Task", out=out) == 1
    assert "HTTP 400" in out.getvalue() and "issuetype" in out.getvalue()


def test_a_pick_without_an_epic_is_marked_for_the_lead():
    fake = FakeJira()
    structure_jira.run([{**PICK, "epic": None}], URL, _jira(fake), "KAN", "Task", out=io.StringIO())
    fields = fake.calls[-1][2]["fields"]
    assert "parent" not in fields and fields["summary"].startswith("[Epic 미정] ")
    assert fields["description"].startswith("리드 배정 필요")


def test_a_failed_call_is_reported_and_exits_one():
    out = io.StringIO()
    assert structure_jira.run([PICK], URL, _jira(FakeJira(fail=True)), "KAN", "Task", out=out) == 1
    assert "failed operations/fleet/fleet/server/tracking*" in out.getvalue()


def test_without_secrets_it_skips_and_succeeds(tmp_path, monkeypatch, capsys):
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    picks = tmp_path / "picks.json"
    picks.write_text(json.dumps({"picks": [PICK], "skipped": []}), encoding="utf-8")
    assert structure_jira.main([str(picks), URL]) == 0
    assert "skipped" in capsys.readouterr().err
