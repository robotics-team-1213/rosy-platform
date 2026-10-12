"""D-687 connects non-executable proposals to their existing admission owners."""
import hashlib
import json
from contextlib import closing

from fastapi import Depends, HTTPException

from core_common.protocol.cell_app import CellAppProposalRequest
from core_common.protocol.channel_requests import (
    ChannelCellPrepareRequest, ChannelMissionPrepareRequest, ChannelWorkAdmitRequest, ChannelWorkflowView,
)
from ..mission_routes import MissionAdmitRequest, MissionCandidateRequest
from ..site_auth import SitePrincipal


class ChannelMissions:
    def __init__(self, workflow, *, proposals, proposal_create, proposal_resolve, cell_prepare,
                 mission_admit, cell_service_id):
        if proposals is not None and proposals.path.resolve() != workflow.journal.path.resolve():
            raise ValueError('Discord work requires the existing shared Mission DB')
        self.workflow, self.proposals = workflow, proposals
        self.create, self.resolve, self.cell_prepare = proposal_create, proposal_resolve, cell_prepare
        self.admit_owner, self.cell_service_id = mission_admit, cell_service_id

    def _proposal(self, value, principal, conn=None):
        proposal = (self.proposals.get(value['work_id']) if conn is None else
                    self.proposals.get_in_transaction(conn, value['work_id']))
        author = self.cell_service_id if value['work_kind'] == 'cell_job' else principal
        if (proposal is None or proposal['principal_id'] != author
                or proposal['request_key'] != value['request_key']
                or (proposal['candidate'].get('kind') == 'cell_job') != (value['work_kind'] == 'cell_job')
                or proposal['state'] != 'RESOLVED'):
            raise HTTPException(409, detail='CHANNEL_WORK_PROVENANCE_CHANGED')
        return proposal

    def prepare(self, request_id, principal, body):
        value = self.workflow.read(request_id, principal)
        if self.proposals is None or self.create is None or self.resolve is None:
            raise HTTPException(503, detail='CHANNEL_MISSION_OWNER_UNAVAILABLE')
        document = body.model_dump(exclude={'expected_revision'})
        digest = hashlib.sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if value['state'] == 'LINKED':
            with closing(self.workflow.journal._connect()) as conn:
                saved = conn.execute('SELECT preparation_digest FROM fleet_channel_workflow WHERE request_id=?',
                                     (request_id,)).fetchone()[0]
            self.workflow._check({**value, 'revision': value['revision'] - 1}, body.expected_hash, body.expected_revision)
            if saved != digest or value['work_kind'] != body.kind:
                raise HTTPException(409, detail='CHANNEL_WORK_ALREADY_SUBMITTED')
            self._proposal(value, principal)
            return value
        self.workflow._check(value, body.expected_hash, body.expected_revision)
        owner = SitePrincipal(principal, 'operator')
        if body.kind == 'mission':
            candidate = body.candidate
            if body.source_proposal_id is not None:
                source = self.proposals.get(body.source_proposal_id, principal_id=principal)
                if source is None:
                    raise HTTPException(404, detail='CHANNEL_SOURCE_PROPOSAL_NOT_FOUND')
                # Feedback/replan lineage must stay with its original fenced resolver.
                if (source['state'] not in {'PROPOSED', 'RESOLVED'}
                        or source.get('supersedes_mission_id') is not None
                        or any(value is not None for key, value in source.items() if key.startswith('source_'))):
                    raise HTTPException(409, detail='CHANNEL_SOURCE_PROPOSAL_FENCED')
                if (source['candidate'].get('kind') == 'cell_job'
                        or source['workcell_id'] != body.workcell_id or source['instance_id'] != body.instance_id):
                    raise HTTPException(409, detail='CHANNEL_SOURCE_PROPOSAL_SCOPE_CHANGED')
                candidate = source['candidate']
            created = self.create(MissionCandidateRequest(
                request_key=value['request_key'], workcell_id=body.workcell_id,
                instance_id=body.instance_id, candidate=candidate), principal=owner)
            result = self.resolve(created['proposal']['proposal_id'], principal=owner)
        else:
            if self.cell_service_id is None or self.cell_prepare is None:
                raise HTTPException(503, detail='CELL_APP_UNCONFIGURED')
            fields = body.model_dump(exclude={'kind', 'reason', 'expected_hash', 'expected_revision'})
            result = self.cell_prepare(CellAppProposalRequest(request_key=value['request_key'], **fields))
        proposal_id = result['proposal']['proposal_id']
        with closing(self.workflow.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            receipt = self.workflow._receipt(conn, request_id, principal)
            current = self.workflow._view(conn, receipt)
            self.workflow._check(current, body.expected_hash, body.expected_revision)
            if current['state'] == 'LINKED':
                raise HTTPException(409, detail='CHANNEL_WORK_ALREADY_SUBMITTED')
            self._proposal({**current, 'work_id': proposal_id, 'work_kind': body.kind}, principal, conn)
            conn.execute('''INSERT INTO fleet_channel_workflow
                (request_id, revision, state, candidate, reason, work_id, work_kind, preparation_digest)
                VALUES (?, ?, 'LINKED', NULL, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET revision=excluded.revision, state='LINKED',
                candidate=NULL, reason=excluded.reason, work_id=excluded.work_id,
                work_kind=excluded.work_kind, preparation_digest=excluded.preparation_digest''',
                         (request_id, current['revision'] + 1, body.reason.strip(), proposal_id, body.kind, digest))
            if self.workflow.journal.reply_outbox is not None:
                self.workflow.journal.reply_outbox.enqueue(
                    conn, receipt, 'LINKED', f"ROSY 작업 원장 연결 · {request_id}\n{body.kind} {proposal_id}"
                    " · 실행 전 제안입니다. Console에서 별도 승인하세요.")
            return self.workflow._view(conn, receipt)

    def admit(self, request_id, principal, body):
        value = self.workflow.read(request_id, principal)
        self.workflow._check(value, body.expected_hash, body.expected_revision)
        if self.admit_owner is None or value['state'] != 'LINKED' or value['work_kind'] not in {'mission', 'cell_job'}:
            raise HTTPException(409, detail='CHANNEL_MISSION_NOT_PREPARED')
        self._proposal(value, principal)
        self.admit_owner(value['work_id'], MissionAdmitRequest(expected_generation=body.expected_generation),
                         principal=SitePrincipal(principal, 'operator'))
        return self.workflow.read(request_id, principal)


def install_channel_mission_routes(app, owners, *, require_operator, read_guard):
    @app.post('/api/fleet/channel-requests/{request_id}/prepare', dependencies=read_guard,
              response_model=ChannelWorkflowView, tags=['fleet-work'])
    def prepare(request_id: str, body: ChannelMissionPrepareRequest | ChannelCellPrepareRequest,
                principal=Depends(require_operator)):
        return owners.prepare(request_id, principal.principal_id, body)

    @app.post('/api/fleet/channel-requests/{request_id}/admit', dependencies=read_guard,
              response_model=ChannelWorkflowView, tags=['fleet-work'])
    def admit(request_id: str, body: ChannelWorkAdmitRequest, principal=Depends(require_operator)):
        return owners.admit(request_id, principal.principal_id, body)
