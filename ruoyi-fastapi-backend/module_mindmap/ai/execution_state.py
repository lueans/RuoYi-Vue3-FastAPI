"""Execution evidence is independent of a retained/applied document result."""

import json
from typing import Any

EXECUTION_EVENT_TYPE = 'execution_state'
EXECUTION_STATES = frozenset({'running', 'stopped', 'unconfirmed'})


def job_execution_state(job: Any) -> str:
    # Read the loaded SQL projection without triggering async ORM lazy IO on a
    # newly inserted job. The request body never supplies execution evidence.
    raw = vars(job).get('execution_state_json')
    try:
        payload = json.loads(raw) if isinstance(raw, str) else None
    except (TypeError, ValueError):
        payload = None
    epoch = getattr(job, 'execution_epoch', 0) or 0
    if (
        isinstance(payload, dict)
        and type(payload.get('executionEpoch')) is int
        and payload['executionEpoch'] == epoch
        and isinstance(payload.get('executionState'), str)
        and payload.get('executionState') in EXECUTION_STATES
    ):
        return payload['executionState']
    if getattr(job, 'error_code', None) == 'AI_AGENT_CLEANUP_FAILED':
        return 'unconfirmed'
    # A zero epoch has never been claimed by an executor. An old nonzero epoch
    # without evidence is unknown, even when its result is ready/cancelled.
    return 'not_started' if epoch == 0 else 'unknown'


def execution_blocks_continuation(job: Any) -> bool:
    state = job_execution_state(job)
    return state in {'running', 'unconfirmed'} or (
        state == 'unknown'
        and (
            getattr(job, 'cancel_requested_time', None) is not None
            or getattr(job, 'status', None) == 'cancelled'
        )
    )
