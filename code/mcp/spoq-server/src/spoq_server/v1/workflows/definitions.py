"""Bundled immutable strategy definitions, independent of the source checkout."""
from __future__ import annotations

import json
from importlib.resources import files

from .compiler import compile_definition
from .types import StrategyDefinition

STRATEGIES = {'classic': ('standard', 'compact'), 'piqard': ('standard',)}


def get_strategy(strategy_id: str = 'classic', profile: str = 'standard') -> StrategyDefinition:
    if (not isinstance(strategy_id, str) or not isinstance(profile, str)
            or strategy_id not in STRATEGIES or profile not in STRATEGIES[strategy_id]):
        raise ValueError('Unknown strategy/profile; use classic standard|compact or piqard standard')
    value = json.loads((files('spoq_server') / 'data' / 'strategies' / (strategy_id + '.json')).read_text())
    if profile == 'compact':
        # A compact route changes task granularity, not its quality requirements.
        value['title'] += ' — compact'
        value['phases'][0]['config']['profile'] = 'compact'
        value['phases'][0]['config']['guidance'] = 'Use the smallest valid Feature/Task scope; retain both quality gates.'
    definition = StrategyDefinition.from_dict(value)
    compile_definition(definition)
    return definition


def list_strategies() -> list[dict]:
    return [{'id': name, 'title': get_strategy(name).title,
             'version': get_strategy(name).version, 'profiles': list(profiles),
             'definition_hash': get_strategy(name).content_hash}
            for name, profiles in STRATEGIES.items()]
