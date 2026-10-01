"""D-341 1-8: the in-memory pairing state machine over the real SQLite store."""

from __future__ import annotations

import sqlite3

import pytest
from core_common.protocol import pairing
from fleet.server.pairing import PairingError, PairingService
from fleet.server.pairing_store import PairingStore
from pairing_fixtures import (
    LEAF_PEM,
    LEAF_SHA256,
    SITE_CA_PEM,
    TLS_HOST,
    FakeClock,
    Phone,
)

SOURCES = {"ceiling_north": "paired", "ceiling_south": "paired", "bench_static": "static"}


def _service(tmp_path, clock=None, **kwargs) -> tuple[PairingService, PairingStore, FakeClock]:
    clock = clock or FakeClock()
    store = PairingStore(tmp_path / "fleet.sqlite3", clock=clock.wall)
    service = PairingService(store, leaf_cert_sha256=LEAF_SHA256, site_ca_pem=SITE_CA_PEM,
                             tls_host=TLS_HOST, site_name="Rosy Lab", sources=SOURCES,
                             monotonic=clock.monotonic, wall=clock.wall, **kwargs)
    return service, store, clock


def _revealed(service, phone=None):
    phone = phone or Phone()
    created = service.create(phone.request_bytes())
    service.reveal(created["request_id"], phone.bearer, phone.reveal_bytes())
    return phone, created


def _approved(service, clock, source="ceiling_north"):
    phone, created = _revealed(service)
    code = phone.code(created["request_id"], created["server_nonce"])
    approval = service.approve(created["request_id"], code=code, source_id=source,
                               principal_id="alice")
    return phone, created, approval


def _status(call) -> PairingError:
    with pytest.raises(PairingError) as caught:
        call()
    return caught.value


def test_request_has_no_side_effect_but_one_pending_row_in_memory(tmp_path):
    service, store, _ = _service(tmp_path)
    created = service.create(Phone().request_bytes())

    assert set(created) == {"request_id", "server_nonce", "expires_at"}
    assert pairing.SECRET_PATTERN.fullmatch(created["server_nonce"])
    assert store.credential_rows() == []
    assert [row["state"] for row in service.pending_listing()["requests"]] == ["pending"]
    # Unauthenticated requests are counted in memory and never reach the audit table,
    # so anonymous traffic cannot evict operator rows (security review finding 1).
    assert store.audit_rows() == []
    assert service.pending_listing()["unauthenticated_requests"] == 1


def test_fleet_restart_forgets_pending_requests(tmp_path):
    service, _, clock = _service(tmp_path)
    created = service.create(Phone().request_bytes())
    restarted, _, _ = _service(tmp_path, clock)

    assert restarted.pending_listing()["requests"] == []
    assert _status(lambda: restarted.poll(created["request_id"], "Bearer x")).status == 404


@pytest.mark.parametrize("body, reason", [
    (lambda phone: phone.request_bytes(role="robot"), "role"),
    (lambda phone: phone.request_bytes(proto="rosy-pair/2"), "proto"),
    (lambda phone: phone.request_bytes(extra="x"), "unknown_field"),
    (lambda phone: phone.request_bytes(device_label="z" * 4100), "too_large"),
])
def test_malformed_requests_are_400_with_the_vector_reason(tmp_path, body, reason):
    service, _, _ = _service(tmp_path)
    error = _status(lambda: service.create(body(Phone())))
    assert (error.status, error.body()["reason"]) == (400, reason)


def test_site_wide_pending_limit_is_429_and_keeps_existing_requests(tmp_path):
    service, _, _clock = _service(tmp_path)
    first = [service.create(Phone().request_bytes())["request_id"] for _ in range(16)]
    error = _status(lambda: service.create(Phone().request_bytes()))

    assert error.status == 429 and error.retry_after is not None
    assert [row["request_id"] for row in service.pending_listing()["requests"]] == first


