"""Fresh one-shot operator-approved study latch, outside the Fleet rearm protocol."""
from contextlib import closing
from datetime import datetime,timezone
import os

from core_common.protocol.schemas import LocalStopRequest, StopRequestSource
from omx_adapter.action_store import ActionStore
from omx_adapter.local_stop import LocalStopBlocked,LocalStopController
from sim_study_authority import NativeSimStudyAuthority


class NativeSimStopFence(LocalStopController):
    def __init__(self,authority):
        if type(authority) is not NativeSimStudyAuthority:
            raise ValueError('explicit native SIM study authority required')
        self.authority=authority
        path=authority.stop_path_once()
        if path.parent.resolve()!=authority.directory or path.parent.is_symlink():
            raise PermissionError('canonical study stop directory required')
        descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_WRONLY,0o600)
        os.close(descriptor)
        ActionStore(path)
        config=authority.owner.config
        super().__init__(path,workcell_id=config.workcell_id,instance_id=config.instance_id)
        with self._lock,closing(self._connect()) as connection:
            if not authority.valid():raise LocalStopBlocked('native study authority closed')
            changed=connection.execute("""UPDATE omx_local_stop SET authority_epoch=1,dispatch_generation=1,
                state='OPEN',source='operator_local',dispatch_enabled=1,
                reason='OPERATOR_APPROVED_ISOLATED_SIM_STUDY'
                WHERE workcell_id=? AND instance_id=? AND authority_epoch=0 AND dispatch_generation=0
                AND state='UNKNOWN' AND reason='STARTUP_STOP_UNCONFIRMED'""",
                (self.workcell_id,self.instance_id)).rowcount
            if changed!=1:raise LocalStopBlocked('study initialization is not fresh')
            connection.commit()
            self._forced_closed=False

    def rearm(self,**kwargs):
        raise LocalStopBlocked('isolated SIM study cannot rearm; new native job required')

    def is_open(self,*,authority_epoch,dispatch_generation):
        return self.authority.valid() and super().is_open(
            authority_epoch=authority_epoch,dispatch_generation=dispatch_generation)

    def close_study(self,reason):
        try:
            self.authority.revoke(reason)
        finally:
            self.trip(LocalStopRequest(workcell_id=self.workcell_id,instance_id=self.instance_id,
                authority_epoch=1,dispatch_generation=1,requested_at=datetime.now(timezone.utc),reason=reason),
                source=StopRequestSource.OPERATOR_LOCAL)

    def run_if_open(self,*,authority_epoch,dispatch_generation,fleet_fence_current,operation):
        def study_current():
            if not self.authority.valid() or not fleet_fence_current():
                self.close_study('SIM_STUDY_AUTHORITY_CLOSED')
                raise LocalStopBlocked('native study authority closed')
            return True
        return super().run_if_open(authority_epoch=authority_epoch,dispatch_generation=dispatch_generation,
                                  fleet_fence_current=study_current,operation=operation)
