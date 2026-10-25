"""G73: the owner is never part of the escalation control flow."""
from copy import deepcopy

import pytest
from pydantic import ValidationError
from contracts import Escalation, ViewerMessage
from tests.engine.conftest import load_json


def current_escalation():
    e = deepcopy(load_json('shapes/escalation_open.json'))
    e['options'] = [o for o in e['options'] if o['option_id'] != 'ask_owner']
    e['claude_attempts'] = []
    return e


def test_g73_shape_and_notice():
    e = current_escalation()
    Escalation.model_validate(e)
    ViewerMessage.model_validate({'type': 'escalation', 'data': e,
                                  'explanation': 'Safe fallback is active.', 'explanation_source': 'template'})


def test_owner_states_and_options_are_rejected():
    e = current_escalation()
    e['status'] = 'awaiting_owner'
    with pytest.raises(ValidationError):
        Escalation.model_validate(e)
    e = current_escalation()
    e['options'][0]['option_id'] = 'ask_owner'
    with pytest.raises(ValidationError):
        Escalation.model_validate(e)


def test_attempt_verdict_consistency():
    e = current_escalation()
    e['claude_attempts'] = [{'ts': e['ts'], 'option_id': 'accept_overrun',
                             'accepted': False, 'reason': 'outside_authority', 'rationale': None}]
    Escalation.model_validate(e)
    e['claude_attempts'][0]['accepted'] = True
    with pytest.raises(ValidationError):
        Escalation.model_validate(e)