def test_site_wide_rate_limit_is_30_per_minute(tmp_path):
    service, _, clock = _service(tmp_path)
    for index in range(30):
        created = service.create(Phone().request_bytes())
        service.reject(created["request_id"], principal_id="alice")
        clock.advance(0.5)
    error = _status(lambda: service.create(Phone().request_bytes()))
    assert error.status == 429
    clock.advance(60)
    assert service.create(Phone().request_bytes())["request_id"]


def test_poll_needs_the_poll_secret_and_two_seconds_between_reads(tmp_path):
    service, _, clock = _service(tmp_path)
    phone = Phone()
    created = service.create(phone.request_bytes())
    request_id = created["request_id"]

    assert _status(lambda: service.poll(request_id, "Bearer " + Phone().poll)).status == 401
    assert service.poll(request_id, phone.bearer) == {"state": "pending"}
    assert _status(lambda: service.poll(request_id, phone.bearer)).status == 429
    clock.advance(2.0)
    assert service.poll(request_id, phone.bearer) == {"state": "pending"}


def test_reveal_checks_the_commit_and_drops_the_server_nonce(tmp_path):
    service, _, _ = _service(tmp_path)
    phone = Phone()
    created = service.create(phone.request_bytes())
    liar = Phone(poll=phone.poll)
    error = _status(lambda: service.reveal(created["request_id"], phone.bearer, liar.reveal_bytes()))
    assert (error.status, error.code) == (400, "COMMIT_MISMATCH")
    assert service.pending_listing()["requests"] == []

    phone, created = _revealed(service)
    entry = service._requests[created["request_id"]]
    assert entry.server_nonce is None and entry.client_commit is None
    assert entry.code_mac is not None and phone.client_nonce not in repr(entry)


def test_unrevealed_and_expired_requests_cannot_be_approved(tmp_path):
    service, _, clock = _service(tmp_path)
    phone = Phone()
    created = service.create(phone.request_bytes())
    error = _status(lambda: service.approve(created["request_id"], code="000000",
                                            source_id="ceiling_north", principal_id="alice"))
    assert (error.status, error.code) == (409, "NOT_REVEALED")

    service.reveal(created["request_id"], phone.bearer, phone.reveal_bytes())
    clock.advance(301)
    code = phone.code(created["request_id"], created["server_nonce"])
    error = _status(lambda: service.approve(created["request_id"], code=code,
                                            source_id="ceiling_north", principal_id="alice"))
    assert error.status == 410
    assert service.poll(created["request_id"], phone.bearer) == {"state": "expired"}


def test_three_wrong_codes_close_the_request(tmp_path):
    service, store, _ = _service(tmp_path)
    phone, created = _revealed(service)
    right = phone.code(created["request_id"], created["server_nonce"])
    wrong = f"{(int(right) + 1) % 1_000_000:06d}"
    for left in (2, 1, 0):
        error = _status(lambda: service.approve(created["request_id"], code=wrong,
                                                source_id="ceiling_north", principal_id="alice"))
        assert (error.status, error.code, error.body()["attempts_left"]) == (409, "CODE_MISMATCH", left)
    error = _status(lambda: service.approve(created["request_id"], code=right,
                                            source_id="ceiling_north", principal_id="alice"))
    assert error.status == 410
    assert store.audit_rows()[-1]["outcome"] in {"closed", "refused"}
    assert any(row["outcome"] == "closed" for row in store.audit_rows())


def test_a_relayed_leaf_gives_a_code_the_operator_cannot_match(tmp_path):
    service, _, _ = _service(tmp_path)
    phone, created = _revealed(service)
    relayed = phone.code(created["request_id"], created["server_nonce"],
                         leaf_sha256=pairing.sha256_text("middlebox"))
    error = _status(lambda: service.approve(created["request_id"], code=relayed,
                                            source_id="ceiling_north", principal_id="alice"))
    assert error.code == "CODE_MISMATCH"


