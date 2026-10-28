"""D-789 robot media runtime: camera mailbox -> H.264 -> WHIP, only while a viewer demands it.

Runs as the optional native ``rosy-media.service`` (its own cgroup); it never opens the
camera. Config is one JSON file (template rosy-media.example.json beside the native units).
"""

import json
from pathlib import Path
import random
import signal
import sys
import time

from .clients import CoreSourceClient, MediaHTTPError
from .feedback import WireSampler
from .policy import MediaPolicy

RENEW_BEFORE_S = 40     # a 60 s grant is renewed every ~20 s
DEMAND_STALE_S = 5
MAX_BACKOFF_S = 5


class MediaWorker:
    def __init__(self, *, client, open_reader, make_publisher, policy=None, sampler=None,
                 rng=random.random, log=print):
        self._client, self._open_reader, self._make_publisher = client, open_reader, make_publisher
        self._policy, self._sampler = policy or MediaPolicy(), sampler
        self._rng, self._log = rng, log
        self.grant, self.publisher, self._reader = None, None, None
        self._demand, self._demand_at = None, None
        self._next_control, self._retry_at, self._failures = 0.0, 0.0, 0
        self._session_renewed = None

    def _control(self, now, wall):
        try:
            if self.grant is None or self.grant.expires_at - wall < RENEW_BEFORE_S:
                renewing = self.grant is not None
                self.grant = self._client.source_grant(self.grant.grant_id if renewing else None)
                if renewing and self.publisher is not None:
                    self._client.renew_session(self.grant)  # same jti, same real session
            self._demand, self._demand_at = self._client.demand(self.grant), now
        except MediaHTTPError as exc:
            if exc.status in (401, 403):
                self.grant = None  # CORE withdrew the source scope: stop at once
                self._demand_at = None
            self._log('media control: ' + str(exc) + (f' ({exc.status})' if exc.status else ''))

    def _demanded(self, now):
        return (self._demand is not None and self._demand_at is not None and self.grant is not None
                and now - self._demand_at <= DEMAND_STALE_S and self._demand['active'] is True)

    def _stop(self, reason, *, failed=False):
        if self.publisher is not None:
            try:
                self.publisher.stop()
            except Exception:
                pass
            self.publisher = None
            self._log('media publisher stopped: ' + reason)
        if failed:
            self._failures += 1
            delay = min(MAX_BACKOFF_S, 0.5 * 2 ** min(self._failures, 4))
            self._retry_at = self._now + delay * (0.5 + 0.5 * self._rng())

    def _feedback(self, now):
        stats = self.publisher.stats()
        wire = self._sampler.sample(now=now) if self._sampler else None
        # shortcut: an unreadable NIC counter disables only the wire guard; fix the interface name to restore it.
        decision = self._policy.update(demand_age_s=now - self._demand_at,
            queue_age_ms=stats['encoded_queue_ms'], loss_fraction=stats['loss_fraction'] or 0,
            wire_bps=wire or 0)
        if stats.get('encoded_queue_overrun') or not decision.enabled:
            # Restarting the session resumes at an IDR instead of dropping reference frames.
            self._stop(decision.reason if not decision.enabled else 'encoded_queue_overrun', failed=True)
            return
        self.publisher.set_rate(fps=min(decision.fps, self._demand['fps']),
                                bitrate=min(decision.bitrate, self._demand['target_bitrate']))

    def step(self, *, now, wall):
        self._now = now
        if now >= self._next_control:
            self._next_control = now + 1
            self._control(now, wall)
            if self.publisher is not None and self._demanded(now):
                try:
                    self._feedback(now)
                except Exception as exc:
                    self._stop('feedback ' + type(exc).__name__, failed=True)
        if not self._demanded(now):
            self._stop('no active viewer demand')
            return
        if self.publisher is None:
            if now < self._retry_at:
                return
            try:
                self._reader = self._reader or self._open_reader()  # mailbox may not exist yet
                self.publisher = self._make_publisher(self._client.whip_endpoint(self.grant), self.grant.token)
                self.publisher.start()
            except Exception as exc:
                self._stop('start ' + type(exc).__name__, failed=True)
                return
        frame = self._reader.latest()
        if frame is None:
            return
        try:
            if self.publisher.push_rgb(frame.rgb, epoch=frame.epoch, sequence=frame.sequence,
                                       captured_ms=frame.captured_ms):
                self._failures = 0
        except Exception as exc:
            self._stop('push ' + type(exc).__name__, failed=True)

    def close(self):
        self._now = 0
        self._stop('shutdown')
        if self._reader is not None:
            self._reader.close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit('usage: python -m rosy_media_edge.worker <rosy-media.json>')
    config = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    from .pipeline import MediaPublisher
    from .source import FrameReader
    token = Path(config['source_token_file']).read_text(encoding='ascii').strip()
    client = CoreSourceClient(core_url=config['core_url'], site_url=config['site_url'],
        robot_id=config['robot_id'], audience=config['audience'], source_token=token,
        core_ca=config.get('core_ca'), site_ca=config.get('site_ca'))
    worker = MediaWorker(client=client, open_reader=lambda: FrameReader(config['mailbox']),
        make_publisher=lambda endpoint, grant: MediaPublisher(endpoint, grant, ca_file=config.get('site_ca')),
        sampler=WireSampler(config.get('interface', 'wlan0')), log=lambda line: print(line, flush=True))
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # systemd stop still sends WHIP DELETE
    try:
        while True:
            worker.step(now=time.monotonic(), wall=time.time())
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()


if __name__ == '__main__':
    main()
