"""D-512 live transports: CORE HTTPS (edge_drive.Core), key-only SSH, site Vision lease."""
from __future__ import annotations

import json
import os
import subprocess
import time
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

    def overhead(self):
        """One fresh Rosy Cam JPEG through a 60 s Viewer lease (D-318), None on any failure."""
        if not self.site_url:
            return None
        try:
            source = self.source or json.loads(self._site("/api/fleet/vision/sources"))["sources"][0]
            lease = json.loads(self._site("/api/fleet/vision/lease", {"source_id": source}))
            return self._site(lease["frame_path"], token=lease["lease"])
        except (OSError, ValueError, KeyError, IndexError):
            return None

    now = staticmethod(time.time)
    sleep = staticmethod(time.sleep)