def test_static_and_unknown_sources_are_not_approval_targets(tmp_path):
    service, _, _ = _service(tmp_path)
    phone, created = _revealed(service)
    code = phone.code(created["request_id"], created["server_nonce"])
    for source, status in (("bench_static", 409), ("nowhere", 404)):
        error = _status(lambda: service.approve(created["request_id"], code=code, source_id=source,
                                                principal_id="alice"))
        assert error.status == status
    # Refused sources do not burn code attempts.
    assert service.pending_listing()["requests"][0]["attempts_left"] == 3


def test_full_flow_delivers_the_token_once_and_activates_only_on_confirm(tmp_path):
    service, store, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    request_id = created["request_id"]

    assert approval["site_ca_fingerprint"] == pairing.site_fingerprint(SITE_CA_PEM)
    assert service.sync_listing() == []
    result = service.poll(request_id, phone.bearer)
    assert result["state"] == "approved"
    body = result["result"]
    assert pairing.validate_result(body) is None
    assert (body["source_id"], body["tls_host"], body["credential_id"]) == (
        "ceiling_north", TLS_HOST, approval["credential_id"])
    clock.advance(2)
    assert _status(lambda: service.poll(request_id, phone.bearer)).status == 410
    assert service.sync_listing() == []

    confirmed = service.confirm(request_id, phone.bearer, approval["credential_id"])
    assert confirmed == {"state": "confirmed", "credential_id": approval["credential_id"]}
    listing = service.sync_listing()
    assert listing == [{"credential_id": approval["credential_id"], "source_id": "ceiling_north",
                        "token_sha256": pairing.sha256_text(body["token"]),
                        "expires_at": body["expires_at"]}]
    lifetime = store.credential_rows()[0]["expires_at"] - store.credential_rows()[0]["created_at"]
    assert lifetime == pytest.approx(180 * 86400)


def test_confirm_needs_delivery_and_the_matching_credential(tmp_path):
    service, _, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    request_id = created["request_id"]
    error = _status(lambda: service.confirm(request_id, phone.bearer, approval["credential_id"]))
    assert (error.status, error.code) == (409, "NOT_DELIVERED")
    service.poll(request_id, phone.bearer)
    error = _status(lambda: service.confirm(request_id, phone.bearer, "cred-other"))
    assert error.code == "CREDENTIAL_MISMATCH"


def test_unconfirmed_approval_is_revoked_after_120_seconds(tmp_path):
    service, store, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    service.poll(created["request_id"], phone.bearer)
    clock.advance(121)

    error = _status(lambda: service.confirm(created["request_id"], phone.bearer,
                                            approval["credential_id"]))
    assert error.status == 410
    assert store.credential_rows()[0]["state"] == "revoked"
    assert store.credential_rows()[0]["revoke_reason"] == "unconfirmed"
    assert service.sync_listing() == []
    # The source is free again.
    _approved(service, clock)


def test_one_active_credential_per_paired_source(tmp_path):
    service, _, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    service.poll(created["request_id"], phone.bearer)
    service.confirm(created["request_id"], phone.bearer, approval["credential_id"])

    second, created2 = _revealed(service)
    code = second.code(created2["request_id"], created2["server_nonce"])
    error = _status(lambda: service.approve(created2["request_id"], code=code,
                                            source_id="ceiling_north", principal_id="alice"))
    assert (error.status, error.code) == (409, "SOURCE_HAS_CREDENTIAL")

    service.revoke(approval["credential_id"], principal_id="alice")
    assert service.sync_listing() == []
    assert service.approve(created2["request_id"], code=code, source_id="ceiling_north",
                           principal_id="alice")["source_id"] == "ceiling_north"


def test_revoke_unknown_and_twice(tmp_path):
    service, _, clock = _service(tmp_path)
    assert _status(lambda: service.revoke("cred-none", principal_id="alice")).status == 404
    phone, created, approval = _approved(service, clock)
    service.revoke(approval["credential_id"], principal_id="alice")
    assert _status(lambda: service.revoke(approval["credential_id"],
                                          principal_id="alice")).status == 409
    # A revoked approval is no longer deliverable.
    assert service.poll(created["request_id"], phone.bearer) == {"state": "rejected"}


