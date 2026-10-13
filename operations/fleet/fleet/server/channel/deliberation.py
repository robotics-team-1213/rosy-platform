"""Durable, read-only model questions; the original operator receipt stays immutable."""
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
import re
import sqlite3
import time

from fastapi import HTTPException
from rosy.decision.deliberation import Problem, canonical, identifier


def status_snapshot(snapshot):
    rows = snapshot.get('robots') if type(snapshot) is dict else None
    if type(rows) is not list or len(rows) > 15:
        raise ValueError('CHANNEL_STATUS_LIMIT')
    selected = []
    for row in rows:
        if type(row) is not dict or row.get('online') is not None and type(row.get('online')) is not bool:
            raise ValueError('CHANNEL_STATUS_INVALID')
        rid = identifier(row.get('robot_id'))
        state = row.get('state') if row.get('online') is True else None
        state = state if type(state) is dict else {}
        safety = state.get('safety') or {}
        line = state.get('line_follow') or {}
        selected.append({'robot_id': rid, 'online': row.get('online'),
            'mode': state.get('mode'), 'estop': safety.get('estop') if type(safety) is dict else None,
            'line_state': line.get('state') if type(line) is dict else None})
        for key in ('mode','line_state'):
            if selected[-1][key] is not None:identifier(selected[-1][key])
        if selected[-1]['estop'] is not None and type(selected[-1]['estop']) is not bool:
            raise ValueError('CHANNEL_STATUS_INVALID')
    if len({r['robot_id'] for r in selected}) != len(selected):
        raise ValueError('CHANNEL_STATUS_INVALID')
    return {'robots': sorted(selected, key=lambda r: r['robot_id'])}


def status_problem(receipt, snapshot, *, now):
    selected = status_snapshot(snapshot)
    values = [r['online'] for r in selected['robots']]
    state = ('empty' if not values else 'unknown' if None in values else
             'online' if all(values) else 'offline' if not any(values) else 'mixed')
    question = re.sub(r'<@!?[0-9]{17,20}>', '', receipt['content']).strip()
    digest = hashlib.sha256(canonical(selected).encode()).hexdigest()
    refs = tuple('robot:' + r['robot_id'] + ':' + ('unknown' if r['online'] is None
                 else 'online' if r['online'] else 'offline') for r in selected['robots'])
    return Problem('fleet', receipt['request_id'], digest, 'fleet_status', now,
        (*refs, 'snapshot:' + digest[:16]), ('human', 'reobserve'), 'READ_ONLY_QUERY',
        goal=question, facts_json=canonical({'state': state}))


from .model_journal import ModelJobsJournal


class ChannelModelJobs(ModelJobsJournal):
    def validate_input(self, receipt, problem, snapshot):
        if (type(problem) is not Problem or problem.domain != 'fleet_status'
                or problem != status_problem(receipt, snapshot, now=problem.observed_at)):
            raise ValueError('CHANNEL_MODEL_INPUT_REQUIRED')

    @staticmethod
    def serialize_input(problem):return canonical(asdict(problem))

    @staticmethod
    def input_basis(snapshot):return status_snapshot(snapshot)
