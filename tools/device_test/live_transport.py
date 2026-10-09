"""D-512 live transports: CORE HTTPS (edge_drive.Core), key-only SSH, site Vision lease."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import edge_drive


class Live:
    """The real transports: CORE over one kept-alive HTTPS connection (edge_drive.Core),
    key-only SSH as rosy (rosy-device-access skill) and the site Vision lease."""

    def __init__(self, args):
        self.core = edge_drive.Core(args.host, Path(args.token_file).read_text(encoding="utf-8").strip(),
                                    args.port, edge_drive.tls_context(args.ca_file, args.insecure),
                                    # the certificate names the robot; --host may be its address
                                    tls_host=f"{args.robot}.local" if args.ca_file else None)
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Rosy"
        self.ssh_argv = ["ssh", "-i", str(base / "ssh" / "rosy-operator-ed25519"), "-o", "IdentitiesOnly=yes",
                         "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
                         "-o", "KbdInteractiveAuthentication=no", "-o", "StrictHostKeyChecking=accept-new",
                         "-o", f"UserKnownHostsFile={base / 'known_hosts'}", "-o", "ConnectTimeout=5",
                         f"rosy@{args.host}"]
        self.site_url, self.source = args.site_url, args.overhead_source
        self.site_ctx = edge_drive.tls_context(args.site_ca_file, args.site_insecure) if args.site_url else None

    def ssh(self, command, stdin=b""):
        """(rc, stdout bytes); stdout stays bytes so file contents round-trip exactly."""
        try:
            p = subprocess.run(self.ssh_argv + [command], input=stdin, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return 124, b""
        return p.returncode, p.stdout

    def _site(self, path, body=None, token=None):
        req = urllib.request.Request(self.site_url.rstrip("/") + path, method="POST" if body else "GET",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": "Bearer " + token} if token else {})})
        with urllib.request.urlopen(req, timeout=5, context=self.site_ctx) as r:
            return r.read()

    def overhead_source(self):
        """--overhead-source, else the site's first Vision source; None when unknown."""
        try:
            return self.source or json.loads(self._site("/api/fleet/vision/sources"))["sources"][0]
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            return None

    @staticmethod
    def _site_token():
        """Site viewer credential for read-guarded Fleet routes, from ROSY_SITE_TOKEN_FILE (None: unset)."""
        path = os.environ.get("ROSY_SITE_TOKEN_FILE")
        return Path(path).read_text(encoding="utf-8").strip() if path else None

    def calibrations(self):
        """Approved camera-to-map records (D-457 GET /api/fleet/calibrations), None on any failure."""
        try:
            return json.loads(self._site("/api/fleet/calibrations", token=self._site_token()))["calibrations"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def active_site_map_id(self):
        """The Fleet active SiteMap's map_id (GET /api/fleet/site-map/active), None on any failure."""
        try:
            return json.loads(self._site("/api/fleet/site-map/active", token=self._site_token()))["map"]["map_id"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    _lease = None  # (frame_path, token, reuse-until) of the current Viewer lease

    def overhead(self):
        """One fresh Rosy Cam JPEG through a 60 s Viewer lease (D-318), None on any failure.

        The lease is reused while it is valid and a 429 is retried twice: the identify
        check grabs a frame every 0.2 s, and one lease per frame tripped Vision's rate
        limit, refusing the whole check (2026-10-09)."""
        if not self.site_url:
            return None
        for attempt in range(3):
            try:
                if self._lease is None or self.now() >= self._lease[2]:
                    source = self.overhead_source()
                    body = json.loads(self._site("/api/fleet/vision/lease", {"source_id": source}))
                    ttl = float(body.get("expires_in_s", 60))
                    self._lease = (body["frame_path"], body["lease"], self.now() + max(0.0, ttl - 10))
                return self._site(self._lease[0], token=self._lease[1])
            except urllib.error.HTTPError as exc:
                if exc.code == 401 or exc.code == 403:
                    self._lease = None  # an expired or revoked lease: take a new one
                elif exc.code != 429:
                    return None
                self.sleep(0.3 * (attempt + 1))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                return None
        return None

    now = staticmethod(time.time)
    sleep = staticmethod(time.sleep)