def test_expired_credentials_leave_the_vision_list(tmp_path):
    service, _, clock = _service(tmp_path, credential_lifetime_s=10)
    phone, created, approval = _approved(service, clock)
    service.poll(created["request_id"], phone.bearer)
    service.confirm(created["request_id"], phone.bearer, approval["credential_id"])
    assert len(service.sync_listing()) == 1
    clock.advance(11)
    assert service.sync_listing() == []
    summary = service.credentials_summary()["credentials"][0]
    assert summary["expired"] is True and "token_sha256" not in summary


def test_restart_revokes_approvals_that_were_never_confirmed(tmp_path):
    service, store, clock = _service(tmp_path)
    _approved(service, clock)
    _service(tmp_path, clock)
    assert store.credential_rows()[0]["state"] == "revoked"
    assert store.credential_rows()[0]["revoke_reason"] == "fleet_restart"


def test_the_database_never_holds_tokens_secrets_nonces_or_codes(tmp_path):
    service, store, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    code = phone.code(created["request_id"], created["server_nonce"])
    token = service.poll(created["request_id"], phone.bearer)["result"]["token"]
    service.confirm(created["request_id"], phone.bearer, approval["credential_id"])

    texts = []
    with sqlite3.connect(store.path) as connection:
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in connection.execute(f"SELECT * FROM {table}"):
                texts.extend(value for value in row if isinstance(value, str))
    raw = store.path.read_bytes()
    for secret in (token, phone.poll, phone.client_nonce, created["server_nonce"]):
        assert secret.encode() not in raw
        assert not any(secret in text for text in texts)
    assert not any(code in text for text in texts)


def test_audit_reuses_device_pairing_audit_with_explicit_device_kind(tmp_path):
    from fleet.server.enrollment_store import EnrollmentStore

    service, store, clock = _service(tmp_path)
    _phone, _created, approval = _approved(service, clock)
    service.reject(service.create(Phone().request_bytes())["request_id"], principal_id="bob")
    enrollment = EnrollmentStore(store.path)
    enrollment.audit(action="enroll", outcome="enrolled", principal_id="alice", target="rosy_09",
                     device_kind="robot")

    rows = enrollment.audit_rows()
    kinds = {row["device_kind"] for row in rows}
    assert kinds == {"overhead-camera", "robot"}
    approve = next(row for row in rows if row["action"] == "approve")
    assert (approve["principal_id"], approve["target"]) == ("alice", approval["credential_id"])
    assert any(row["action"] == "reject" and row["principal_id"] == "bob" for row in rows)


def test_audit_is_bounded(tmp_path):
    store = PairingStore(tmp_path / "fleet.sqlite3", audit_limit=5)
    for index in range(9):
        store.audit(action="request", outcome="pending", principal_id=None, target=f"r{index}",
                    device_kind="overhead-camera")
    assert [row["target"] for row in store.audit_rows()] == [f"r{index}" for index in range(4, 9)]


def test_site_ca_must_be_a_ca_and_tls_host_a_local_name(tmp_path):
    store = PairingStore(tmp_path / "fleet.sqlite3")
    common = {"leaf_cert_sha256": LEAF_SHA256, "site_name": "Rosy Lab", "sources": SOURCES}
    with pytest.raises(ValueError, match="CA"):
        PairingService(store, site_ca_pem=LEAF_PEM, tls_host=TLS_HOST, **common)
    with pytest.raises(ValueError, match="tls_host"):
        PairingService(store, site_ca_pem=SITE_CA_PEM, tls_host="192.168.1.102", **common)
    with pytest.raises(ValueError, match="leaf"):
        PairingService(store, site_ca_pem=SITE_CA_PEM, tls_host=TLS_HOST,
                       **{**common, "leaf_cert_sha256": "nope"})


