# SPOQ Epic Roadmap

This file tracks active epics in priority order. It is automatically updated by `/epic-planning` and `/agent-execution`.

## Active Epics (Priority Order)

Execute epics in the order listed below. Higher priority epics should complete before lower priority ones begin (unless they have no dependencies).

| Priority | Epic | Status | Tasks | Est. Hours | Dependencies |
|----------|------|--------|-------|------------|--------------|
| 1 | [backlog-yaml-roadmap](epics/active/backlog-yaml-roadmap/) | in-progress | 15 | 20h | none |
| 2 | [auth-rbac-roles](epics/active/auth-rbac-roles/) | in-progress | 10 | 18h | none |
| 3 | [telemetry-pipeline](epics/active/telemetry-pipeline/) | pending | 7 | 14h | auth-rbac-roles |
| 4 | [observability-dashboard](epics/active/observability-dashboard/) | proposed | 8 | 16h | telemetry-pipeline |
| 5 | [cli-plugin-system](epics/active/cli-plugin-system/) | proposed | 12 | 24h | |

## Completed Epics

| Epic | Completed | Tasks |
|------|-----------|-------|
| [spoq-rs-orchestrator](epics/complete/spoq-rs-orchestrator/) | 2026-02-23 | 12 |
| [spoq-mcp-server](epics/complete/spoq-mcp-server/) | 2026-02-23 | 9 |
| [website-redesign-ada](epics/complete/website-redesign-ada/) | 2026-02-11 | 16 |
| [seo-ai-first-optimization](epics/complete/seo-ai-first-optimization/) | 2026-02-15 | 13 |

## How This File Works

### Automatic Updates

1. **On Epic Planning**: New epics are added to the bottom of the Active Epics table
2. **On Epic Execution**: Status is updated as tasks complete
3. **On Epic Completion**: Epic moves from Active to Completed table

### Dependency Rules

- Epics with dependencies cannot start until their dependencies complete
- Independent epics can run in parallel if resources allow
- The `Dependencies` column lists epic names (not task IDs)
