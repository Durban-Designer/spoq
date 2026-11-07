"""Deterministic DAG scheduling shared by project plans and features."""
from __future__ import annotations


def waves(dependencies: dict[str, list[str]]) -> list[list[str]]:
    remaining = {key: set(value) for key, value in dependencies.items()}
    missing = set().union(*remaining.values()) - remaining.keys() if remaining else set()
    if missing:
        raise ValueError('Unknown dependencies: ' + ', '.join(sorted(missing)))
    result = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError('Dependency cycle: ' + ', '.join(sorted(remaining)))
        result.append(ready)
        for key in ready:
            remaining.pop(key)
        for deps in remaining.values():
            deps.difference_update(ready)
    return result
