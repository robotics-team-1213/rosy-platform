"""The updater's GitHub list, rollout and staging (D-412; moved out of rosy_auto_update.py, D-798)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from signing import verify_signature
from auto_update_host import (BACKOFF_DEFAULT_S, BACKOFF_MAX_S, BACKOFF_MIN_S, Definitive, DISK_MARGIN_BYTES,
    MAX_LIST_BYTES, MAX_ROLLOUT_BYTES, MAX_SIG_BYTES, MAX_TARBALL_BYTES, _number, _outcome, parse_z, RELEASES,
    STAGE_BACKOFF_BASE_S, STAGE_MAX_DEFINITIVE, TAG, _tail, TRUSTED_KEY, UNPACK_TIMEOUT_S, UpdateError,
    VERIFY_TIMEOUT_S, _z)


class UpdaterStage:
    """Updater mixin: backoff, the release list, the signed rollout, staging and the rollout gate."""

    # GitHub --------------------------------------------------------------------------

    def _backoff(self, state: dict, headers: dict) -> _dt.datetime:
        now = self.host.now()
        delay = BACKOFF_DEFAULT_S
        retry = headers.get("retry-after", "")
        reset = headers.get("x-ratelimit-reset", "")
        if retry.isdigit():
            delay = int(retry)
        elif reset.isdigit() and headers.get("x-ratelimit-remaining") == "0":
            delay = int(reset) - int(now.timestamp())
        until = now + _dt.timedelta(seconds=min(max(delay, BACKOFF_MIN_S), BACKOFF_MAX_S))
        state["backoff_until"] = _z(until)
        return until

    def _releases(self, state: dict, repo: str) -> list[dict]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        # Legacy engines must never consume feature entries from our cache after downgrade.
        if (state.get("etag_v2") and isinstance(state.get("releases_v2"), list)
                and all(isinstance(entry, dict) and "delta" in entry for entry in state["releases_v2"])):
            headers["If-None-Match"] = state["etag_v2"]
        status, found, body = self.http.get(
            f"{self.api_base}/repos/{repo}/releases?per_page=20", headers, MAX_LIST_BYTES)
        if status == 304:
            return state["releases_v2"]
        if status in (403, 429):
            until = self._backoff(state, found)
            raise UpdateError(f"GITHUB_RATE_LIMITED: HTTP {status}; backing off until {_z(until)}")
        if status != 200:
            raise UpdateError(f"GITHUB_HTTP: HTTP {status}")
        try:
            listed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UpdateError("GITHUB_RESPONSE: not JSON") from exc
        if not isinstance(listed, list):
            raise UpdateError("GITHUB_RESPONSE: not a list")
        releases = []
        for item in listed:
            if not isinstance(item, dict) or item.get("draft") is not False or item.get("prerelease") is not False:
                continue
            match = TAG.fullmatch(str(item.get("tag_name", "")))
            if not match:
                continue
            release_id = match.group(1)
            urls = {asset.get("name"): asset.get("browser_download_url")
                    for asset in item.get("assets") or [] if isinstance(asset, dict)}
            wanted = {"tarball": f"{release_id}.tar.gz", "rollout": "rollout.json", "sig": "rollout.json.sig"}
            if not all(isinstance(urls.get(name), str) for name in wanted.values()):
                continue
            size = next((asset.get("size") for asset in item.get("assets") or []
                         if isinstance(asset, dict) and asset.get("name") == wanted["tarball"]), None)
            releases.append({"release_id": release_id, **{key: urls[name] for key, name in wanted.items()},
                             "size": size if _number(size) and size >= 0 else None,
                             "delta": urls.get(f"{release_id}.delta.tar.gz")})
        state["etag_v2"] = found.get("etag")
        state["releases_v2"] = releases
        return releases

    def _rollout(self, release: dict) -> dict:
        release_id = release["release_id"]
        status, _found, raw = self.http.get(release["rollout"], {"Accept": "application/octet-stream"},
                                            MAX_ROLLOUT_BYTES)
        sig_status, _found, signature = self.http.get(release["sig"], {"Accept": "application/octet-stream"},
                                                      MAX_SIG_BYTES)
        if status != 200 or sig_status != 200:
            raise UpdateError(f"ROLLOUT_HTTP: rollout {status}, signature {sig_status}")
        try:
            text = signature.decode("ascii")
        except UnicodeDecodeError as exc:
            raise Definitive("ROLLOUT_SIGNATURE: not ASCII") from exc
        rejections = verify_signature(raw, text, self.root / TRUSTED_KEY)
        if rejections:
            raise Definitive(f"ROLLOUT_SIGNATURE: {rejections[0].code}")
        try:
            rollout = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise Definitive("ROLLOUT_INVALID: not JSON") from exc
        if not isinstance(rollout, dict) or rollout.get("schema") != 1:
            raise Definitive("ROLLOUT_INVALID: schema 1 object required")
        canary = rollout.get("canary")
        checks = (
            rollout.get("release_id") == release_id,
            rollout.get("tarball") == f"{release_id}.tar.gz",
            isinstance(rollout.get("tarball_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", rollout["tarball_sha256"]) is not None,
            parse_z(rollout.get("published_at")) is not None,
            isinstance(canary, list) and all(isinstance(name, str) for name in canary),
            isinstance(rollout.get("canary_ok"), bool),
            isinstance(rollout.get("withdrawn"), bool),
            isinstance(rollout.get("wave_delay_s"), int) and not isinstance(rollout.get("wave_delay_s"), bool)
            and rollout["wave_delay_s"] >= 0,
        )
        if not all(checks):
            raise Definitive("ROLLOUT_INVALID: fields do not match the contract or this release")
        delta = rollout.get("delta")
        if delta is not None:
            hashes = ("sha256", "base_sums_sha256", "target_sums_sha256", "full_tarball_sha256")
            if (not isinstance(delta, dict) or delta.get("schema") != 1
                    or delta.get("tarball") != f"{release_id}.delta.tar.gz"
                    or not isinstance(delta.get("base_release_id"), str)
                    or re.fullmatch(r"\d{4}\.\d{2}\.\d{2}-\d{3}", delta["base_release_id"]) is None
                    or delta["base_release_id"] == release_id
                    or type(delta.get("size")) is not int or not 0 < delta["size"] <= MAX_TARBALL_BYTES
                    or any(not isinstance(delta.get(key), str)
                           or re.fullmatch(r"[0-9a-f]{64}", delta[key]) is None for key in hashes)
                    or delta["full_tarball_sha256"] != rollout["tarball_sha256"]):
                raise Definitive("ROLLOUT_DELTA_INVALID: signed transport binding is invalid")
        return rollout

    # staging --------------------------------------------------------------------------

    def _stage(self, state: dict, release: dict, rollout: dict) -> None:
        """Stage with per-release backoff; three definitive failures fail the id (review M5)."""
        release_id = release["release_id"]
        if state.get("staged") == release_id and Path(self.release_path(release_id)).is_dir():
            return
        errors = state.setdefault("stage_errors", {})
        record = errors.get(release_id)
        retry = parse_z((record or {}).get("retry_after"))
        if retry is not None and self.host.now() < retry:
            raise UpdateError(f"STAGE_BACKOFF: {release_id} last failed ({record.get('last')}); "
                              f"next attempt after {_z(retry)}")
        try:
            self._stage_once(state, release, rollout)
        except UpdateError as exc:
            if release_id not in (state.get("failed") or {}):
                self._stage_error(state, release_id, str(exc), isinstance(exc, Definitive))
            raise
        errors.pop(release_id, None)
        state["staged"] = release_id
        self._save_state(state)
        self._history("staged", release_id, "downloaded, unpacked and verified")

    def _stage_error(self, state: dict, release_id: str, message: str, definitive: bool) -> None:
        record = state.setdefault("stage_errors", {}).setdefault(release_id, {"attempts": 0, "definitive": 0})
        record["attempts"] += 1
        record["definitive"] += int(definitive)
        record["last"] = message
        delay = min(STAGE_BACKOFF_BASE_S * 2 ** (record["attempts"] - 1), BACKOFF_MAX_S)
        record["retry_after"] = _z(self.host.now() + _dt.timedelta(seconds=delay))
        if record["definitive"] >= STAGE_MAX_DEFINITIVE:
            self._mark_failed(state, release_id, f"staging failed {STAGE_MAX_DEFINITIVE} times: {message}")

    def _clean_downloads(self) -> Path:
        downloads = self.updates / "downloads"
        try:
            downloads.mkdir(parents=True, exist_ok=True)
            for leftover in downloads.iterdir():
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover)
                else:
                    leftover.unlink()
        except OSError as exc:
            raise UpdateError(f"DOWNLOADS_UNCLEAN: cannot clear {downloads}: {exc}") from exc
        return downloads

    def _delta_transport(self, release: dict, rollout: dict) -> dict | None:
        delta = rollout.get("delta")
        if delta is None:
            return None
        base_id = delta["base_release_id"]
        # A different/missing normal version uses the complete authenticated asset.
        if self.host.current_release() != base_id:
            return None
        base = Path(self.release_path(base_id))
        if not base.exists() and not base.is_symlink():
            return None
        if base.is_symlink() or not base.is_dir():
            raise Definitive("DELTA_BASE_INVALID: current base is not a plain release")
        checked = self.host.run(["python3", "-B", self._native("native_release.py"), "--root", str(self.root),
                                 "--public-key", self._dev(TRUSTED_KEY), "verify", "--release-id", base_id],
                                VERIFY_TIMEOUT_S)
        kind, error = _outcome(checked)
        if kind != "ok":
            raise Definitive(f"DELTA_BASE_UNVERIFIED: {error}") if kind == "definitive" else UpdateError(
                f"DELTA_BASE_VERIFY_TRANSIENT: {error}")
        if hashlib.sha256((base / "SHA256SUMS").read_bytes()).hexdigest() != delta["base_sums_sha256"]:
            raise Definitive("DELTA_BASE_MISMATCH: current base checksum identity differs")
        if self.host.current_release() != base_id:
            raise UpdateError("DELTA_BASE_CHANGED: current moved while verifying")
        if not isinstance(release.get("delta"), str):
            raise Definitive("DELTA_ASSET_MISSING: signed transport asset is absent")
        return delta

    def _stage_once(self, state: dict, release: dict, rollout: dict) -> None:
        release_id = release["release_id"]
        delta = None
        if not Path(self.release_path(release_id)).is_dir():
            delta = self._delta_transport(release, rollout)
            size = release.get("size") or 0
            need = 2 * size + DISK_MARGIN_BYTES
            free = self.host.free_bytes(self.root / RELEASES)
            if free < need:
                raise UpdateError(f"DISK_LOW: {free} bytes free, {need} needed for {release_id}")
            downloads = self._clean_downloads()
            part = downloads / f"{release_id}.tar.gz.part"
            tarball = downloads / f"{release_id}.tar.gz"
            try:
                digest = self.http.download(release["delta"] if delta else release["tarball"], part,
                                            delta["size"] if delta else MAX_TARBALL_BYTES)
            except UpdateError:
                part.unlink(missing_ok=True)
                raise
            if digest != (delta["sha256"] if delta else rollout["tarball_sha256"]) or (
                    delta and part.stat().st_size != delta["size"]):
                part.unlink(missing_ok=True)
                raise Definitive(f"TARBALL_SHA256_MISMATCH: {release_id} got {digest}")
            os.replace(part, tarball)
            environment = (["env", f"ROSY_DELTA_BASE_ID={delta['base_release_id']}",
                            f"ROSY_DELTA_BASE_SUMS={delta['base_sums_sha256']}",
                            f"ROSY_DELTA_TARGET_SUMS={delta['target_sums_sha256']}"] if delta else [])
            unpacked = self.host.run([*environment, "bash", self._native("rosy-release-unpack.sh"), release_id,
                                      str(tarball), self._dev(RELEASES)], UNPACK_TIMEOUT_S)
            tarball.unlink(missing_ok=True)  # the script removes it on success
            if unpacked.returncode != 0:
                error = f"UNPACK_FAILED: {_tail(unpacked.stderr or unpacked.stdout)}"
                raise UpdateError(error) if unpacked.returncode in (124, 127) else Definitive(error)
        verified = self.host.run(["python3", "-B", self._native("native_release.py"), "--root", str(self.root),
                                  "--public-key", self._dev(TRUSTED_KEY), "verify", "--release-id", release_id],
                                 VERIFY_TIMEOUT_S)
        kind, error = _outcome(verified)
        if kind == "definitive":
            # Review H3: only a JSON verdict from the verifier fails the release.
            self._mark_failed(state, release_id, f"verify: {error}")
            raise UpdateError(f"VERIFY_FAILED: {release_id}: {error}")
        if kind != "ok":
            raise UpdateError(f"VERIFY_TRANSIENT: {release_id}: {error}")
        if rollout.get("delta") is not None:
            sums = Path(self.release_path(release_id)) / "SHA256SUMS"
            if hashlib.sha256(sums.read_bytes()).hexdigest() != rollout["delta"]["target_sums_sha256"]:
                raise Definitive("DELTA_TARGET_MISMATCH: full target checksum identity differs")

    def _gate(self, rollout: dict) -> str | None:
        if self.host.hostname() in rollout["canary"]:
            return None
        if not rollout["canary_ok"]:
            return "waiting for the canary (canary_ok is false)"
        due = parse_z(rollout["published_at"]) + _dt.timedelta(seconds=rollout["wave_delay_s"])
        if self.host.now() < due:
            return f"wave delay until {_z(due)}"
        return None
