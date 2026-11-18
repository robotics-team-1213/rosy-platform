"""D-1024 3: Fleet side of the lease delivery port. A CORE client for ``POST /api/v1/arm/{lease,hold}`` and the ticker
that drives PolicyApprovals.tick_all at no more than a quarter of the lease (the lease itself renews at half period).

Any non-200, timeout or malformed reply is a failed delivery, which PolicyApprovals turns into a closed window and a
HOLD. Without a configured target Fleet builds no delivery port and no window can open.
"""
import json
import logging
import math
from pathlib import Path
import ssl
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

_LOG = logging.getLogger(__name__)
TIMEOUT_MAX_S = 0.25  # one HTTP exchange; a hung CORE must not outlast a lease period
_GRANT_KEYS = ('lease_id', 'episode_id', 'workcell_id', 'policy_digest', 'rig_revision', 'calibration_revision',
               'ttl_s', 'seq', 'window_remaining_s')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # A bearer token never follows a redirect.


class CoreLeaseDelivery:
    def __init__(self, targets, *, timeout_s=TIMEOUT_MAX_S, opener=None, ca_file=None):
        """targets: {workcell_id: (CORE origin, bearer token)}. https, or http only on loopback for the SIM."""
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= TIMEOUT_MAX_S
                or not targets):
            raise ValueError('targets and a timeout of at most 0.25 s required')
        self._targets = {}
        for workcell, (origin, token) in targets.items():
            parsed = urlsplit(origin)
            loopback = parsed.hostname in ('localhost', '127.0.0.1', '::1')
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in ('', '/') or parsed.scheme not in ('http', 'https')
                    or (parsed.scheme == 'http' and not loopback) or not token or any(c.isspace() for c in token)):
                raise ValueError(f'CORE origin and credential for {workcell} are invalid')
            self._targets[workcell] = (origin.rstrip('/'), token)
        self._timeout = timeout_s
        context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context)).open

    def _post(self, workcell_id, path, body):
        origin, token = self._targets[workcell_id]  # KeyError: an unconfigured workcell fails closed
        request = Request(origin + '/api/v1/arm/' + path, data=json.dumps(body, allow_nan=False).encode(),
                          method='POST', headers={'Authorization': 'Bearer ' + token,
                                                  'Content-Type': 'application/json'})
        # urlopen's timeout is per socket operation; a trickling reply would outlast it, so the whole exchange runs
        # under one hard deadline and an overrun is abandoned (a daemon thread ends when its socket times out).
        box = {}

        def exchange():
            try:
                with self._open(request, timeout=self._timeout) as response:
                    box['value'] = (response.status == 200, json.loads(response.read(65536)))
            except HTTPError as exc:
                exc.close()
                box['value'] = (False, {})
            except BaseException as exc:
                box['error'] = exc
        worker = threading.Thread(target=exchange, name='core-lease-exchange', daemon=True)
        worker.start()
        worker.join(self._timeout)
        if worker.is_alive():
            raise TimeoutError('CORE exchange passed its total deadline')
        if 'error' in box:
            raise box['error']
        return box['value']

    def deliver(self, grant):
        """PolicyApprovals.deliver port: True only when CORE accepted the lease."""
        try:
            ok, reply = self._post(grant['workcell_id'], 'lease', {k: grant[k] for k in _GRANT_KEYS})
            return ok and isinstance(reply, dict) and reply.get('accepted') is True
        except Exception:
            return False

    def hold(self, workcell_id, reason):
        """PolicyApprovals.hold port: raises when CORE did not confirm, so the approval retries the HOLD."""
        ok, _ = self._post(workcell_id, 'hold', {'reason': str(reason)[:96] or 'hold'})
        if not ok:
            raise OSError('CORE did not confirm HOLD')


class PolicyApprovalTicker:
    """One thread: tick_all every quarter lease. A failing tick never stops it; shutdown holds every open window."""

    def __init__(self, approvals):
        self.approvals, self._stop, self._thread = approvals, threading.Event(), None
        self.period_s = approvals.lease_s / 4

    def _run(self):
        while not self._stop.wait(self.period_s):
            try:
                self.approvals.tick_all()
            except Exception:
                _LOG.exception('policy approval tick failed; the next tick retries and windows stay held')

    def start(self):
        if self._thread is not None:
            raise RuntimeError('ticker already started')
        self._thread = threading.Thread(target=self._run, name='policy-approval-ticker', daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        try:
            self.approvals.hold_all('fleet_shutdown')
        except Exception:
            _LOG.exception('shutdown hold failed; device leases run out by themselves')


def targets_from_file(path):
    """JSON ``{workcell_id: {"url": ..., "token_file": ...}}``; the token stays in its own file."""
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    return {cell: (row['url'], Path(row['token_file']).read_text(encoding='utf-8').strip())
            for cell, row in raw.items()}


def build_policy_approvals(environ):
    """Approvals with a CORE delivery port and a ticker when ROSY_POLICY_LEASE_TARGETS names a targets file;
    otherwise the delivery-less approvals that refuse every window (nothing can be leased)."""
    from .policy_approval import PolicyApprovals
    path = environ.get('ROSY_POLICY_LEASE_TARGETS')
    if not path:
        return PolicyApprovals(), None
    try:
        delivery = CoreLeaseDelivery(targets_from_file(path), ca_file=environ.get('ROSY_POLICY_LEASE_CA') or None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        _LOG.exception('policy lease targets unusable; no delivery port, so no approval window can open')
        return PolicyApprovals(), None
    approvals = PolicyApprovals(deliver=delivery.deliver, hold=delivery.hold)
    return approvals, PolicyApprovalTicker(approvals)


def attach_ticker(app, ticker):
    """Run the ticker for the app's lifetime; leaving the lifespan holds every open window."""
    import asyncio
    from contextlib import asynccontextmanager
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        ticker.start()
        try:
            async with inner(application) as state:
                yield state
        finally:
            await asyncio.to_thread(ticker.stop)
    app.router.lifespan_context = lifespan
