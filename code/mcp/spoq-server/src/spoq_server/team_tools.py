"""Team execution MCP tools for SPOQ."""

import json
from collections import defaultdict
from pathlib import Path

from spoq_server.server import mcp, project_root
from spoq_server import epic_utils


def _resolve_epic_path(epic_path: str) -> Path:
    """Resolve epic path relative to project root."""
    p = Path(epic_path)
    if not p.is_absolute():
        p = project_root() / p
    return p


def _load_persona_rules() -> dict:
    """Load persona rules from config YAML."""
    rules_path = (
        project_root()
        / ".claude"
        / "skills"
        / "team-execution"
        / "assets"
        / "config"
        / "persona-rules.yml"
    )
    if not rules_path.exists():
        rules_path = Path(__file__).parent / 'data/skills/team-execution/assets/config/persona-rules.yml'
    if not rules_path.exists():
        return {
            "personas": {"fullstack": {"skills": [], "file_patterns": []}},
            "weights": {"skill_match": 2, "file_pattern_match": 1},
        }
    import yaml
    return yaml.safe_load(rules_path.read_text(encoding='utf-8'))


def _score_task_for_persona(
    task_skills: list[str],
    task_files: list[str],
    persona_skills: list[str],
    persona_patterns: list[str],
    weights: dict[str, int],
) -> int:
    """Score a task against a single persona profile.

    Formula: Score = (skill_matches * skill_weight) + (file_pattern_matches * file_weight)
    Each task file is counted at most once across all patterns.
    """
    score = 0

    # Skill intersection scoring
    task_skills_lower = {s.lower() for s in task_skills}
    persona_skills_lower = {s.lower() for s in persona_skills}
    skill_matches = len(task_skills_lower & persona_skills_lower)
    score += skill_matches * weights.get("skill_match", 2)

    # File pattern scoring — each file counted at most once
    for task_file in task_files:
        task_file_lower = task_file.lower()
        for pattern in persona_patterns:
            clean_pattern = pattern.lower().lstrip("*.")
            if clean_pattern in task_file_lower:
                score += weights.get("file_pattern_match", 1)
                break

    return score


@mcp.tool()
def spoq_assign_personas(epic_path: str, verbose: bool = False) -> str:
    """Assign specialist personas to tasks based on skills and file patterns.

    Scores each task against all persona profiles from persona-rules.yml.
    The highest-scoring persona wins; ties fall back to "fullstack".

    Args:
        epic_path: Path to epic directory (absolute or relative to project root).
        verbose: If true, include detailed scores per persona per task.

    Returns JSON mapping {task_id: persona} or detailed scoring when verbose.
    """
    try:
        eu = epic_utils
        resolved = _resolve_epic_path(epic_path)
        result = eu.parse_epic(resolved)

        if "error" in result:
            return json.dumps(result)

        tasks = result["tasks"]
        rules = _load_persona_rules()
        personas = rules.get("personas", {})
        weights = rules.get("weights", {"skill_match": 2, "file_pattern_match": 1})

        assignments = {}
        for task in tasks:
            task_id = task.get("id", "unknown")
            skills = task.get("skills_required", []) or []
            files = task.get("files_to_touch", []) or []

            best_persona = "fullstack"
            best_score = 0
            all_scores = {}

            for persona_name, persona_config in personas.items():
                if persona_name == "fullstack":
                    continue
                persona_skills = persona_config.get("skills", [])
                persona_patterns = persona_config.get("file_patterns", [])
                score = _score_task_for_persona(
                    skills, files, persona_skills, persona_patterns, weights
                )
                all_scores[persona_name] = score
                if score > best_score:
                    best_score = score
                    best_persona = persona_name

            all_scores["fullstack"] = 0

            if verbose:
                assignments[task_id] = {
                    "persona": best_persona,
                    "score": best_score,
                    "scores": all_scores,
                }
            else:
                assignments[task_id] = best_persona

        return json.dumps(assignments)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_detect_conflicts(epic_path: str, wave: int) -> str:
    """Detect shared file conflicts between tasks in a specific wave.

    Builds a file-to-tasks mapping for the requested wave, then identifies
    files touched by more than one task. These overlaps require orchestrator
    merge strategies during parallel execution.

    Args:
        epic_path: Path to epic directory (absolute or relative to project root).
        wave: Wave number to check for conflicts (0-indexed).

    Returns JSON with conflicts[], safe_tasks[], and conflicting_tasks[].
    """
    try:
        eu = epic_utils
        resolved = _resolve_epic_path(epic_path)
        result = eu.parse_epic(resolved)

        if "error" in result:
            return json.dumps(result)

        tasks = result["tasks"]
        waves_map = eu.compute_waves(tasks)
        wave_groups = eu.group_waves(waves_map)

        if wave not in wave_groups:
            available = sorted(wave_groups.keys())
            return json.dumps(
                {"error": f"Wave {wave} not found. Epic has waves {available}"}
            )

        task_map = {t["id"]: t for t in tasks}
        wave_task_ids = wave_groups[wave]
        wave_tasks = [task_map[tid] for tid in wave_task_ids if tid in task_map]

        # Build file -> tasks mapping
        file_tasks: dict[str, list[str]] = defaultdict(list)
        for task in wave_tasks:
            task_id = task.get("id", "unknown")
            files = task.get("files_to_touch", []) or []
            for f in files:
                file_tasks[f].append(task_id)

        # Identify conflicts (files touched by multiple tasks)
        conflicts = []
        conflicting_task_ids: set[str] = set()
        for filepath, task_ids in sorted(file_tasks.items()):
            if len(task_ids) > 1:
                conflicts.append({
                    "file": filepath,
                    "tasks": sorted(task_ids),
                    "resolution": "orchestrator_merge",
                })
                conflicting_task_ids.update(task_ids)

        all_task_ids = {t.get("id") for t in wave_tasks}
        safe_tasks = sorted(all_task_ids - conflicting_task_ids)

        return json.dumps({
            "wave": wave,
            "conflicts": conflicts,
            "safe_tasks": safe_tasks,
            "conflicting_tasks": sorted(conflicting_task_ids),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
