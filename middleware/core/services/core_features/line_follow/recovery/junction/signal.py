"""D-620: ask on the paired Fleet API; only three seconds of unanswered waiting selects right."""
import logging
import uuid

from core_common.protocol.schemas import JunctionSignalAnswer

_LOG = logging.getLogger(__name__)
WAIT_S, REPLY_FRESH_S = 3.0, 2.0


class JunctionSignalMixin:
    def junction_signal_link_refused(self):
        return False

    def _signal_before_entry(self):
        j = self._junction or {}
        return (j.get('state') == 'waiting' or (j.get('signal_owned') and (
            j.get('state') == 'armed' or (j.get('state') == 'turning'
                                        and j.get('sub') == 'stopping' and 'pivot_basis' not in j))))

    def junction_signal_request(self):
        with self._lock:
            s = self._junction_signal
            return (s['id'] if s and self._mode.value == 'CAMERA_LINE'
                    and self._signal_before_entry() and not s.get('entered') else None)

    def junction_signal_answer(self, payload):
        try:
            answer = JunctionSignalAnswer.model_validate(payload)
        except ValueError:
            request = self.junction_signal_request()
            if request is not None and isinstance(payload, dict) and payload.get('request_id') == request:
                self.junction_signal_answer(dict(request_id=payload['request_id'], lamp='unknown',
                                                 may_enter=False, reason='invalid_reply'))
            return False
        with self._lock:
            if self.junction_signal_request() != answer.request_id:
                return False
            s = self._junction_signal
            previous = s.get('answer')
            s.update(answer=answer, answered_at=self._clock(), state=answer.lamp)
            if previous != answer:
                _LOG.info("junction %s Fleet reply %s may_enter=%s reason=%s",
                          s['id'], answer.lamp, answer.may_enter, answer.reason)
            return True

    def _signal_idle(self, now, seen):
        s = self._junction_signal
        if s is not None:
            if seen:
                s['last_seen'] = now
            elif self._junction is None and now-s['last_seen'] > self._config.lost_after_s:
                self._junction_signal = None

    def _signal_gate(self, j, now):
        if not self._config.junction_signal_enabled or not self._signal_before_entry():
            return j
        s = self._junction_signal
        if s is None:
            s = self._junction_signal = dict(id=uuid.uuid4().hex, start=now, last_seen=now,
                                            answer=None, state='waiting')
            _LOG.info("junction %s requesting Fleet signal; unanswered fallback after %.1fs", s['id'], WAIT_S)
        if s.get('entered'):
            return j
        if self.junction_signal_link_refused():
            self.junction_signal_answer(dict(request_id=s['id'], lamp='unknown',
                                             may_enter=False, reason='link_rejected'))
        answer = s['answer']
        allowed = (answer is not None and answer.lamp == 'green' and answer.may_enter
                   and 0 <= now-s['answered_at'] <= REPLY_FRESH_S)
        fallback = answer is None and now-s['start'] >= WAIT_S-1e-6
        if answer is not None and now-s['answered_at'] > REPLY_FRESH_S:
            s['state'] = 'unknown'  # an expired reply stays answered; it never becomes silence
        if not (allowed or fallback):
            if j.get('signal_owned'):
                self._bridge_hint = None
                self._junction = j = dict(action=None, place_id=None, state='waiting')
            return j
        if not j.get('signal_owned'):
            s['state'] = 'fallback' if fallback else 'green'
            self.set_junction('right', 'signal:'+s['id'], expires_s=30., turn_deg=-90., now=now)
            j = self._junction
            j['signal_owned'] = True
            _LOG.info("junction %s selecting right (-90deg): %s; CORE motion admission still required",
                      s['id'], s['state'])
        return j

    def _signal_entered(self, j):
        if j.get('signal_owned') and self._junction_signal is not None:
            self._junction_signal.update(entered=True, state='entered')
