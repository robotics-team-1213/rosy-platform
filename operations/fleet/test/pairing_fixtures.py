"""Shared D-341 pairing test material: public fixture certificates and a phone-side helper.

Certificates come from the public site-link vector; no private key exists in the tree.
Phone secrets are generated per test run so no credential literal lands in the source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core_common.protocol import pairing

FIXTURES = Path(__file__).resolve().parents[3] / "test/fixtures/protocol"
_SITE_LINK = {case["id"]: case for case in json.loads(
    (FIXTURES / "site-link.v1.json").read_text(encoding="utf-8"))["cases"]}
SITE_CA_PEM = _SITE_LINK["overhead_camera_with_credential_ref"]["record"]["ca_pem"]
LEAF_PEM = _SITE_LINK["ca_pem_is_leaf"]["record"]["ca_pem"]
LEAF_SHA256 = pairing.der_sha256(LEAF_PEM)
TLS_HOST = "fixture-site.local"


class FakeClock:
    """Monotonic and wall clocks that move only when a test says so."""

    def __init__(self, start: float = 1_000.0, wall: float = 1_790_000_000.0) -> None:
        self.now = start
        self.wall_offset = wall - start

    def monotonic(self) -> float:
        return self.now

    def wall(self) -> float:
        return self.now + self.wall_offset

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Phone:
    """What a Rosy Cam phone keeps during one pairing attempt."""

    label: str = "Galaxy S21 ceiling"
    client_nonce: str = field(default_factory=pairing.new_secret)
    poll: str = field(default_factory=pairing.new_secret)

    def request_body(self, **changes) -> dict:
        body = {"proto": pairing.PROTO, "role": pairing.ROLE, "device_label": self.label,
                "app_version": "0.4.0", "client_commit": pairing.commit(self.client_nonce),
                "poll_secret_sha256": pairing.sha256_text(self.poll)}
        body.update(changes)
        return body

    def request_bytes(self, **changes) -> bytes:
        return json.dumps(self.request_body(**changes)).encode("utf-8")

    def reveal_bytes(self) -> bytes:
        return json.dumps({"client_nonce": self.client_nonce}).encode("utf-8")

    def code(self, request_id: str, server_nonce: str, leaf_sha256: str = LEAF_SHA256) -> str:
        return pairing.confirmation_code(role=pairing.ROLE, request_id=request_id,
                                         leaf_cert_sha256=leaf_sha256,
                                         client_nonce=self.client_nonce, server_nonce=server_nonce)

    @property
    def bearer(self) -> str:
        return "Bearer " + self.poll
