# Opus Worker Prompt Template

Use this template when spawning Opus sub-agents for task execution.

> **Source of truth:** the live template is `render_worker()` in
> `scripts/compile-workflow.py`; this file is the human-readable mirror. The
> worker does **not** receive the full `description` / `overview` /
> `architecture` inlined — those are large and inlining them across every worker
> blew the Workflow tool's 512KB scriptPath cap. The worker is an Opus agent
> with filesystem access, so it is pointed at the authoritative task YAML and
> `EPIC.md` on disk instead (smaller script, no render-vs-source drift).

## Variables

- `{{task.id}}` - Task identifier
- `{{task.title}}` - Human-readable title
- `{{task.epic}}` - Parent epic name
- `{{task.path}}` - Path to the task YAML the worker must read (full spec/steps)
- `{{epic.md_path}}` - Path to EPIC.md the worker must read (overview/architecture)
- `{{task.acceptance_criteria}}` - List of acceptance criteria (inlined; short)
- `{{task.files_to_touch}}` - Files that should be modified (inlined; short)
- `{{task.dependencies}}` - Completed dependency task IDs
- `{{retry_count}}` - Current retry attempt (0 = first try)
- `{{qa_feedback}}` - QA feedback from previous attempt (if rework)

---

## Prompt

```markdown
You are executing task **{{task.id}}** from epic **{{task.epic}}**.

## Task: {{task.title}}

## Authoritative task specification (READ THIS FIRST)

Read the complete task definition from `{{task.path}}`. That YAML is the source
of truth: follow its objective, prerequisites, context, steps, code sketches,
verification, and error handling exactly. The Acceptance Criteria and Files to
Modify are reproduced below for convenience, but if anything differs, the YAML
on disk wins.

## Acceptance Criteria

{{#each task.acceptance_criteria}}
- [ ] {{this}}
{{/each}}

## Files to Modify

{{#each task.files_to_touch}}
- `{{this}}`
{{/each}}

## Epic Context

Read `{{epic.md_path}}` for the epic Overview and Architecture. Do not rely on
memory; consult it whenever a cross-task type, interface, or seam is unclear.

## Dependencies Completed

{{#if task.dependencies}}
The following tasks have been completed before this one:
{{#each task.dependencies}}
- {{this}}
{{/each}}
{{else}}
No dependencies - this is a Wave 1 task.
{{/if}}

{{#if qa_feedback}}
## Previous Attempt Feedback (Retry {{retry_count}}/3)

Your previous implementation did not pass QA. Here is the feedback:

{{qa_feedback}}

Address these specific issues in your implementation.
{{/if}}

## Instructions

1. Execute the task steps exactly as described
2. Verify each acceptance criterion as you complete it
3. Update or create unit tests for any code changes
4. If you encounter blockers, document them clearly
5. Return a summary of:
   - Work completed
   - Files modified
   - Tests added/updated
   - Any issues or concerns

## Output Format

When complete, provide:

```
## Summary
[1-2 sentence summary of what was accomplished]

## Files Modified
- `path/to/file1.java` - [what changed]
- `path/to/file2.java` - [what changed]

## Tests
- `path/to/test.java` - [tests added/modified]

## Acceptance Criteria Status
- [x] Criterion 1 - verified by [how]
- [x] Criterion 2 - verified by [how]

## Issues (if any)
- [Issue description and any workarounds applied]
```
```

---

## Usage Example

```python
worker_prompt = worker_template.format(
    task=task_data,
    epic=epic_metadata,
    retry_count=0,
    qa_feedback=None
)

# Spawn Opus agent
task_id = Task(
    prompt=worker_prompt,
    model="opus",
    run_in_background=True,
    description=f"Execute {task_data['id']}"
)
```

## Rework Example

```python
# After QA failure
worker_prompt = worker_template.format(
    task=task_data,
    epic=epic_metadata,
    retry_count=1,
    qa_feedback="""
Failing Metrics:
• Test Existence: 60 → Add tests for:
  - FooService.bar()
  - BazController.create()
• Completeness: 75 → Resolve:
  - TODO on line 42 of Foo.java

Remediation (3 actions):
1. Create FooServiceTest.java
2. Implement TODO (add caching logic)
3. Re-run /agent-validation
"""
)
```
