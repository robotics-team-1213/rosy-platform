#!/usr/bin/env python3
"""Platform trust source for the OMX updater (`"trust_source": "platform"`, D-805 7).

The GitHub REST source shares the anonymous 60/h limit with every updater on the cell (2026-11-27: three
`rate_limited` runs, each delaying a release by 10 min). This source reads instead the green-main pointer that
the D-441 signing PC signs (`deploy/site/green_main_pointer.py`) after checking the same conditions: each
required check's newest GitHub Actions run completed with success, on main's first-parent line. Ancestry is
read from a local commit-only mirror over the git protocol (no API). Any failure raises SourceUnavailable:
the run logs `transient` and changes nothing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from omx_autoupdate_host import Host, SourceUnavailable, _sp

SCHEMA = "rosy-green-main/1"
SHA = re.compile(r"^[0-9a-f]{40}$")
GREEN = ("completed", "success", "github-actions")


def _verifier():
    site = Path(__file__).resolve().parents[2] / "site"  # deploy/site/candidate_signing.py ships in the release
    if str(site) not in sys.path:
        sys.path.insert(0, str(site))
    try:
        from candidate_signing import CandidateSignatureError, verify_manifest_signature
    except ImportError:
        raise SourceUnavailable("verifier_missing") from None
    return CandidateSignatureError, verify_manifest_signature


def parse_pointer(raw: bytes, cfg: dict) -> dict:
    try:
        p = json.loads(raw)
    except ValueError:
        raise SourceUnavailable("malformed") from None
    if (not isinstance(p, dict) or p.get("schema") != SCHEMA or p.get("repository") != cfg["github_repo"]
            or p.get("branch") != cfg["branch"] or not isinstance(p.get("source_commit"), str)
            or not SHA.fullmatch(p["source_commit"]) or type(p.get("commit_verified")) is not bool
            or not isinstance(p.get("required_checks"), list)
            or not all(isinstance(c, str) for c in p["required_checks"]) or type(p.get("generated_at")) is not int):
        raise SourceUnavailable("malformed")
    age = time.time() - p["generated_at"]  # a replayed old pointer (or a dead signer) must not hold the cell on an old head
    if not -300 <= age <= float(cfg.get("platform_max_age_s", 3600)):
        raise SourceUnavailable("stale")
    return p


class PlatformHost(Host):
    """Host whose head, checks, ancestry and verification come from the signed pointer and the local mirror."""

    def __init__(self, cfg: dict) -> None:
        super().__init__(cfg)
        self._pointer: dict | None = None

    def pointer(self) -> dict:
        if self._pointer is None:  # one read per run: head and checks come from the same signed bytes
            url = self.cfg["platform_url"]
            try:
                with urllib.request.urlopen(url, timeout=30) as body:
                    raw = body.read(64 * 1024)
                with urllib.request.urlopen(url + ".sig", timeout=30) as body:
                    sig = body.read(16 * 1024 + 1)
            except (OSError, ValueError):  # URLError, HTTPError and timeouts are OSError
                raise SourceUnavailable("unreachable") from None
            error, verify = _verifier()
            try:
                verify(raw, sig, trusted_key_id=self.cfg["platform_key_id"],
                       public_key=Path(os.path.expanduser(self.cfg["platform_public_key"])))
            except error:
                raise SourceUnavailable("bad_signature") from None
            self._pointer = parse_pointer(raw, self.cfg)
        return self._pointer

    def remote_head(self) -> str:
        return self.pointer()["source_commit"]

    def checks(self, sha: str) -> dict:
        p = self.pointer()
        return {name: GREEN for name in p["required_checks"]} if sha == p["source_commit"] else {}

    def verified(self, sha: str) -> bool:
        p = self.pointer()
        return sha == p["source_commit"] and p["commit_verified"]

    def descends(self, base: str, head: str) -> bool:
        """base is head or its ancestor on the fetched branch history; an unknown commit (a floor not on origin) is False."""
        mirror, branch = Path(self.cfg["root"]) / "history.git", self.cfg["branch"]
        git = ["git", "-C", str(mirror)]
        try:
            if not (mirror / "HEAD").is_file():
                shutil.rmtree(mirror, ignore_errors=True)  # a clone killed half way: start over
                _sp().run(["git", "clone", "-q", "--bare", "--filter=tree:0", "--single-branch", "--branch", branch,
                           self.cfg["repo_url"], str(mirror)], check=True, capture_output=True, timeout=600)
            else:
                _sp().run([*git, "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/heads/{branch}"],
                          check=True, capture_output=True, timeout=300)
            done = _sp().run([*git, "merge-base", "--is-ancestor", base, head], capture_output=True, timeout=60,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
        except (OSError, subprocess.SubprocessError):
            raise SourceUnavailable("history_unreachable") from None
        return done.returncode == 0