def test_pending_listing_shows_no_code_or_secret(tmp_path):
    service, _, _ = _service(tmp_path)
    phone, created = _revealed(service)
    listing = service.pending_listing()
    row = listing["requests"][0]
    assert row["state"] == "revealed" and row["device_label"] == phone.label
    assert listing["paired_sources"] == [
        {"source_id": "ceiling_north", "has_credential": False},
        {"source_id": "ceiling_south", "has_credential": False}]
    assert listing["site_ca_fingerprint"] == pairing.site_fingerprint(SITE_CA_PEM)
    text = repr(listing)
    for secret in (phone.poll, phone.client_nonce, created["server_nonce"],
                   phone.code(created["request_id"], created["server_nonce"])):
        assert secret not in text


def test_concurrent_approvals_issue_exactly_one_credential(tmp_path):
    """Sync FastAPI routes run on a thread pool: the state machine must serialise them."""
    import threading

    service, store, _clock = _service(tmp_path)
    phone, created = _revealed(service)
    code = phone.code(created["request_id"], created["server_nonce"])
    barrier = threading.Barrier(8)
    outcomes = []

    def approve():
        barrier.wait()
        try:
            service.approve(created["request_id"], code=code, source_id="ceiling_north",
                            principal_id="alice")
            outcomes.append("approved")
        except PairingError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=approve) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("approved") == 1
    assert len(store.credential_rows()) == 1



def test_anonymous_request_flood_never_evicts_audit_rows_and_refusals_are_counted(tmp_path):
    service, store, _ = _service(tmp_path)
    store.audit(action="approve", outcome="ok", principal_id="op", target="cred-x",
                device_kind="overhead-camera")
    refused = 0
    for _ in range(40):
        try:
            service.create(Phone().request_bytes())
        except Exception:
            refused += 1
    assert [row["action"] for row in store.audit_rows()] == ["approve"]
    listing = service.pending_listing()
    assert listing["refused_requests"] == refused > 0


def test_request_repr_hides_nonces_and_poll_digest(tmp_path):
    service, _, _ = _service(tmp_path)
    created = service.create(Phone().request_bytes())
    entry = service._requests[created["request_id"]]
    text = repr(entry)
    assert created["server_nonce"] not in text and entry.poll_sha256 not in text


def test_a_repeated_confirm_with_the_same_id_is_idempotent_inside_the_window(tmp_path):
    # rosy-84 client review: if the first 200 is lost, the phone must learn the credential is live.
    service, store, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    request_id, cred = created["request_id"], approval["credential_id"]
    service.poll(request_id, phone.bearer)
    first = service.confirm(request_id, phone.bearer, cred)
    clock.advance(2)
    again = service.confirm(request_id, phone.bearer, cred)
    assert again == first == {"state": "confirmed", "credential_id": cred}
    assert [row["action"] for row in store.audit_rows()].count("confirm") == 1


def test_a_repeated_confirm_is_refused_after_the_window_a_revoke_or_with_another_id(tmp_path):
    service, store, clock = _service(tmp_path)
    phone, created, approval = _approved(service, clock)
    request_id, cred = created["request_id"], approval["credential_id"]
    service.poll(request_id, phone.bearer)
    service.confirm(request_id, phone.bearer, cred)
    assert _status(lambda: service.confirm(request_id, phone.bearer, "cred-other")).status == 410
    assert _status(lambda: service.confirm(request_id, "Bearer wrong", cred)).status == 401
    service.revoke(cred, principal_id="alice")
    assert _status(lambda: service.confirm(request_id, phone.bearer, cred)).status == 410

    service2, _, clock2 = _service(tmp_path / "late")
    phone2, created2, approval2 = _approved(service2, clock2)
    service2.poll(created2["request_id"], phone2.bearer)
    service2.confirm(created2["request_id"], phone2.bearer, approval2["credential_id"])
    clock2.advance(121)
    assert _status(lambda: service2.confirm(created2["request_id"], phone2.bearer,
                                            approval2["credential_id"])).status == 410
