"""Manually publish weekly structure picks to Jira (D-773; separately configured CLI).

python tools/harness/structure_jira.py PICKS_JSON GITHUB_ISSUE_URL

PICKS_JSON is ``structure_report.py --picks-json`` output. For each pick it looks for a task this
tool made for the same group: open, it only comments the new issue link; closed, it skips (a person
already decided, e.g. "not one responsibility"); none, it creates a task under the pick's Epic (none: "[Epic 미정]" and "리드 배정 필요"),
unassigned (team-guide 5.1: the lead assigns). Environment: JIRA_BASE_URL, JIRA_EMAIL,
JIRA_API_TOKEN (an Atlassian API token), JIRA_PROJECT (default KAN), JIRA_ISSUE_TYPE (default Task).
Exit 0 when every pick was created or commented; 1 when any Jira call failed.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request


def summary(pick: dict) -> str:
    prefix = "" if pick.get("epic") else "[Epic 미정] "
    return f"{prefix}[구조] {pick['unit']} — {pick['group']} 분리 ({pick['lines']}줄)"


def description(pick: dict, issue_url: str) -> str:
    lines = ([] if pick.get("epic") else ["리드 배정 필요: 경로에 맞는 Epic이 없습니다.", ""])
    lines += [f"주간 구조 리포트: {issue_url}", "", "옮길 파일:"]
    lines += [f"- {path}" for path in pick["files"]]
    lines += ["", "완료 조건:",
              "1. import 이름을 바꾸지 않는 순수 이동(git mv); split_check.py에서 코드 차이는 등록 상수뿐",
              "2. 새 단위를 size_units.txt와 platform_parts.yaml에 등록, size_ratchet.txt 행을 측정값으로 낮춤",
              "3. 경로 문자열을 적은 시험·문서 갱신, 고정 깊이 경로(parents[N]) 확인",
              "4. 관련 시험 known_failures NEW 0, PR CI 통과",
              "5. 묶음이 한 책임(같은 ADR·기능)인지 담당자가 먼저 확인; 아니면 이 작업을 닫고 이유를 남김",
              "6. 브랜치 refactor/kan-<번호>-<주제>, PR 제목 [KAN-<번호>]로 이 작업 키를 남김 (KAN-31 안내)"]
    return "\n".join(lines)


class Jira:
    def __init__(self, base: str, email: str, token: str, opener=urllib.request.urlopen):
        self.base = base.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        self.opener = opener

    def call(self, method: str, path: str, body: dict) -> dict:
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method=method,
                                         headers={"Authorization": self.auth, "Content-Type": "application/json",
                                                  "Accept": "application/json"})
        with self.opener(request, timeout=30) as response:
            text = response.read().decode() or "{}"
        return json.loads(text)

    def existing(self, project: str, pick: dict) -> tuple[str, bool] | None:
        """(key, is_done) of a task already made for this exact group, open or closed."""
        phrase = pick["group"].rstrip("*").replace('"', "")  # "*" would be a JQL wildcard
        jql = f'project = {project} AND summary ~ "\\"{phrase}\\"" ORDER BY created DESC'
        found = self.call("POST", "/rest/api/3/search/jql",
                          {"jql": jql, "fields": ["summary", "status"], "maxResults": 50})
        marker = f"— {pick['group']} 분리"  # text search stems words; confirm our own summary exactly
        for issue in found.get("issues") or []:
            fields = issue.get("fields") or {}
            if marker in (fields.get("summary") or ""):
                category = ((fields.get("status") or {}).get("statusCategory") or {}).get("key")
                return issue["key"], category == "done"

    def comment(self, key: str, text: str) -> None:
        self.call("POST", f"/rest/api/2/issue/{key}/comment", {"body": text})

    def create(self, project: str, issue_type: str, pick: dict, issue_url: str) -> str:
        fields = {"project": {"key": project}, "issuetype": {"name": issue_type},
                  "summary": summary(pick), "description": description(pick, issue_url)}
        if pick.get("epic"):
            fields["parent"] = {"key": pick["epic"]}
        return self.call("POST", "/rest/api/2/issue", {"fields": fields})["key"]


def run(picks: list[dict], issue_url: str, jira: Jira, project: str, issue_type: str, out=sys.stdout) -> int:
    failed = 0
    for pick in picks:
        try:
            found = jira.existing(project, pick)
            if found and found[1]:
                print(f"skipped {found[0]} (closed before; a person decided): {pick['group']}", file=out)
            elif found:
                jira.comment(found[0], f"이번 주 구조 리포트에도 같은 후보가 나왔습니다: {issue_url}")
                print(f"commented {found[0]}: {pick['group']}", file=out)
            else:
                print(f"created {jira.create(project, issue_type, pick, issue_url)}: {pick['group']}", file=out)
        except urllib.error.HTTPError as exc:  # 5: say why Jira refused (issue type, parent, permissions)
            failed += 1
            detail = exc.read().decode("utf-8", "replace")[:300]
            print(f"failed {pick['group']}: HTTP {exc.code}: {detail}", file=out)
        except (urllib.error.URLError, KeyError, ValueError) as exc:
            failed += 1
            print(f"failed {pick['group']}: {type(exc).__name__}: {exc}", file=out)
    return 1 if failed else 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    missing = [name for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not os.environ.get(name)]
    if missing:
        print(f"skipped: {', '.join(missing)} not set", file=sys.stderr)
        return 0
    picks = json.loads(open(args[0], encoding="utf-8").read())["picks"]
    jira = Jira(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
    return run(picks, args[1], jira, os.environ.get("JIRA_PROJECT", "KAN"), os.environ.get("JIRA_ISSUE_TYPE", "Task"))


if __name__ == "__main__":
    sys.exit(main())
