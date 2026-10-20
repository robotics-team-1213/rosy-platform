"""Optional admitted conversation protocol, separate from D-720 status admission."""
import asyncio
from contextlib import asynccontextmanager
import logging
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator
from rosy.decision.deliberation import canonical

from rosy.decision.conversation.codec import Profile, Strict, bounded_environment, checked_answer, digest, source_policy
from rosy.decision.conversation.preprocessing import DISCORD_REVISION, prepare
from .jobs import ConversationJobs
from .worker import ConversationWorker
from ..broker_transport import exchange
from ..model_runtime import fresh_snapshot


class ConversationConfig(Strict):
    host: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
    ssh_port: Literal[22, 2222] = 22
    key_file: str = Field(pattern=r'^/run/rosy-deliberation/broker.key$')
    known_hosts_file: str = Field(pattern=r'^/run/rosy-deliberation/known_hosts$')
    profile: Profile
    source_commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    valid_until: FiniteFloat
    primary_admitted: bool
    semantic_evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    policy: dict

    @model_validator(mode='after')
    def independent_policy(self):
        if self.policy != source_policy(self.source_commit, self.profile):
            raise ValueError('CONVERSATION_POLICY_NOT_ADMITTED')
        return self

    def producer_scope(self):
        return {k:getattr(self, k) for k in ('source_commit', 'policy', 'semantic_evidence_sha256')} | {
            'profile':self.profile.model_dump()}

    @classmethod
    def load(cls, path, *, optional=False):
        if optional and not Path(path).exists():return None
        try:return cls.model_validate_json(Path(path).read_bytes())
        except (OSError, ValueError):raise ValueError('INVALID_CONVERSATION_CONFIG') from None


class ConversationProvider:
    def __init__(self, config):self.config = config

    async def __call__(self, question, profile, remaining):
        c = self.config
        if profile != c.profile:raise ValueError('CONVERSATION_PROFILE_CHANGED')
        packet = canonical({'schema':'rosy.conversation-request/1', 'source_commit':c.source_commit,
            'profile':profile.model_dump(), 'policy':c.policy, 'input_hash':question.digest,
            'question':question.model_dump(), 'remaining':remaining}).encode()
        if len(packet) > 65536:raise ValueError('CONVERSATION_INPUT_LIMIT')
        value = await exchange(c, 'rosy-conversation-v1', packet, remaining)
        if (type(value) is not dict or set(value) != {'source_commit', 'profile', 'input_hash', 'answer', 'cost_usd'}
                or value['source_commit'] != c.source_commit or value['profile'] != profile.model_dump()
                or value['input_hash'] != question.digest or type(value['cost_usd']) not in (int, float)
                or value['cost_usd'] != 0):raise ValueError('CONVERSATION_BROKER_IDENTITY_CHANGED')
        answer = checked_answer(value['answer'], question, preprocessing=profile.revision == DISCORD_REVISION)
        if answer.usage is not None:
            if answer.usage.preparation_hash != prepare(question).digest:
                raise ValueError('CONVERSATION_PREPARATION_CHANGED')
            logging.getLogger('uvicorn.error').info('conversation_inference %s', json.dumps({
                'input_hash':question.digest, 'profile':profile.revision,
                'source_commit':c.source_commit, **answer.usage.model_dump()}, sort_keys=True))
        return answer.model_dump()


def install_conversation(app, config, site_maps, *, task_service=None):
    if config is None:return
    if getattr(app.state, 'channel_model_jobs', None) is not None:
        raise ValueError('ONE_CHANNEL_CONVERSATION_OWNER_REQUIRED')
    journal = getattr(app.state, 'channel_requests', None)
    if journal is None or journal.reply_outbox is None:raise ValueError('CONVERSATION_RECEPTION_AND_REPLIES_REQUIRED')
    scope = config.producer_scope()
    jobs = ConversationJobs(journal, digest(scope))
    app.state.channel_conversation_jobs = jobs
    gather = app.state.fleet_gather

    def cached():
        snapshot = fresh_snapshot(gather._snapshot, gather.gathered_at, gather._console._clock())
        view = site_maps.active_view()
        snapshot['map'] = None if view is None else {k:view[k] for k in ('version', 'sha256')} | {
            'places_complete':len(view['map']['places']) <= 64,
            'places':[{k:p.get(k) for k in ('id', 'name', 'x', 'y', 'yaw')}
                      for p in sorted(view['map']['places'], key=lambda p:p['id'])[:64]]}
        # Existing Mission/Cell approvals are not exposed as model authority.
        snapshot['work_catalog'] = []
        return snapshot

    async def snapshot():
        await gather()
        return cached()

    def admitted():
        return (config.primary_admitted and time.time() < config.valid_until and
                config.producer_scope() == scope and config.policy == source_policy(config.source_commit, config.profile))
    worker = ConversationWorker(jobs, snapshot, config.profile, ConversationProvider(config),
        admission=admitted, producer_scope=scope,
        observation_guard=lambda basis:bounded_environment(cached()) == basis,
        context_reader=lambda context:app.state.intent_execution.console._client(context['robot_id'])._get(
            '/api/v1/navigation/state?run_id='+context['run_id']))
    app.state.channel_conversation_worker = worker
    if task_service is not None and config.profile.revision != DISCORD_REVISION:
        from ..execution.runtime import install_execution
        install_execution(app,jobs,task_service,scope,admitted,lambda:bounded_environment(cached()),
                          refresh=snapshot)
    previous = app.router.lifespan_context

    async def run():
        await asyncio.to_thread(jobs.recover)
        while True:
            try:
                for receipt in await asyncio.to_thread(jobs.pending_receipts):await worker.step(receipt)
            except asyncio.CancelledError:raise
            except Exception:logging.getLogger(__name__).warning('Conversation cycle held; no model replay')
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state:
            task = asyncio.create_task(run())
            try:yield state
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    app.router.lifespan_context = lifespan


def install_conversation_routes(app, conversation_config, model_config, site_maps,
                                task_service, require_operator, read_guard):
    from fastapi import Depends
    from core_common.protocol.channel_requests import ChannelModelResult
    from ..model_runtime import install_channel_models
    install_channel_models(app, model_config)
    install_conversation(app, conversation_config, site_maps, task_service=task_service)
    if model_config is not None or conversation_config is not None:
        @app.get('/api/fleet/channel-requests/{request_id}/deliberation', dependencies=read_guard,
                 response_model=ChannelModelResult, tags=['fleet-work'])
        def channel_model_result(request_id: str, principal=Depends(require_operator)):
            jobs = (app.state.channel_conversation_jobs if conversation_config is not None
                    else app.state.channel_model_jobs)
            return jobs.read(request_id, principal.principal_id)
