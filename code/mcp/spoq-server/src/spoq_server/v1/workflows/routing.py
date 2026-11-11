"""Versioned deterministic routing; a strategy recommendation is not authorization."""
from __future__ import annotations

import json

from .definitions import get_strategy
from .types import canonical_json, content_hash

POLICY_VERSION = 'spoq-route-1'
ADDONS = ('diagram', 'erd', 'algorithm', 'formal')
SIGNALS = {
    'effort': {'small', 'medium', 'large', 'unknown'},
    'uncertainty': {'low', 'medium', 'high', 'unknown'},
    'impact': {'low', 'medium', 'high', 'critical', 'unknown'},
    'coupling': {'low', 'medium', 'high', 'unknown'},
}


def route(inputs: dict, preference: str | None = None) -> dict:
    """Choose a route from recorded signals; no time/cost prediction or model call.

    Missing uncertainty is conservative. Explicit preference can select Classic
    when no requested design output would be dropped, but cannot remove gates.
    """
    if not isinstance(inputs, dict):
        raise ValueError('Routing inputs must be an object')
    normalized = json.loads(canonical_json(inputs))
    missing = []
    for name, values in SIGNALS.items():
        value = normalized.get(name, 'unknown')
        if not isinstance(value, str) or value not in values:
            raise ValueError(f'Invalid {name}; expected one of {sorted(values)}')
        normalized[name] = value
        if value == 'unknown':
            missing.append(name)
    requested = normalized.get('addons', {})
    if not isinstance(requested, dict) or requested.keys() - set(ADDONS):
        raise ValueError('Addons must be an object with diagram, erd, algorithm, formal booleans')
    if any(type(v) is not bool for v in requested.values()):
        raise ValueError('Addon selections must be booleans')
    addons = {name: requested.get(name, False) for name in ADDONS}
    proof = normalized.get('formal_proof_required', False)
    if type(proof) is not bool:
        raise ValueError('formal_proof_required must be boolean')
    if proof:
        addons['formal'] = True
    normalized['formal_proof_required'] = proof
    normalized['addons'] = addons
    capabilities = normalized.get('capabilities', {})
    if not isinstance(capabilities, dict):
        raise ValueError('Capabilities must be an object of observed capabilities')
    normalized['capabilities'] = capabilities
    if 'goal' in normalized and (not isinstance(normalized['goal'], str) or len(normalized['goal']) > 100_000):
        raise ValueError('Goal must be text of at most 100,000 characters')
    evidence = normalized.get('evidence', [])
    if not isinstance(evidence, (dict, list)):
        raise ValueError('Input evidence must be a JSON object or array')
    normalized['evidence'] = evidence
    reasons = []
    human = False
    if normalized['uncertainty'] in {'high', 'unknown'}:
        human = True
        reasons.append('Uncertainty is high or unknown; record decisions and review a narrative before decomposition.')
    if normalized['impact'] in {'high', 'critical'}:
        human = True
        reasons.append('High impact benefits from a revision-bound human planning checkpoint.')
    if normalized['coupling'] == 'high':
        human = True
        reasons.append('High coupling calls for explicit design decisions before task decomposition.')
    if any(addons.values()):
        human = True
        reasons.append('Requested design outputs join before narrative review: ' + ', '.join(k for k, v in addons.items() if v) + '.')
    strategy = 'piqard' if human else 'classic'
    if preference is not None:
        if not isinstance(preference, str) or preference.lower() not in {'classic', 'piqard'}:
            raise ValueError('Strategy preference must be classic or piqard')
        strategy = preference.lower()
        if strategy == 'classic' and any(addons.values()):
            raise ValueError('Classic cannot drop requested design addons; select PIQARD or remove those design requirements explicitly')
        reasons.append('Explicit user strategy preference: ' + strategy + '; mandatory quality gates remain enabled.')
    compact = (strategy == 'classic' and normalized['effort'] == 'small'
               and normalized['uncertainty'] == 'low' and normalized['impact'] == 'low'
               and normalized['coupling'] == 'low')
    profile = 'compact' if compact else 'standard'
    if not reasons:
        reasons.append('Known scope can use Classic SPOQ with planning and implementation validation.')
    if compact:
        reasons.append('Small, clear, low-impact and loosely coupled work uses the compact profile without removing gates.')
    if normalized['effort'] == 'large':
        reasons.append('Large effort affects decomposition; size alone does not require human planning.')
    definition = get_strategy(strategy, profile)
    return {'format': 'spoq-route-1', 'policy_version': POLICY_VERSION,
            'strategy': strategy, 'profile': profile, 'addons': dict(addons),
            'effort_band': normalized['effort'], 'reasons': reasons,
            'missing_information': missing, 'input_evidence': evidence, 'inputs': normalized,
            'definition_hash': definition.content_hash,
            'mandatory_gates': {'plan': {'average': 95, 'floor': 90},
                                'implementation': {'average': 95, 'floor': 80},
                                'required_checks': True},
            'authorization': 'Inherit user scope and repository rules; routing grants no additional permission.'}


def propose_escalation(previous: dict, new_inputs: dict, *, at_phase_boundary: bool,
                       reason: str, preference: str | None = None) -> dict:
    """Return a proposal for a successor run; never mutate/reroute an active run."""
    if at_phase_boundary is not True:
        raise ValueError('Strategy revisions can only be proposed at a safe phase boundary')
    if not isinstance(previous, dict) or previous.get('format') != 'spoq-route-1':
        raise ValueError('A recorded previous routing result is required')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A strategy revision reason is required')
    proposed = route(new_inputs, preference)
    return {'status': 'proposed', 'requires_explicit_adoption': True,
            'previous_route_hash': content_hash(previous), 'proposed_route': proposed,
            'reason': reason, 'preserve_history': True,
            'approval_policy': 'Revalidate changed inputs and approvals in a successor run; retain reusable artifacts with provenance.'}
