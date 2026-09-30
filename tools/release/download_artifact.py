"""Download one GitHub Actions artifact in parallel byte ranges, with progress.

`gh run download` shows nothing for a 2.6 GB unsigned image artifact and took
over ten minutes without a line of output (2026-09-30, release 009); eight range
workers finished in about 18 minutes. This tool makes that the repo way:

    python tools/release/download_artifact.py --run 123 --name rosy-os-image --out X:/DevTemp/a.zip
    python tools/release/download_artifact.py --artifact-id 456 --out X:/DevTemp/a.zip --extract X:/DevTemp/rel

The size comes from the API, the token from GH_TOKEN or `gh auth token`, and the
short-lived signed download URL from the API redirect. Neither the token nor the
signed URL is ever printed. Parts live next to the output (<out>.parts/) and a
re-run resumes them; the assembled file must have the API's exact size.
--extract checks the zip (CRC) and refuses entries that would land outside DIR.

Standard library only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

USER_AGENT = "rosy-download-artifact"
REQUEST_BYTES = 8 * 1024 * 1024
MAX_FAILURES = 6


class DownloadError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def github_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    try:
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise DownloadError("no GitHub token: set GH_TOKEN or run `gh auth login`") from error
    if not token:
        raise DownloadError("`gh auth token` returned nothing: run `gh auth login`")
    return token


def default_repo() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True,
                             check=True, cwd=Path(__file__).resolve().parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise DownloadError("cannot tell the repository: pass --repo OWNER/NAME") from error
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise DownloadError("origin is not a GitHub remote: pass --repo OWNER/NAME")
    return match.group(1)


class GitHub:
    def __init__(self, api_base: str, repo: str, token: str):
        self.api = api_base.rstrip("/") + f"/repos/{repo}/actions"
        self._token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT}

    def _json(self, path: str) -> dict:
        try:
            with urlopen(Request(self.api + path, headers=self._headers()), timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise DownloadError(f"GitHub API {path} returned HTTP {error.code}") from None

    def artifact(self, artifact_id: int | None, run: int | None, name: str | None) -> dict:
        if artifact_id is not None:
            found = self._json(f"/artifacts/{artifact_id}")
        else:
            listed = self._json(f"/runs/{run}/artifacts?name={name}&per_page=100")
            matches = [item for item in listed.get("artifacts", []) if item.get("name") == name]
            if len(matches) != 1:
                raise DownloadError(f"run {run} has {len(matches)} artifacts named {name!r}")
            found = matches[0]
        if found.get("expired"):
            raise DownloadError(f"artifact {found.get('id')} has expired")
        size = found.get("size_in_bytes")
        if not isinstance(size, int) or size <= 0:
            raise DownloadError("the API gave no artifact size")
        return found

    def signed_url(self, artifact_id: int) -> str:
        request = Request(f"{self.api}/artifacts/{artifact_id}/zip", headers=self._headers())
        try:
            build_opener(_NoRedirect).open(request, timeout=30)
        except HTTPError as error:
            location = error.headers.get("Location") if error.code in (301, 302, 303, 307, 308) else None
            if location:
                return location
            raise DownloadError(f"the artifact zip request returned HTTP {error.code}") from None
        raise DownloadError("the artifact zip request did not redirect to a download URL")


class Progress:
    def __init__(self, total: int, done: int, every: float):
        self.total = total
        self.done = done
        self.every = every
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._start = time.monotonic()
        self._start_bytes = done

    def add(self, count: int) -> None:
        with self._lock:
            self.done += count

    def line(self) -> str:
        with self._lock:
            done = self.done
        elapsed = max(time.monotonic() - self._start, 1e-6)
        rate = (done - self._start_bytes) / elapsed
        eta = f"{(self.total - done) / rate:.0f}s" if rate > 0 else "unknown"
        return (f"downloaded {done / 1e6:,.1f} / {self.total / 1e6:,.1f} MB "
                f"({100.0 * done / self.total:.1f}%) rate {rate / 1e6:.2f} MB/s eta {eta}")

    def run(self) -> None:
        while not self._stop.wait(self.every):
            print(self.line(), flush=True)

    def stop(self) -> None:
        self._stop.set()


class Downloader:
    def __init__(self, github: GitHub, artifact: dict, out: Path, workers: int, progress_seconds: float):
        self.github = github
        self.artifact_id = int(artifact["id"])
        self.size = int(artifact["size_in_bytes"])
        self.out = out
        self.parts_dir = Path(str(out) + ".parts")
        self.workers = max(1, min(workers, 64))
        self.progress_seconds = progress_seconds
        self._url_lock = threading.Lock()
        self._url: str | None = None
        self._url_generation = 0

    def _ranges(self) -> list[tuple[int, int]]:
        segment = -(-self.size // self.workers)
        return [(first, min(self.size, first + segment) - 1)
                for first in range(0, self.size, segment)]

    def _prepare_parts(self) -> list[tuple[int, int]]:
        meta_path = self.parts_dir / "meta.json"
        meta = {"artifact_id": self.artifact_id, "size": self.size, "workers": self.workers}
        if meta_path.exists():
            previous = json.loads(meta_path.read_text(encoding="utf-8"))
            if previous != meta:
                raise DownloadError(f"{self.parts_dir} holds parts of another download ({previous}); "
                                    "remove it or pass the same --workers")
        else:
            self.parts_dir.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return self._ranges()

    def _part(self, index: int) -> Path:
        return self.parts_dir / f"part-{index:02d}.bin"

    def _current_url(self, stale_generation: int | None = None) -> tuple[str, int]:
        with self._url_lock:
            if self._url is None or stale_generation == self._url_generation:
                self._url = self.github.signed_url(self.artifact_id)
                self._url_generation += 1
            return self._url, self._url_generation

    def _fetch(self, index: int, first: int, last: int, progress: Progress) -> None:
        part = self._part(index)
        total = last - first + 1
        failures = 0
        url, generation = self._current_url()
        while True:
            have = part.stat().st_size if part.exists() else 0
            if have == total:
                return
            if have > total:
                raise DownloadError(f"part {index} is larger than its range; remove {self.parts_dir}")
            start = first + have
            end = min(last, start + REQUEST_BYTES - 1)
            request = Request(url, headers={"Range": f"bytes={start}-{end}", "User-Agent": USER_AGENT})
            try:
                with urlopen(request, timeout=60) as response:
                    expected = f"bytes {start}-{end}/{self.size}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise DownloadError(f"part {index}: the server did not honour the byte range "
                                            f"(HTTP {response.status})")
                    payload = response.read()
                if len(payload) != end - start + 1:
                    raise OSError(f"part {index}: short response")
                with part.open("ab") as output:
                    output.write(payload)
                progress.add(len(payload))
                failures = 0
            except (OSError, URLError) as error:
                failures += 1
                code = getattr(error, "code", None)
                print(f"part {index} retry {failures}/{MAX_FAILURES}: {type(error).__name__}"
                      + (f" HTTP {code}" if code else ""), flush=True)
                if failures >= MAX_FAILURES:
                    raise DownloadError(f"part {index} did not complete; re-run to resume") from None
                time.sleep(min(2 * failures, 10))
                # The signed URL is short-lived; a failure asks for a fresh one.
                url, generation = self._current_url(generation)

    def run(self) -> Path:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        ranges = self._prepare_parts()
        done = sum(min(self._part(i).stat().st_size, last - first + 1)
                   for i, (first, last) in enumerate(ranges) if self._part(i).exists())
        progress = Progress(self.size, done, self.progress_seconds)
        print(f"artifact {self.artifact_id}: {self.size / 1e6:,.1f} MB in {len(ranges)} parts"
              + (f", resuming at {done / 1e6:,.1f} MB" if done else ""), flush=True)
        reporter = threading.Thread(target=progress.run, daemon=True)
        reporter.start()
        try:
            with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
                futures = [pool.submit(self._fetch, i, first, last, progress)
                           for i, (first, last) in enumerate(ranges)]
                for future in futures:
                    future.result()
        finally:
            progress.stop()
        print(progress.line(), flush=True)
        temporary = Path(str(self.out) + ".assembling")
        with temporary.open("wb") as output:
            for index in range(len(ranges)):
                with self._part(index).open("rb") as source:
                    shutil.copyfileobj(source, output, length=REQUEST_BYTES)
        actual = temporary.stat().st_size
        if actual != self.size:
            temporary.unlink()
            raise DownloadError(f"assembled size {actual} != API size {self.size}; remove {self.parts_dir} and re-run")
        os.replace(temporary, self.out)
        shutil.rmtree(self.parts_dir)
        print(f"complete: {self.out} ({actual} bytes)", flush=True)
        return self.out


def safe_extract(archive: Path, destination: Path) -> list[str]:
    """Extract after a CRC check; refuse absolute, drive or '..' entry names."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        for name in names:
            path = PurePosixPath(name.replace("\\", "/"))
            if (path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name)
                    or not (destination / path).resolve().is_relative_to(destination)):
                raise DownloadError(f"refusing zip entry outside the destination: {name!r}")
        bad = bundle.testzip()
        if bad is not None:
            raise DownloadError(f"zip entry {bad!r} fails its CRC check")
        destination.mkdir(parents=True, exist_ok=True)
        bundle.extractall(destination)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--run", type=int, help="workflow run id (with --name)")
    which.add_argument("--artifact-id", type=int)
    parser.add_argument("--name", help="artifact name within --run")
    parser.add_argument("--repo", help="OWNER/NAME (default: this checkout's origin)")
    parser.add_argument("--out", type=Path, required=True, help="zip file to write")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--progress-seconds", type=float, default=10.0)
    parser.add_argument("--extract", type=Path, metavar="DIR")
    parser.add_argument("--api-base", default="https://api.github.com", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.run is not None and not args.name:
        parser.error("--run needs --name")
    try:
        github = GitHub(args.api_base, args.repo or default_repo(), github_token())
        artifact = github.artifact(args.artifact_id, args.run, args.name)
        if args.out.exists() and args.out.stat().st_size == int(artifact["size_in_bytes"]):
            print(f"already complete: {args.out}", flush=True)
        else:
            Downloader(github, artifact, args.out, args.workers, args.progress_seconds).run()
        if args.extract:
            names = safe_extract(args.out, args.extract)
            print(f"extracted {len(names)} entries to {args.extract}", flush=True)
    except (DownloadError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
