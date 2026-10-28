"""Opt-in native-test timings; never changes admission or ROS callback scheduling."""
from collections import deque
import json
import sys
import threading
import time
import traceback


class FeedbackTrace:
    def __init__(self, runtime):
        self.events = deque(maxlen=3000)
        self.first_hold = None
        self.stacks = {}
        intake = runtime._joint_state_intake.snapshot
        deliver = runtime.owner.observe_joint_state
        admission = runtime.owner.run_admission_policy
        poll = runtime.owner.poll

        def snapshot(*args, **kwargs):
            self.add('intake', stamp_ns=kwargs['stamp_ns'], source_now_ns=kwargs['source_now_ns'])
            try:
                result = intake(*args, **kwargs)
            except Exception as error:
                self.add('intake_rejected', error=str(error))
                raise
            self.add('intake_accepted', sequence=result.sequence, received_at=result.received_at)
            return result

        def observe(value):
            self.add('owner_deliver', sequence=value.sequence)
            result = deliver(value)
            self.add('owner_delivered', sequence=value.sequence, accepted=result)
            return result

        def run(check):
            self.add('owner_lock_wait')
            def acquired(state):
                self.add('owner_lock_acquired')
                return check(state)
            return admission(acquired)

        def tick():
            self.add('poll_begin')
            result = poll()
            self.add('poll_end', state=result.state, reason=result.reason)
            if result.state == 'hold' and self.first_hold is None:
                self.first_hold = dict(reason=result.reason, command_id=result.command_id,
                    events=list(self.events))
                self.stacks = {str(key): traceback.format_stack(frame)
                    for key, frame in sys._current_frames().items()}
            return result

        runtime._joint_state_intake.snapshot = snapshot
        runtime.owner.observe_joint_state = observe
        runtime.owner.run_admission_policy = run
        runtime.owner.poll = tick

    def add(self, kind, **facts):
        self.events.append(dict(kind=kind, at=time.monotonic(), thread=threading.get_ident(), **facts))

    def dump(self, path=None):
        payload = json.dumps(dict(first_hold=self.first_hold,
            events=list(self.events), stacks=self.stacks))
        if path is None:
            print('OMX_FEEDBACK_TRACE=' + payload, flush=True)
        else:
            path.write_text(payload, encoding='utf-8')
            print('OMX_FEEDBACK_TRACE_FILE=' + path.name, flush=True)
