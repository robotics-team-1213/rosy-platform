#!/usr/bin/env python3
"""Automatic signed site-candidate updater for the arm cell (cell-a: fleet, vision, proxy only).

Installed copy: /usr/local/lib/rosy-cell/cell_a_autoupdate.py next to verify_candidate.py and
candidate_signing.py (see deploy/site/README.md "Arm cell updater"). It differs from
rosy_site_autoupdate.py: per-service tags in cell-a.env, the cell-a Compose project, and the arm
session/job locks. GitHub API use per run is kept small because several updaters on the cell share
the anonymous 60/h limit: the release list is a conditional (ETag) request and a 304 is not counted,
and an ancestry comparison of two fixed commits is cached.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = "robotics-team-1213/rosy-platform"
KEY_ID = "rosy-site-bench-20261003"
PUBLIC_KEY = Path("/etc/rosy/cell-a/trust/site-release-ed25519.pub.pem")
VERIFIER = Path("/usr/local/lib/rosy-cell/verify_candidate.py")
CELL_DIR = Path("/etc/rosy/cell-a")
ENV_FILE = CELL_DIR / "cell-a.env"
COMPOSE_FILES = [CELL_DIR / "compose.yaml", CELL_DIR / "compose.d1039.yaml"]
STATE_DIR = Path("/var/lib/rosy/cell-a-autoupdate")
STAGING_DIR = STATE_DIR / "staging"
FAILED_FILE = STATE_DIR / "failed.txt"
RELEASES_CACHE = STATE_DIR / "releases-cache.json"
FORWARD_CACHE = STATE_DIR / "forward-cache.json"
SERVICES = {
    "fleet": "ROSY_SITE_FLEET_TAG",
    "vision": "ROSY_SITE_VISION_TAG",
    "proxy": "ROSY_SITE_PROXY_TAG",
}
SESSION_LOCK = Path("/home/robttt/rosy-omx/session.lock")
JOB_DIR = Path("/home/robttt/rosy-jobs")
sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script folder; candidate_signing sits beside it
from candidate_signing import verify_manifest_signature
PART_RE = re.compile(r"^rosy-site-candidate-([0-9a-f]{40})\.tar\.part\d{2}$")


def log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=True, timeout=900)


def arm_session_active() -> bool:
    for pattern in ("rosy-omx-owner@*", "rosy-omx-arm-session@*"):
        res = run(["systemctl", "--user", "-M", "robttt@", "is-active", "--quiet", pattern], check=False)
        if res.returncode == 0:
            return True
    return False


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def verified_tags(manifest: dict) -> dict[str, str]:
    tags = {}
    for service, key in SERVICES.items():
        ref = manifest["images"][service]["reference"]
        match = re.fullmatch(fr"rosy-site-{service}:([0-9a-f]{{40}})", ref)
        if not match:
            raise RuntimeError(f"invalid signed image reference for {service}")
        tags[key] = match[1]
    return tags


def changed_env(previous: bytes, tags: dict[str, str]) -> bytes:
    content = previous
    for key, tag in tags.items():
        pattern = rb"(?m)^(" + key.encode() + rb"=)[^\r\n]*"
        content, count = re.subn(pattern, lambda match: match[1] + tag.encode(), content)
        if count != 1:
            raise RuntimeError(f"expected one setting for {key}")
    return content


def write_env(contents: bytes) -> None:
    attrs = ENV_FILE.stat()
    tmp = ENV_FILE.with_suffix(".env.new")
    with tmp.open("xb") as output:
        try:
            output.write(contents)
            output.flush()
            os.fchown(output.fileno(), attrs.st_uid, attrs.st_gid)
            os.fchmod(output.fileno(), attrs.st_mode & 0o777)
            os.fsync(output.fileno())
            os.replace(tmp, ENV_FILE)
        finally:
            tmp.unlink(missing_ok=True)


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "rosy-cell-autoupdate"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def fetch_releases() -> object:
    """Release list with If-None-Match: an unchanged list answers 304, which GitHub does not count."""
    cache = read_cache(RELEASES_CACHE)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "rosy-cell-autoupdate"}
    if isinstance(cache.get("etag"), str) and "body" in cache:
        headers["If-None-Match"] = cache["etag"]
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases?per_page=100", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            etag = resp.headers.get("ETag")
    except urllib.error.HTTPError as err:
        if err.code == 304 and "If-None-Match" in headers:
            return cache["body"]
        raise
    if etag and isinstance(body, list):
        write_cache(RELEASES_CACHE, {"etag": etag, "body": body})
    return body


def download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "rosy-cell-autoupdate"})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh)


def signed_releases():
    releases = fetch_releases()
    if not isinstance(releases, list):
        return None
    for rel in sorted(releases, key=lambda row: row.get("created_at") or "", reverse=True):
        tag = rel.get("tag_name", "")
        if not re.fullmatch(r"site-[a-f0-9]{12}", tag) or rel.get("draft"):
            continue
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", []) if "name" in a and "browser_download_url" in a}
        if "release.json.sig" in assets and "SHA256SUMS" in assets and "release.json" in assets:
            prefix = f"https://github.com/{REPO}/releases/download/{tag}/"
            if all(re.fullmatch(r"[a-zA-Z0-9_.-]+", name) and url == prefix + name
                   for name, url in assets.items()):
                yield tag, assets


def reused_present(manifest: dict) -> bool:
    for service, accepted in manifest.get("reused_images", {}).items():
        if service not in SERVICES:  # cell-a runs only fleet/vision/proxy; other reused images live on Fleet R
            continue
        ref = manifest["images"][service]["reference"]
        image = run(["docker", "image", "inspect", "--format", "{{.Id}}|{{.Os}}|{{.Architecture}}", ref], check=False)
        fields = image.stdout.strip().split("|")
        if image.returncode or len(fields) != 3 or fields[0] not in accepted or fields[1:] != ["linux", "amd64"]:
            return False
    return True


def latest_signed_release() -> tuple[str, dict[str, str]] | None:
    """Newest signed release whose reused images are already here: an incremental release reuses images an
    older one built, so a cell that skipped that older release must install it first (2026-11-26 hold)."""
    first = None
    for n, (tag, assets) in enumerate(signed_releases()):
        first = first or (tag, assets)
        if n >= 8:
            break
        try:
            with urllib.request.urlopen(assets["release.json"], timeout=30) as resp:
                manifest = json.loads(resp.read())
        except Exception:
            continue
        if isinstance(manifest, dict) and reused_present(manifest):
            return tag, assets
    return first


def compose_up(env_file: Path) -> None:
    cmd = ["docker", "compose", "--project-name", "cell-a", "--env-file", str(env_file)]
    for f in COMPOSE_FILES:
        if not f.is_file():
            raise RuntimeError("required Compose file is missing")
        cmd.extend(["-f", str(f)])
    cmd.extend(["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180"])
    run(cmd)


def forward(current: str, target: str) -> bool:
    if not re.fullmatch(r"[a-f0-9]{40}", current):
        return False
    key = f"{current}...{target}"
    cache = read_cache(FORWARD_CACHE)
    if isinstance(cache.get(key), bool):  # ancestry of two fixed commits never changes
        return cache[key]
    comparison = fetch_json(f"https://api.github.com/repos/{REPO}/compare/{key}?per_page=1")
    result = (isinstance(comparison, dict) and comparison.get("status") == "ahead"
              and comparison.get("merge_base_commit", {}).get("sha") == current)
    write_cache(FORWARD_CACHE, {key: result})
    return result


def check_runtime(tags: dict[str, str], checked_ids: dict[str, str]) -> None:
    for service, key in SERVICES.items():
        name = "peer-cell-a" if service == "proxy" else service
        ref = f"rosy-site-{service}:{tags[key]}"
        output = run(["docker", "inspect", "--format",
                      "{{.Config.Image}}|{{.Image}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                      f"cell-a-{name}-1"]).stdout.strip().split("|")
        if output[:3] != [ref, checked_ids[service], "running"] or (
                service != "proxy" and output[3:] != ["healthy"]):
            raise RuntimeError(f"activated {name} did not match the verified image")
    mount = run(["docker", "inspect", "--format",
                 '{{range .Mounts}}{{if eq .Destination "/var/lib/rosy"}}{{.Name}}{{end}}{{end}}',
                 "cell-a-fleet-1"]).stdout.strip()
    if mount != "cell-a_cell_a_data":
        raise RuntimeError("Fleet is not using its existing data volume")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if arm_session_active():
        log("held", reason="arm-session-active")
        return 0

    found = latest_signed_release()
    if not found:
        log("idle", reason="no-signed-release")
        return 0
    tag, assets = found

    work = STAGING_DIR / tag
    dl = work / "download"
    cand_root = work / "candidate"
    shutil.rmtree(work, ignore_errors=True)
    dl.mkdir(parents=True, exist_ok=True)
    cand_root.mkdir(parents=True, exist_ok=True)

    try:
        for name in ("SHA256SUMS", "release.json", "release.json.sig"):
            download_file(assets[name], dl / name)
        commits: set[str] = set()
        part_names: list[str] = []
        for line in (dl / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            parts = line.split("  ", 1)
            if len(parts) != 2:
                continue
            name = parts[1].strip()
            m = PART_RE.fullmatch(name)
            if m:
                commits.add(m.group(1))
                part_names.append(name)
        if len(commits) != 1:
            raise RuntimeError(f"unexpected commits in SHA256SUMS: {commits}")
        commit = commits.pop()
        if not commit.startswith(tag[5:]):
            raise RuntimeError(f"commit {commit} does not match tag {tag}")

        raw = (dl / "release.json").read_bytes()
        verify_manifest_signature(raw, (dl / "release.json.sig").read_bytes(),
                                  trusted_key_id=KEY_ID, public_key=PUBLIC_KEY)
        manifest = json.loads(raw)
        if manifest["source_commit"] != commit or tag != f"site-{commit[:12]}":
            raise RuntimeError("signed candidate commit does not match release")
        tags = verified_tags(manifest)
        env = read_env()
        current = env.get("ROSY_SITE_FLEET_TAG", "")
        if all(env.get(key) == tag_value for key, tag_value in tags.items()):
            log("idle", current=current, tag=tag)
            return 0
        failed = set(FAILED_FILE.read_text(encoding="utf-8").splitlines()) if FAILED_FILE.exists() else set()
        if commit in failed:
            log("skipped-failed", commit=commit, tag=tag)
            return 0
        if not forward(current, commit):
            log("held", current=current, target=commit, reason="not-forward")
            return 0

        if args.dry_run:
            log("would-install", tag=tag, commit=commit, current=current, image_tags=tags)
            return 0

        if not reused_present(manifest):
            log("held", tag=tag, reason="reused-image-missing-or-mismatched")
            return 0
        for name in sorted(part_names):
            download_file(assets[name], dl / name)
        subprocess.run(["sha256sum", "--check", "--strict", "SHA256SUMS"], cwd=dl, check=True, capture_output=True, text=True)

        archive = dl / f"rosy-site-candidate-{commit}.tar"
        with archive.open("wb") as out_f:
            for name in sorted(part_names):
                with (dl / name).open("rb") as in_f:
                    shutil.copyfileobj(in_f, out_f)
                (dl / name).unlink()

        with tarfile.open(archive, "r:") as bundle:
            members = bundle.getmembers()
            for member in members:
                if not (member.isfile() or member.isdir()):
                    raise RuntimeError(f"non-regular member: {member.name}")
                if member.name.startswith("/") or ".." in member.name.split("/") or not (member.name == commit or member.name.startswith(commit + "/")):
                    raise RuntimeError(f"unexpected member: {member.name}")
            bundle.extractall(cand_root, members=members, filter="data")
        archive.unlink()

        cand_dir = cand_root / commit
        if (cand_dir / "release.json").read_bytes() != raw:
            raise RuntimeError("bundle manifest differs from signed release asset")
        shutil.copy2(dl / "release.json.sig", cand_dir / "release.json.sig")

        run([sys.executable, str(VERIFIER), "--candidate-dir", str(cand_dir),
             "--trusted-key-id", KEY_ID, "--trusted-public-key", str(PUBLIC_KEY), "--signature-only"])
        run(["docker", "image", "load", "--input", str(cand_dir / "images.tar")])
        checked = json.loads(run([sys.executable, str(VERIFIER), "--candidate-dir", str(cand_dir),
                                  "--trusted-key-id", KEY_ID, "--trusted-public-key", str(PUBLIC_KEY),
                                  "--services", ",".join(SERVICES)]).stdout)
        if checked.get("result") != "PASS" or checked.get("source_commit") != commit:
            raise RuntimeError("loaded-image verification did not bind the candidate")
        if any(checked["image_references"][service].split(":", 1)[1] != tags[key]
               for service, key in SERVICES.items()):
            raise RuntimeError("verified runtime references differ from signed metadata")
        with SESSION_LOCK.open("rb") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log("held", reason="arm-session-lock")
                return 0
            if arm_session_active() or not JOB_DIR.is_dir() or any(JOB_DIR.glob("*.lock")) or read_env() != env:
                log("held", reason="arm-job-or-environment-changed")
                return 0
            prev_env = ENV_FILE.read_bytes()
            write_env(changed_env(prev_env, tags))
            try:
                compose_up(ENV_FILE)
                check_runtime(tags, checked["image_ids"])
            except Exception as err:
                write_env(prev_env)
                compose_up(ENV_FILE)
                log("rollback", commit=commit, error_type=type(err).__name__)
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                with FAILED_FILE.open("a", encoding="utf-8") as output:
                    output.write(commit + "\n")
                return 1

        log("installed", tag=tag, commit=commit)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())