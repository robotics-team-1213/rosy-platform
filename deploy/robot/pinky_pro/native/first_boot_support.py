"""Pure CORE overlay construction shared with the first-boot applicator."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def apply_time_source(source, path, write_atomic, *, restart: bool) -> None:
    """D-859: follow the site NTP server named on the card; a clock problem never holds provisioning."""
    if not source:
        return
    here = Path(__file__).resolve().parent
    # Installed image: beside this file. Source tree: deploy/hosts/common.
    sys.path[:0] = [str(here), str(here.parents[2] / "hosts/common")]
    try:
        from rosy_time_sync import configuration
        write_atomic(path, configuration("client", [source], []), 0o644)
        if restart:  # before rosy-runtime.target, so the makestep window precedes any workload
            subprocess.run(["systemctl", "restart", "--no-block", "chrony.service"], check=False, timeout=30)
    except (ImportError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"rosy-first-boot: time source not applied: {exc}", file=sys.stderr)


def merge_core_overlay(text: str | None, record: dict, fleet_bootstrap: dict | None = None) -> str:
    """Return CORE's overlay with the card's record as its only credential.

    Other overlay keys are kept. The overlay's auth.tokens list replaces the
    package default list as a whole, which is what shuts the shared
    rosy-dev-* credentials out. A credential that is not this card's own
    (another id, or CORE's legacy plaintext map) holds provisioning: first
    boot never decides what to do with a credential it did not issue.
    """
    import yaml  # python3-yaml ships in the image; only this step needs it.

    overlay: dict = {}
    if text is not None:
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ValueError("CORE config overlay is unreadable") from exc
        if not isinstance(loaded, dict):
            raise ValueError("CORE config overlay is not a mapping")
        overlay = loaded
    auth = overlay.get("auth", {})
    if auth is None:
        auth = {}
    if not isinstance(auth, dict):
        raise ValueError("CORE config overlay auth is not a mapping")
    records = auth.get("tokens") or []
    if not isinstance(records, list) or any(
            not isinstance(item, dict) or item.get("id") != record["id"] for item in records):
        raise ValueError("CORE config overlay already holds another API credential")
    # D-193 5: the card's credential is listed (and whoami answers) as `card`.
    overlay["auth"] = {**auth, "tokens": [{**record, "source": "card"}]}
    if fleet_bootstrap and fleet_bootstrap.get("account_trust"):
        overlay["auth"]["account_trust"] = fleet_bootstrap["account_trust"]  # D-992, validated with the bundle
    if fleet_bootstrap:
        try:
            endpoint = urlsplit(fleet_bootstrap.get("endpoint", ""))
        except ValueError:
            endpoint = urlsplit("")
        hostname = (endpoint.hostname or "").lower()
        profile = fleet_bootstrap.get("trust_profile", "")
        if (endpoint.scheme == "https" and hostname.endswith(".local")
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local", hostname)
                and isinstance(profile, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", profile)):
            fleet = overlay.get("fleet") or {}
            if not isinstance(fleet, dict):
                raise ValueError("CORE config overlay fleet is not a mapping")
            # The SD's one-time pairing_credential is never an Agent token.
            fleet["discovery"] = {
                "expected_hostname": hostname,
                "ca_file": f"/etc/rosy/trust/{profile}.crt",
            }
            overlay["fleet"] = fleet
    return yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False)
