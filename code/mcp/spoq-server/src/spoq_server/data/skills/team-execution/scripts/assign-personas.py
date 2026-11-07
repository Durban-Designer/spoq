#!/usr/bin/env python3
"""
Assign persona types to tasks based on skills_required and files_to_touch.

Reads a JSON task list from stdin (output of build-dependency-graph.py or
parse-epic.py) and outputs a JSON mapping of task_id -> persona_name.

Scoring: Score = (skill_matches * 2) + (file_pattern_matches * 1)
When no score > 0, defaults to "fullstack".

Usage:
    python3 parse-epic.py spoq/epics/epic-name | python3 assign-personas.py
    python3 assign-personas.py < tasks.json
    python3 assign-personas.py --verbose < tasks.json
"""

import sys
import json
from pathlib import Path
from typing import Any

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

yaml = None
try:
    from epic_utils import _ensure_yaml
    yaml = _ensure_yaml()
except ImportError:
    try:
        import yaml as _yaml
        yaml = _yaml
    except ImportError:
        print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)


def load_persona_rules() -> dict[str, Any]:
    """Load persona rules from config YAML."""
    rules_path = Path(__file__).parent.parent / "assets" / "config" / "persona-rules.yml"
    if not rules_path.exists():
        print(f"Warning: {rules_path} not found, using defaults", file=sys.stderr)
        return {"personas": {"fullstack": {"skills": [], "file_patterns": []}}, "weights": {"skill_match": 2, "file_pattern_match": 1}}
    with open(rules_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def score_task_for_persona(
    task_skills: list[str],
    task_files: list[str],
    persona_skills: list[str],
    persona_patterns: list[str],
    weights: dict[str, int],
) -> int:
    """Score a task against a single persona profile."""
    score = 0

    # Skill matching (case-insensitive)
    task_skills_lower = {s.lower() for s in task_skills}
    persona_skills_lower = {s.lower() for s in persona_skills}
    skill_matches = len(task_skills_lower & persona_skills_lower)
    score += skill_matches * weights.get("skill_match", 2)

    # File pattern matching (substring match)
    for task_file in task_files:
        task_file_lower = task_file.lower()
        for pattern in persona_patterns:
            pattern_lower = pattern.lower()
            # Strip leading wildcards for substring matching
            clean_pattern = pattern_lower.lstrip("*.")
            if clean_pattern in task_file_lower:
                score += weights.get("file_pattern_match", 1)
                break  # One match per file is enough

    return score


def assign_personas(tasks: list[dict], rules: dict[str, Any]) -> dict[str, dict]:
    """
    Assign persona to each task based on scoring.

    Returns dict: {task_id: {"persona": name, "score": int, "scores": {persona: score}}}
    """
    personas = rules.get("personas", {})
    weights = rules.get("weights", {"skill_match": 2, "file_pattern_match": 1})
    assignments = {}

    for task in tasks:
        task_id = task.get("id", "unknown")

        # Handle field name variance between example and production epics
        skills = task.get("skills_required", []) or task.get("expertise_tags", []) or []
        files = task.get("files_to_touch", []) or task.get("deliverables", []) or []

        best_persona = "fullstack"
        best_score = 0
        all_scores = {}

        for persona_name, persona_config in personas.items():
            if persona_name == "fullstack":
                continue  # Fullstack is the fallback

            persona_skills = persona_config.get("skills", [])
            persona_patterns = persona_config.get("file_patterns", [])

            score = score_task_for_persona(
                skills, files, persona_skills, persona_patterns, weights
            )
            all_scores[persona_name] = score

            if score > best_score:
                best_score = score
                best_persona = persona_name

        all_scores["fullstack"] = 0
        assignments[task_id] = {
            "persona": best_persona,
            "score": best_score,
            "scores": all_scores,
        }

    return assignments


def main():
    verbose = "--verbose" in sys.argv

    # Read input from stdin
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Accept either parsed epic format or raw task list
    if "tasks" in data:
        tasks = data["tasks"]
    elif isinstance(data, list):
        tasks = data
    else:
        print("Error: Expected JSON with 'tasks' key or a JSON array", file=sys.stderr)
        sys.exit(1)

    if not tasks:
        print(json.dumps({}))
        return

    # Load rules and assign
    rules = load_persona_rules()
    assignments = assign_personas(tasks, rules)

    if verbose:
        # Detailed output
        print(json.dumps(assignments, indent=2))
    else:
        # Compact output: {task_id: persona_name}
        compact = {tid: info["persona"] for tid, info in assignments.items()}
        print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
