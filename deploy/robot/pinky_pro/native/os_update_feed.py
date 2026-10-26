"""Signed OS catalogue/distribution client; only the frozen lifecycle owner may apply a staged bundle."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import runpy
import stat
from urllib.parse import urlsplit

from auto_update_host import API_BASE, Host, Http, MAX_LIST_BYTES, UpdateError, parse_z, _z
from os_factory_release import PUBLIC_KEY
from os_state_io import _json_atomic
from os_state_layout import COMMON, _object, _path, _read
from os_update_manifest import release_id, verify_metadata
from os_update_policy import _Policy
import os_update_rollout as rollout
from os_update_stage import stage
from os_update_state import read_state
import os_update_controller as lifecycle

TAG = "os-pinky-pro-"
CACHE = COMMON + "/os-update/feed.json"
CACHE_FIELDS = {"schema_version", "repo", "api_base", "fetched_at", "etag", "releases", "backoff_until"}


class Withdrawn(ValueError):
    """A verified publisher withdrawal, not an unauthenticated network/parser error."""


class Feed:
    def __init__(self, root: Path, *, host=None, http=None):
        self.root = Path(root).absolute()
        self.host = host if host is not None else Host(self.root)
        self.config = _Policy(self.root, self.host)._config()
        self.api = (self.config["api_base"] or API_BASE).rstrip("/")
        self.http = http if http is not None else Http(("https", "http") if self.api.startswith("http://") else ("https",))

    def _freeze(self):
        namespace = runpy.run_path(str(Path(__file__).with_name("rosy-update-gate")))
        decide = namespace["decide"]
        decide.__globals__["ROOT"] = "" if self.root == Path("/") else str(self.root)
        code, reason = decide()
        if code: raise ValueError("OS_FEED_FROZEN: " + reason)

    def _empty_cache(self):
        return dict(schema_version=1, repo=self.config["repo"], api_base=self.api,
                    fetched_at=None, etag=None, releases=[], backoff_until=None)

    def _cache(self):
        path = _path(self.root, CACHE)
        if not path.exists(): return self._empty_cache()
        info = path.stat()
        if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("OS_FEED_CACHE: unsafe cache")
        value = _object(_read(path, MAX_LIST_BYTES, self.root.stat().st_uid), CACHE_FIELDS)
        if value["repo"] != self.config["repo"] or value["api_base"] != self.api: return self._empty_cache()
        if (not isinstance(value["releases"], list) or len(value["releases"]) > 1000
                or value["etag"] is not None and (not isinstance(value["etag"], str) or len(value["etag"]) > 512)
                or any(value[key] is not None and parse_z(value[key]) is None for key in ("fetched_at", "backoff_until"))):
            raise ValueError("OS_FEED_CACHE: invalid cache fields")
        for item in value["releases"]: self._cached_entry(item)
        return value

    def _save(self, value):
        if len(json.dumps(value).encode()) > MAX_LIST_BYTES:
            raise ValueError("OS_FEED_CACHE: cache exceeds limit")
        _json_atomic(_path(self.root, CACHE), value, 0o600)

    def _url(self, url, identity, name):
        if not isinstance(url, str) or len(url) > 4096: raise ValueError("OS_FEED_URL: invalid asset URL")
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("OS_FEED_URL: credentials/fragment/query not allowed")
        if self.api == API_BASE:
            expected = f"https://github.com/{self.config['repo']}/releases/download/{TAG + identity}/{name}"
            if url != expected: raise ValueError("OS_FEED_URL: asset differs from canonical release")
        else:
            origin = urlsplit(self.api)
            if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                raise ValueError("OS_FEED_URL: asset escaped configured catalogue origin")
        return url

    def _names(self, identity):
        return {f"rosy-os-pinky-pro-{identity}-arm64.raucb", "os-update.json", "os-update.json.sig", "os-rollout.json", "os-rollout.json.sig"}

    def _cached_entry(self, item):
        if not isinstance(item, dict) or set(item) != {"release_id", "assets"}: raise ValueError("OS_FEED_CACHE: invalid entry")
        identity = release_id(item["release_id"])
        if not isinstance(item["assets"], dict) or set(item["assets"]) != self._names(identity):
            raise ValueError("OS_FEED_CACHE: invalid asset set")
        for name, url in item["assets"].items(): self._url(url, identity, name)
        return item

    def _entry(self, item):
        if not isinstance(item, dict) or item.get("draft") is not False or item.get("prerelease") is not False: return None
        tag = item.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith(TAG): return None
        try: identity = release_id(tag[len(TAG):])
        except ValueError: return None
        wanted = self._names(identity)
        assets = item.get("assets")
        if not isinstance(assets, list) or len(assets) > 256: raise ValueError("OS_FEED: invalid asset inventory")
        found = {}
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") not in wanted: continue
            name = asset["name"]
            if name in found: raise ValueError("OS_FEED: duplicate OS asset")
            found[name] = self._url(asset.get("browser_download_url"), identity, name)
        if set(found) != wanted: return None
        return dict(release_id=identity, assets=found)

    def _get(self, url, limit):
        code, _, raw = self.http.get(url, {"Accept": "application/octet-stream", "Cache-Control": "no-cache"}, limit)
        if code != 200: raise ValueError("OS_FEED_HTTP: " + str(code))
        return raw

    def _releases(self):
        cache = self._cache()
        now = self.host.now()
        until = parse_z(cache["backoff_until"]) if cache["backoff_until"] else None
        if until is not None and 0 < (until - now).total_seconds() <= 3600:
            raise ValueError("OS_FEED_RATE_LIMITED: waiting for retry")
        fetched = parse_z(cache["fetched_at"]) if cache["fetched_at"] else None
        if fetched is not None and 0 <= (now - fetched).total_seconds() < 600: return cache["releases"]
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if cache["etag"]: headers["If-None-Match"] = cache["etag"]
        base = f"{self.api}/repos/{self.config['repo']}/releases?per_page=100"
        found = {}
        for page in range(1, 11):
            code, response, raw = self.http.get(base + ("&page=" + str(page) if page > 1 else ""), headers if page == 1 else {}, MAX_LIST_BYTES)
            if code in (403, 429):
                retry = response.get("retry-after", "")
                delay = int(retry) if isinstance(retry, str) and retry.isdigit() and len(retry) < 8 else 600
                cache["backoff_until"] = _z(now + dt.timedelta(seconds=max(60, min(delay, 3600))))
                self._save(cache)
                raise ValueError("OS_FEED_RATE_LIMITED: " + str(code))
            if code == 304 and page == 1 and fetched is not None:
                cache["fetched_at"] = _z(now); self._save(cache)
                return cache["releases"]
            if code != 200: raise ValueError("OS_FEED_HTTP: catalogue " + str(code))
            listed = json.loads(raw)
            if not isinstance(listed, list) or len(listed) > 100: raise ValueError("OS_FEED: catalogue is not a bounded list")
            for item in listed:
                entry = self._entry(item)
                if entry is not None:
                    if entry["release_id"] in found: raise ValueError("OS_FEED: duplicate OS release")
                    found[entry["release_id"]] = entry
            if page == 1:
                etag = response.get("etag")
                cache["etag"] = etag if isinstance(etag, str) and len(etag) <= 512 else None
            if not re.search(r';\s*rel="next"', response.get("link", "")): break
            if page == 10: raise ValueError("OS_FEED: catalogue truncated; refusing partial selection")
        cache.update(fetched_at=_z(now), backoff_until=None, releases=sorted(found.values(), key=lambda e: e["release_id"], reverse=True))
        self._save(cache)
        return cache["releases"]

    def _metadata(self, entry):
        urls = entry["assets"]
        raw = self._get(urls["os-update.json"], 16384)
        signature = self._get(urls["os-update.json.sig"], 512).decode("ascii").strip()
        value = verify_metadata(raw, signature, _path(self.root, PUBLIC_KEY))
        if value["release_id"] != entry["release_id"]: raise ValueError("OS_FEED: tag and signed OS identity differ")
        return value, raw, signature

    def _admit_entry(self, entry, metadata):
        urls = entry["assets"]
        raw = self._get(urls["os-rollout.json"], 16384)
        sig = self._get(urls["os-rollout.json.sig"], 512).decode("ascii").strip()
        policy = rollout.verify(raw, sig, _path(self.root, PUBLIC_KEY), metadata)
        if policy["withdrawn"]: raise Withdrawn("OS_ROLLOUT_WITHDRAWN: " + metadata["release_id"])
        rollout.authorize(policy, self.host.hostname(), self.host.now())

    def admit(self, metadata):
        """Fresh tagged release + signed rollout, never the discovery cache, authorizes an install/arm."""
        url = f"{self.api}/repos/{self.config['repo']}/releases/tags/{TAG + release_id(metadata['release_id'])}"
        entry = self._entry(json.loads(self._get(url, MAX_LIST_BYTES)))
        if entry is None or entry["release_id"] != metadata["release_id"]: raise ValueError("OS_FEED: release no longer published")
        self._admit_entry(entry, metadata)

    def poll(self, *, apply=True, run=None):
        if read_state(self.root)["pending"] is not None:
            return dict(outcome="resumed", state=lifecycle.resume(self.root, host=self.host, **({"run": run} if run is not None else {})))
        if not self.config["enabled"]: return dict(outcome="disabled")
        self._freeze()
        with lifecycle._file_lock(self.root, COMMON + "/os-update/controller.lock"):
            state = read_state(self.root)
            if state["pending"] is not None: return dict(outcome="busy")
            for entry in self._releases():
                identity = entry["release_id"]
                if identity <= state["committed"]["release_id"] or identity in state["failed_versions"]: continue
                metadata, raw, signature = self._metadata(entry)
                try: self._admit_entry(entry, metadata)
                except Withdrawn: continue
                bundle = stage(self.root, metadata, raw, signature, entry["assets"][metadata["bundle"]["filename"]], host=self.host, http=self.http)
                break
            else: return dict(outcome="no-update")
        if not apply: return dict(outcome="staged", release_id=identity)
        result = lifecycle.start(self.root, bundle, raw, signature, host=self.host, **({"run": run} if run is not None else {}))
        return dict(outcome="trial-requested" if result["pending"] is not None else "source-retained", release_id=identity, state=result)


def run(root=Path("/"), *, host=None, http=None, service_run=None):
    try:
        # Construct the feed only after recovery: invalid optional network config must not strand pending state.
        if read_state(root)["pending"] is not None:
            return dict(outcome="resumed", state=lifecycle.resume(root, host=host, **({"run": service_run} if service_run is not None else {})))
        return Feed(root, host=host, http=http).poll(run=service_run)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, UpdateError) as exc:
        raise ValueError(f"OS_FEED_HOLD: {exc}") from exc
