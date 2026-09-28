"""Public GitHub Releases transport. Downloading is never permission to install."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

from bundle import BundleError, MAX_BYTES, release_id
from storage import check_update_headroom


def repository(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise BundleError("GITHUB_REPOSITORY", "configure owner/repository, not a URL")
    return value


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        url = urlsplit(newurl)
        if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
                or url.hostname not in {"github.com", "api.github.com", "release-assets.githubusercontent.com",
                                        "objects.githubusercontent.com"}):
            raise BundleError("DOWNLOAD_URL", "GitHub redirected outside the release asset hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": "rosy-release/1",
                                                   "Accept": "application/vnd.github+json"})
    return urllib.request.build_opener(_HTTPSRedirect()).open(request, timeout=30)


@dataclass(frozen=True)
class Candidate:
    release_id: str
    name: str
    url: str
    size: int
    sha256: str


def select_release(data: dict, repo: str, current: str | None) -> Candidate | None:
    repo = repository(repo)
    if not isinstance(data, dict):
        raise BundleError("GITHUB_RESPONSE", "release metadata must be an object")
    if data.get("draft") is not False or data.get("prerelease") is not False:
        return None
    version = release_id(data.get("tag_name"))
    if current is not None and version <= release_id(current):
        return None
    name = f"rosy-release-{version}.tar.zst"
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise BundleError("GITHUB_ASSET", "release has no asset list")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise BundleError("GITHUB_ASSET", f"expected exactly one {name}")
    asset = matches[0]
    url = f"https://github.com/{repo}/releases/download/{version}/{name}"
    if asset.get("browser_download_url") != url:
        raise BundleError("DOWNLOAD_URL", "asset URL does not match the configured repository and tag")
    size, digest = asset.get("size"), asset.get("digest")
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise BundleError("DOWNLOAD_SIZE", "asset size exceeds the release bound")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise BundleError("DOWNLOAD_DIGEST", "asset has no SHA256 digest")
    return Candidate(version, name, url, size, digest[7:])


def latest(repo: str, current: str | None = None, *, opener=open_url) -> Candidate | None:
    url = f"https://api.github.com/repos/{repository(repo)}/releases/latest"
    with opener(url) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise BundleError("GITHUB_RESPONSE", "metadata exceeds 2 MiB")
    return select_release(json.loads(raw), repo, current)


def download(candidate: Candidate, directory: Path, *, opener=open_url) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rejected = check_update_headroom(candidate.size, staging=directory)
    if rejected:
        raise BundleError(rejected[0].code, rejected[0].detail)
    target = directory / candidate.name
    digest, count = hashlib.sha256(), 0
    handle = tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False)
    temporary = Path(handle.name)
    try:
        with handle, opener(candidate.url) as response:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > candidate.size:
                    raise BundleError("DOWNLOAD_SIZE", "asset sent more bytes than declared")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if count != candidate.size:
            raise BundleError("DOWNLOAD_SIZE", "asset download ended early")
        if digest.hexdigest() != candidate.sha256:
            raise BundleError("DOWNLOAD_DIGEST", "download differs from GitHub asset digest")
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)
