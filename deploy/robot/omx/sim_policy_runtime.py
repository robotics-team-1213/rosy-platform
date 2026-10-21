"""SIM-only additional step fence over the existing serialized policy admission."""
import threading

from rosy.execution.local.policy_runtime import PolicyRuntimeBinding


class SimPolicyRuntimeBinding(PolicyRuntimeBinding):
    def __init__(self,*args,**kwargs):
        self.admission_rejection=None
        super().__init__(*args,**kwargs)

    def _rejected(self,reason,command,current=None):
        # Latch the original failed comparison in memory; the actor flushes it after HOLD.
        if self.admission_rejection is None:
            diagnostic=dict(reason=reason)
            try:
                diagnostic['command_id']=command.command_id
                candidate=getattr(self._local,'candidate',None)
                diagnostic.update(checked_owner_s=self._clock(),
                    joint_names=list(command.joint_names),
                    targets=[list(point.positions) for point in command.trajectory_points],
                    observed_at_ns=getattr(candidate,'observed_at_ns',None),
                    camera_received_at_ns=getattr(candidate,'camera_received_at_ns',None),
                    produced_at_ns=getattr(candidate,'produced_at_ns',None))
                if current is not None:
                    diagnostic.update(positions=dict(current.positions),sequence=current.sequence,
                        received_owner_s=current.received_at,
                        max_step_rad=max(abs(value-current.positions[name])
                            for point in command.trajectory_points
                            for name,value in zip(command.joint_names,point.positions)))
            except Exception as error:
                diagnostic['diagnostic_error']=type(error).__name__
            self.admission_rejection=diagnostic
        return False

    def check_command(self, command):
        if not super().check_command(command):
            return self._rejected('base_context_freshness_or_binding',command)
        try:
            if self.session._authority(self.session.lease) is not True:
                return self._rejected('authority',command)
        except Exception:
            return self._rejected('authority_exception',command)
        current = self.owner._joint_state
        if current is None:return self._rejected('missing_readback',command)
        accepted=all(
            abs(value-current.positions[name]) <= .04
            for point in command.trajectory_points
            for name, value in zip(command.joint_names, point.positions))
        return True if accepted else self._rejected('readback_step',command,current)


def bind_sim_runtime(session, runtime):
    with session._lock:
        if session._runtime_binding is not None:
            raise ValueError('runtime already bound')
        session._runtime_binding = SimPolicyRuntimeBinding(session, runtime)


def trace_sim_admission(session,journal,runtime):
    """Measure unchanged SIM calls in memory; the stopped actor writes the trace."""
    records=[]
    binding=session._runtime_binding
    def measured(stage,call):
        def invoke(*args,**kwargs):
            command_id=next((arg.command_id for arg in args if hasattr(arg,'command_id')),None)
            if stage=='journal_read' and args:command_id=args[0]
            if command_id is None:
                command_id=getattr(getattr(binding._local,'command',None),'command_id',None)
            started=int(runtime.monotonic()*1e9);outcome='raised'
            try:
                value=call(*args,**kwargs);outcome='returned'
                return value
            finally:
                records.append(dict(stage=stage,command_id=command_id,thread_id=threading.get_ident(),
                    started_owner_ns=started,ended_owner_ns=int(runtime.monotonic()*1e9),outcome=outcome))
        return invoke
    for stage,target,name in [('session_submit',session,'submit'),('guard',session,'_guard'),
            ('journal_prepare',journal,'prepare'),('journal_observe',journal,'observe'),
            ('journal_read',journal,'read'),('native_send',runtime.action_port,'send_goal'),
            ('native_submit',binding,'submit'),('post_submission',binding,'check_after_submission')]:
        setattr(target,name,measured(stage,getattr(target,name)))
    return records
