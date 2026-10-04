"""D-368 driver MJPEG stream: route contract on a real CoreServices (SOURCE tier).

Judged here: auth 401, driver-only 409 (no seat lease, D-460), single stream,
new-sequence-only parts, and the slot following the current driver.
Mid-stream eviction and disconnect release are pinned in
``middleware/core/services/test/test_vision_stream_gate.py`` (the TestClient
portal serialises requests, so an in-band seat change cannot be replayed here).
fps/latency belong to ROS-SIM/DEVICE, not this file.
"""

import time

from core_common.identity import SOFTWARE_VERSION  # noqa: F401  (import sanity)


def _jpeg(n: int) -> bytes:
    return b"\xff\xd8" + bytes([64 + (n % 26)]) * 24 + b"\xff\xd9"


def _publish(svc, n: int) -> None:
    svc.vision.publish(_jpeg(n), captured_at=time.monotonic() + n,
                       frame_id=f"stream-test-{n}", source="STREAMTEST",
                       width=320, height=240)


def _drive(tc, svc, headers):
    svc.state.set_velocity(0.0, 0.0)  # a live base for the teleop write gate
    assert tc.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=headers).status_code == 200
    assert tc.post("/api/v1/teleop", json={"linear": 0.05, "angular": 0.0},
                   headers=headers).status_code == 200


def test_stream_requires_authentication(core_client):
    tc, _svc = core_client()
    assert tc.get("/api/v1/vision/front/stream").status_code == 401


def test_stream_refuses_anyone_before_an_accepted_teleop(core_client):
    tc, svc = core_client()
    response = tc.get("/api/v1/vision/front/stream",
                      headers={"Authorization": "Bearer rosy-dev-operator"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAMERA_STREAM_NOT_DRIVER"
    assert svc.vision_stream.stream_owner() is None


def test_teleop_acceptance_makes_the_caller_the_stream_driver(core_client):
    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    _drive(tc, svc, operator)
    driver = svc.vision_stream.driver()
    assert driver is not None
    # Stable opaque id, never the bearer secret (D-193/D-30).
    assert "rosy-dev-operator" not in str(driver)


def test_stream_parts_carry_only_new_sequences_and_seat_change_ends(core_client):
    """The multipart generator directly: part shape, new-sequence-only, eviction.

    The TestClient portal cannot replay a seat change while an infinite
    response is open, so the generator is iterated here instead of over HTTP;
    auth/409 mapping is covered by the plain-GET tests above.
    """
    import asyncio

    from core_api_web.api.deps import AuthContext
    from core_api_web.api.v1 import vision as vision_routes

    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    _drive(tc, svc, operator)
    driver = svc.vision_stream.driver()
    _publish(svc, 1)
    response = asyncio.run(
        vision_routes.stream_front_camera(auth=AuthContext(driver, "operator"), svc=svc))
    assert response.media_type.startswith("multipart/x-mixed-replace")
    assert response.headers["cache-control"] == "no-store"

    async def scenario():
        out = b""
        async for chunk in response.body_iterator:
            out += chunk
            if b"X-Rosy-Camera-Sequence: 1\r\n" in out:
                break
        assert b"Content-Type: image/jpeg\r\n" in out
        assert _jpeg(1) in out

        _publish(svc, 2)
        async for chunk in response.body_iterator:
            out += chunk
            if b"X-Rosy-Camera-Sequence: 2\r\n" in out:
                break
        # No repeats: sequence 1 was served exactly once.
        assert out.count(b"X-Rosy-Camera-Sequence: 1\r\n") == 1
        assert _jpeg(2) in out

        # A new accepted teleop is a seat change: the generator returns.
        svc.vision_stream.on_teleop("another-driver")
        async for _chunk in response.body_iterator:
            pass
        return out

    asyncio.run(scenario())
    # The finally clause released the slot on the way out.
    assert svc.vision_stream.stream_owner() is None


def test_stream_generator_close_releases_the_slot(core_client):
    """Client disconnect: closing the iterator runs the release path."""
    import asyncio

    from core_api_web.api.deps import AuthContext
    from core_api_web.api.v1 import vision as vision_routes

    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    _drive(tc, svc, operator)
    driver = svc.vision_stream.driver()
    _publish(svc, 1)
    response = asyncio.run(
        vision_routes.stream_front_camera(auth=AuthContext(driver, "operator"), svc=svc))
    assert svc.vision_stream.stream_owner() == driver

    async def pull_one_and_close():
        async for _chunk in response.body_iterator:
            break
        await response.body_iterator.aclose()

    asyncio.run(pull_one_and_close())
    assert svc.vision_stream.stream_owner() is None


def test_stream_refuses_while_another_stream_holds_the_slot(core_client):
    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    _drive(tc, svc, operator)
    # Simulate a stream already open from another connection (gate-level).
    driver = svc.vision_stream.driver()
    svc.vision_stream.open(driver)
    try:
        response = tc.get("/api/v1/vision/front/stream", headers=operator)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CAMERA_STREAM_BUSY"
    finally:
        svc.vision_stream.close(driver)


def test_stream_follows_the_current_driver_after_a_seat_change(core_client):
    import asyncio

    from core_api_web.api.deps import AuthContext
    from core_api_web.api.v1 import vision as vision_routes

    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    admin = {"Authorization": "Bearer rosy-dev-admin"}
    _drive(tc, svc, operator)
    previous_driver = svc.vision_stream.driver()
    _publish(svc, 1)
    first = asyncio.run(vision_routes.stream_front_camera(
        auth=AuthContext(previous_driver, "operator"), svc=svc))
    assert first.media_type.startswith("multipart/x-mixed-replace")

    # Another operator's accepted teleop is a seat change (D-411/D-460).
    _drive(tc, svc, admin)
    assert svc.vision_stream.driver() != previous_driver
    # The previous driver is refused over HTTP; the new driver gets the stream.
    refused = tc.get("/api/v1/vision/front/stream", headers=operator)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CAMERA_STREAM_NOT_DRIVER"
    _publish(svc, 2)
    handover = asyncio.run(vision_routes.stream_front_camera(
        auth=AuthContext(svc.vision_stream.driver(), "administrator"), svc=svc))
    assert handover.media_type.startswith("multipart/x-mixed-replace")
    asyncio.run(_close_after_start(first))
    asyncio.run(_close_after_start(handover))
    assert svc.vision_stream.stream_owner() is None


async def _close_after_start(response) -> None:
    """Start the generator (so `finally` owns it), then close: client disconnect."""
    async for _chunk in response.body_iterator:
        break
    await response.body_iterator.aclose()


def test_spectator_polling_path_is_unchanged(core_client):
    """D-368 section 2: non-drivers keep the 0.4 s polling route, not the stream."""
    tc, svc = core_client()
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    _drive(tc, svc, operator)
    _publish(svc, 1)
    viewer = {"Authorization": "Bearer rosy-dev-viewer"}
    status = tc.get("/api/v1/vision/front/status", headers=viewer)
    assert status.status_code == 200 and status.json()["available"] is True
    frame = tc.get("/api/v1/vision/front/frame",
                   params={"sequence": status.json()["sequence"]},
                   headers=viewer)
    assert frame.status_code == 200
