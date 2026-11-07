# Haiku Investigation Prompt Template

Use this template when spawning a Haiku agent to investigate build failures.

## Variables

- `{{wave}}` - Wave number that just completed
- `{{init_sh_output}}` - Last 100 lines of ./init.sh output
- `{{wave_tasks}}` - List of tasks in this wave with their files_to_touch
- `{{git_diff_stat}}` - Output of `git diff --stat` showing changed files

---

## Prompt

```markdown
The build failed after wave {{wave}} completed. Your task is to identify which specific task(s) caused the failure.

## Build Output (last 100 lines)

```
{{init_sh_output}}
```

## Tasks in Wave {{wave}}

{{#each wave_tasks}}
### {{this.id}}: {{this.title}}
Files touched:
{{#each this.files_to_touch}}
- `{{this}}`
{{/each}}

{{/each}}

## Git Diff Summary

```
{{git_diff_stat}}
```

## Instructions

1. Parse the build error output to identify:
   - Which file(s) have errors
   - What type of error (compile, test failure, lint, etc.)
   - The root cause message

2. Cross-reference error file(s) with task `files_to_touch`:
   - Match error file paths to task file lists
   - A task is "failing" if ANY of its files appear in the error

3. Determine which tasks PASSED:
   - Tasks whose files do NOT appear in error output
   - These can proceed to QA

4. Return ONLY the structured output below

## Output Format (JSON only)

```json
{
  "failing_tasks": ["task-01", "task-03"],
  "passing_tasks": ["task-02", "task-04"],
  "root_cause": "Compile error in FooService.java line 42: missing import for Optional",
  "error_type": "compile",
  "affected_files": [
    "code/apps/orchestrator-java/src/main/java/com/wyrd/orchestrator/service/FooService.java"
  ]
}
```

## Field Descriptions

- `failing_tasks`: Task IDs whose files appear in error output (array of strings)
- `passing_tasks`: Task IDs whose files do NOT appear in error output (array of strings)
- `root_cause`: Concise (1 sentence) description of the actual error
- `error_type`: One of: "compile", "test", "lint", "runtime", "unknown"
- `affected_files`: List of file paths that have errors

## Important

- Return ONLY valid JSON, no markdown or explanation
- Be precise about which tasks are failing vs passing
- If unclear which task caused an error, mark ALL potentially related tasks as failing
- An empty `failing_tasks` array means the build error is unrelated to this wave's changes
```

---

## Usage Example

```python
investigation_prompt = investigation_template.format(
    wave=2,
    init_sh_output=build_output[-100:],  # Last 100 lines
    wave_tasks=wave_task_details,
    git_diff_stat=diff_stat_output
)

# Spawn Haiku agent (fast, low cost)
result = Task(
    prompt=investigation_prompt,
    model="haiku",
    description=f"Investigate wave {wave} build failure"
)

# Parse JSON response
investigation_result = json.loads(result.output)
failing_task_ids = investigation_result["failing_tasks"]
passing_task_ids = investigation_result["passing_tasks"]
```

## Expected Behaviors

### Scenario 1: Single task failure
```json
{
  "failing_tasks": ["03-create-badge"],
  "passing_tasks": ["04-create-button", "05-create-progress"],
  "root_cause": "BadgeComponent.tsx has undefined import 'cn' from utils",
  "error_type": "compile",
  "affected_files": ["code/apps/monitor-ui/src/components/ui/Badge.tsx"]
}
```

### Scenario 2: Multiple task failures
```json
{
  "failing_tasks": ["03-create-badge", "05-create-progress"],
  "passing_tasks": ["04-create-button"],
  "root_cause": "Multiple components missing cn utility import",
  "error_type": "compile",
  "affected_files": [
    "code/apps/monitor-ui/src/components/ui/Badge.tsx",
    "code/apps/monitor-ui/src/components/ui/Progress.tsx"
  ]
}
```

### Scenario 3: Unrelated build failure
```json
{
  "failing_tasks": [],
  "passing_tasks": ["03-create-badge", "04-create-button", "05-create-progress"],
  "root_cause": "PostgreSQL connection refused - infrastructure not running",
  "error_type": "runtime",
  "affected_files": []
}
```

In scenario 3, all tasks can proceed to QA since the build failure is unrelated to their changes.
