---
name: journal-tracker
description: Track AI agent work sessions in journal.md with timestamps, confidence scores, and detailed summaries. Supports auto-archiving, database parsing, and XAI/meta-orchestration integration. Use when starting/ending work sessions or when completing significant tasks.
---

# Journal Tracker Skill

## When to Use This Skill

Use this skill when:
- Starting a new work session
- Completing a work session
- Finishing significant tasks or milestones
- Updating status after major changes
- Before committing code (document what was done)

## MCP Detection

Before executing any scripts, check if the SPOQ MCP server is available:

1. Call `spoq_ping` tool
   - **Success** → MCP_MODE=true (use MCP tools for all operations below)
   - **Tool not found / Error** → MCP_MODE=false (use Python scripts as fallback)

This check only runs once per session. All script references below provide both paths.

### Timestamp Shorthand

Throughout this document, "**get a timestamp**" means:
- **MCP_MODE=true**: Call `spoq_get_timestamp(format="iso")`
- **MCP_MODE=false**: Run `python3 .claude/skills/journal-tracker/scripts/get-time.py`

Both return ISO 8601 format: `2025-11-01T10:52:34Z`

## Journal Entry Format

Every entry in `journal.md` follows this YAML frontmatter + Markdown format:

```markdown
---
agent: Claude Code
start_time: 2025-11-01T10:52:34Z
end_time: 2025-11-01T11:23:15Z
confidence: 0.95
session_type: development|refactor|bugfix|planning|documentation
files_modified:
  - path/to/file1.ts
  - path/to/file2.md
  - path/to/file3.py
tasks_completed: 3
tasks_total: 5
---

## Summary

Brief 1-2 sentence summary of what was accomplished in this session.

## Work Completed

- ✅ Task 1: Description of completed task
- ✅ Task 2: Description of completed task
- ✅ Task 3: Description of completed task

## Changes Made

### File Category 1
- `file1.ts` - What changed and why
- `file2.ts` - What changed and why

### File Category 2
- `file3.md` - What changed and why

## Issues Encountered

None.

Or list issues:
- Issue 1: Description and resolution
- Issue 2: Description and resolution

## Testing

- ✅ Unit tests passing
- ✅ Integration tests passing
- ⚠️ Manual testing required for X
- ❌ Performance benchmarks not run

## Next Steps

1. Next task to work on
2. Follow-up items
3. Known issues to address

## Notes

Additional context, decisions made, or important observations.

---
```

## Getting Timestamps

### MCP_MODE=true
```
Call spoq_get_timestamp(format="iso")
# Returns: 2025-11-01T10:52:34Z
```

### MCP_MODE=false (fallback)
```bash
# Get current time (ISO 8601 format)
python3 .claude/skills/journal-tracker/scripts/get-time.py
# Output: 2025-11-01T10:52:34Z
```

### In Practice

**Start of session:**

**MCP_MODE=true:**
```
START_TIME = spoq_get_timestamp(format="iso")
```

**MCP_MODE=false:**
```bash
START_TIME=$(python3 .claude/skills/journal-tracker/scripts/get-time.py)
echo $START_TIME
```

**End of session:**

**MCP_MODE=true:**
```
END_TIME = spoq_get_timestamp(format="iso")
```

**MCP_MODE=false:**
```bash
END_TIME=$(python3 .claude/skills/journal-tracker/scripts/get-time.py)
echo $END_TIME
```

## Confidence Scoring

Rate your confidence in the work completed:

| Score | Meaning | When to Use |
|-------|---------|-------------|
| 0.95-1.0 | Very High | Thoroughly tested, production-ready, no known issues |
| 0.85-0.94 | High | Well tested, minor edge cases may exist |
| 0.75-0.84 | Good | Functional, some testing needed |
| 0.65-0.74 | Moderate | Works but needs validation, potential issues |
| 0.50-0.64 | Low | Prototype quality, significant testing needed |
| <0.50 | Very Low | Experimental, known issues, needs rework |

**Factors affecting confidence:**
- Test coverage
- Complexity of changes
- Review status
- Known issues
- Integration testing
- Production readiness

## Session Types

Categorize your work session:

- **development**: New features, functionality
- **refactor**: Code reorganization, cleanup
- **bugfix**: Fixing identified issues
- **planning**: Design, architecture, roadmap
- **documentation**: Docs, READMEs, comments
- **migration**: Moving code, upgrading dependencies
- **optimization**: Performance improvements
- **testing**: Writing tests, test infrastructure
- **infrastructure**: DevOps, deployment, CI/CD
- **research**: Exploration, proof of concepts

## Complete Workflow Example

### 1. Start Session

```bash
# Capture start time (MCP_MODE=true: spoq_get_timestamp(format="iso"))
START_TIME=$(python3 .claude/skills/journal-tracker/scripts/get-time.py)
echo "Session started at: $START_TIME"

# Optional: Create a placeholder entry
cat >> journal.md << EOF

---
agent: Claude Code
start_time: $START_TIME
end_time: TBD
confidence: TBD
session_type: development
files_modified: []
tasks_completed: 0
tasks_total: 0
---

## Summary

[Work in progress...]

---

EOF
```

### 2. Do Work

Track files as you modify them:
- Note each file changed
- Track tasks completed
- Document issues encountered

### 3. End Session

```bash
# Capture end time (MCP_MODE=true: spoq_get_timestamp(format="iso"))
END_TIME=$(python3 .claude/skills/journal-tracker/scripts/get-time.py)
echo "Session ended at: $END_TIME"

# Update journal.md with complete entry (see format above)
```

### 4. Complete Entry Example

```markdown
---
agent: Claude Code
start_time: 2025-11-01T14:30:00Z
end_time: 2025-11-01T16:45:30Z
confidence: 0.92
session_type: development
files_modified:
  - code/apps/orchestrator-ts/src/tasks/tasks.service.ts
  - code/apps/orchestrator-ts/src/tasks/tasks.controller.ts
  - code/apps/orchestrator-ts/src/tasks/tasks.service.spec.ts
  - code/packages/shared/src/dtos/task.dto.ts
tasks_completed: 4
tasks_total: 5
---

## Summary

Migrated TaskService from Java Spring Boot to TypeScript NestJS with full test coverage. All endpoints functional, 95% test coverage achieved.

## Work Completed

- ✅ Converted TaskService from Java to TypeScript
- ✅ Implemented TaskController with NestJS decorators
- ✅ Created comprehensive unit tests (95% coverage)
- ✅ Updated shared DTOs for type safety

## Changes Made

### Backend Services (code/apps/orchestrator-ts/)
- `src/tasks/tasks.service.ts` - Full TaskService implementation with TypeORM
- `src/tasks/tasks.controller.ts` - RESTful endpoints for task management
- `src/tasks/tasks.service.spec.ts` - Comprehensive unit tests with mocking

### Shared Packages
- `code/packages/shared/src/dtos/task.dto.ts` - TypeScript interfaces for task DTOs

## Issues Encountered

- **TypeORM Query Builder**: Different syntax from JpaRepository, required learning curve
  - Resolution: Used TypeORM documentation and existing patterns
- **Async/Await**: Converted CompletableFuture patterns to Promise-based async/await
  - Resolution: Consistent async/await throughout service layer

## Testing

- ✅ Unit tests: 95% coverage (jest)
- ✅ Type checking: No TypeScript errors
- ✅ Linting: ESLint passing
- ⚠️ Integration tests: Pending (task 5)
- ⚠️ E2E tests: Pending

## Next Steps

1. Implement integration tests with TestContainers
2. Add E2E tests for task endpoints
3. Performance benchmark against Java version
4. Update API documentation
5. Begin migration of WorkerService

## Notes

- Java → TypeScript migration following patterns from java-to-typescript skill
- Maintained identical API contracts for backward compatibility
- Consider adding request/response interceptors for logging
- Database queries 20% faster with TypeORM query builder vs JPA (preliminary testing)

---
```

## Journal.md Structure

The journal file grows from bottom to top (newest entries at bottom):

```markdown
# SPOQ Development Journal

This journal tracks all AI agent work sessions with timestamps, confidence scores, and detailed summaries.

## Format

Each entry includes:
- **Agent**: Name of AI assistant
- **Timestamps**: Exact start/end times (UTC)
- **Confidence**: 0.0-1.0 score for work quality
- **Session Type**: Category of work performed
- **Files Modified**: Complete list of changed files
- **Summary**: Brief overview of work
- **Details**: Comprehensive breakdown

---

[First entry...]

---

[Second entry...]

---

[Most recent entry...]

---
```

## Best Practices

### 1. Timestamp Accuracy
```bash
# ALWAYS use the get-time script or MCP tool
# MCP_MODE=true:  spoq_get_timestamp(format="iso")
# MCP_MODE=false: python3 .claude/skills/journal-tracker/scripts/get-time.py
START=$(python3 .claude/skills/journal-tracker/scripts/get-time.py)

# DON'T manually type timestamps
# BAD: start_time: 2025-11-01T10:00:00Z  # Approximate
# GOOD: start_time: 2025-11-01T10:52:34Z  # Exact
```

### 2. File Listing
```yaml
# Be comprehensive
files_modified:
  - code/apps/api/src/service.ts
  - code/apps/api/src/controller.ts
  - code/apps/api/src/service.spec.ts
  - code/packages/shared/src/dto.ts
  - README.md
  - docs/api/endpoints.md

# DON'T be vague
# BAD: files_modified: [various files]
```

### 3. Confidence Calibration
```yaml
# Be honest about limitations
confidence: 0.75  # If edge cases not tested
confidence: 0.85  # If well tested but not production-validated
confidence: 0.95  # If thoroughly tested and production-ready

# DON'T overestimate
# Untested code is not 0.95 confidence
```

### 4. Actionable Next Steps
```markdown
## Next Steps

# GOOD: Specific and actionable
1. Run integration tests with PostgreSQL TestContainer
2. Benchmark query performance against Java baseline
3. Update OpenAPI spec for new endpoints

# BAD: Vague
1. More testing
2. Improvements
```

### 5. Document Decisions
```markdown
## Notes

# Record important decisions
- Chose TypeORM over Prisma for better NestJS integration
- Kept synchronous API despite async capabilities for Java parity
- Added custom exception filter for consistent error responses

# This helps future agents/developers understand "why"
```

## Integration with SPOQ Workflow

### Before Starting Work
1. Check `journal.md` for latest entry
2. Read "Next Steps" from last session
3. Understand context and decisions made
4. Capture start timestamp

### During Work
1. Track files as you modify them
2. Note issues encountered
3. Track tasks completed vs total
4. Document decisions in real-time

### After Completing Work
1. Capture end timestamp
2. Calculate confidence score
3. Write comprehensive summary
4. List all modified files
5. Define clear next steps
6. Append entry to journal.md

### Before Committing
1. Review journal entry
2. Ensure accuracy
3. Update confidence if needed
4. Reference journal in commit message

## Quick Reference Commands

```bash
# Get current time
# MCP_MODE=true:  spoq_get_timestamp(format="iso")
# MCP_MODE=false:
python3 .claude/skills/journal-tracker/scripts/get-time.py

# Get readable format (MCP_MODE=true: spoq_get_timestamp(format="readable"))
python3 .claude/skills/journal-tracker/scripts/get-time.py --format readable

# Create entry template
cat >> journal.md << 'EOF'

---
agent: Claude Code
start_time: $(python3 .claude/skills/journal-tracker/scripts/get-time.py)
end_time: TBD
confidence: TBD
session_type: development
files_modified: []
tasks_completed: 0
tasks_total: 0
---

## Summary

...

---

EOF

# View recent entries
tail -n 100 journal.md

# Search for specific work
grep -A 20 "TaskService" journal.md

# Count entries
grep -c "^agent:" journal.md
```

## IMPORTANT Rules

1. **ALWAYS use get-time.py or spoq_get_timestamp()**: Never manually type timestamps
2. **Complete file lists**: List every file modified, no exceptions
3. **Honest confidence**: Under-promise, over-deliver
4. **Specific summaries**: Say what was done, not "worked on stuff"
5. **Document issues**: Future agents need to know what went wrong
6. **Clear next steps**: Make it easy for next session to continue
7. **Update before commits**: Journal should be current before pushing code
8. **One entry per session**: Don't combine unrelated work
9. **Append to bottom**: Newest entries at end of file
10. **Review previous entries**: Learn from past work before starting

## Example Entry Templates

### Development Session
```markdown
---
agent: Claude Code
start_time: [get a timestamp - see MCP Detection]
end_time: [get a timestamp - see MCP Detection]
confidence: [0.0-1.0]
session_type: development
files_modified:
  - file1
  - file2
tasks_completed: X
tasks_total: Y
---

## Summary

Implemented [feature] with [tech]. Achieved [result].

## Work Completed

- ✅ Task 1
- ✅ Task 2

## Changes Made

- `file1` - Description
- `file2` - Description

## Issues Encountered

None / List issues

## Testing

- Status of tests

## Next Steps

1. Next task

---
```

### Bugfix Session
```markdown
---
agent: Claude Code
start_time: [timestamp]
end_time: [timestamp]
confidence: 0.88
session_type: bugfix
files_modified:
  - path/to/fixed/file.ts
  - path/to/test.spec.ts
tasks_completed: 1
tasks_total: 1
---

## Summary

Fixed [bug] in [component] by [solution]. Root cause was [explanation].

## Issue

- **Bug**: Description
- **Impact**: What was broken
- **Root Cause**: Why it happened

## Solution

- What was changed
- How it fixes the issue
- Why this approach

## Testing

- ✅ Regression test added
- ✅ Manual testing confirms fix

## Next Steps

1. Monitor for related issues

---
```

## Integration with Git

Reference journal entries in commit messages:

```bash
git commit -m "Migrate TaskService to TypeScript

- Converted Java Spring Boot service to NestJS
- 95% test coverage achieved
- See journal.md entry from 2025-11-01T14:30-16:45 for details

Confidence: 0.92"
```

This creates a traceable link between commits and journal entries.

## Automation and XAI Integration

### Auto-Archiving (`archive-journal.py`)

Automatically archives journal.md when it exceeds 1500 lines:
- Archives to `documents/archive/journals/journal_YYYYMMDD_HHMMSS.md`
- Supports multiple archives per day during intensive work
- Preserves journal header, resets active journal

```bash
# Check if archive is needed (dry run)
python3 scripts/journal/archive-journal.py --dry-run

# Archive with default 1500 line threshold
python3 scripts/journal/archive-journal.py

# Custom threshold
python3 scripts/journal/archive-journal.py --threshold 1000
```

**When to Archive**:
- Before starting a major new project
- When journal feels unwieldy to navigate
- Automatically when exceeding 1500 lines
- Run `--dry-run` first to see current line count

### Mega Journal Consolidation (`create-mega-journal.py`)

Combines all archives into single file for analysis:
- Sorts entries chronologically across all archives
- Used for historical analysis, reporting, training data
- Can include active journal.md

```bash
python3 .claude/skills/journal-tracker/scripts/create-mega-journal.py
python3 .claude/skills/journal-tracker/scripts/create-mega-journal.py --include-active
python3 .claude/skills/journal-tracker/scripts/create-mega-journal.py --output reports/history.md
```

### Database Parser (`parse-to-db.py`)

Parses YAML frontmatter into SQLite for knowledge graph construction:
- Enables SQL queries on work history
- Tracks file modification patterns
- Analyzes confidence trends, session types, agent activity
- Foundation for XAI and meta-orchestration

```bash
python3 .claude/skills/journal-tracker/scripts/parse-to-db.py --db journal.db
python3 .claude/skills/journal-tracker/scripts/parse-to-db.py --db journal.db --source mega-journal.md
python3 .claude/skills/journal-tracker/scripts/parse-to-db.py --db journal.db --analyze
```

**Example SQL Queries:**
```sql
-- Most productive days
SELECT DATE(start_time) as date, COUNT(*) as sessions, SUM(duration_seconds)/3600 as hours
FROM journal_entries GROUP BY date ORDER BY hours DESC;

-- Confidence trends
SELECT DATE(start_time) as date, AVG(confidence) as avg_conf
FROM journal_entries GROUP BY date ORDER BY date;

-- Most modified files
SELECT fm.file_path, COUNT(*) as mod_count
FROM files_modified fm GROUP BY fm.file_path ORDER BY mod_count DESC;
```

### XAI and Meta-Orchestration Vision

Journal system supports next-level multi-agent systems:
- **Explainable AI**: Track agent decision-making with confidence scores
- **Meta-Learning**: Train future agents on successful patterns from history
- **Swarm Coordination**: Monitor parallel agent work via timestamps and dependencies
- **Hierarchical Task Decomposition**: Track how complex tasks break down (tasks_completed/tasks_total)
- **Knowledge Graph**: Nodes (entries, files, tasks, issues), Edges (MODIFIED, COMPLETED, PRECEDED_BY)

**Real-world example**: User migrated 170 endpoints with 9-agent swarm in one afternoon using hierarchical task decomposition + journal tracking for coordination.

## Advanced: Full Session Transcript Capture

For comprehensive XAI and training data, capture **every token** in/out of agents:

### Manager Agents (Interactive)

**`session-logger.py`** - Auto-captures interactive Claude Code sessions:
- Full conversation transcript (all user prompts + assistant responses)
- Tool calls with parameters and results
- Thinking/reasoning blocks (when visible)
- Session metadata (agent, timestamps, summary)

Output: `session-transcripts/manager-{timestamp}/` with transcript.jsonl, tool-calls.jsonl, thinking.jsonl

### Worker Agents (Headless)

**`worker-logger.py`** - Structured logging for headless workers:
- Task input (what manager requested)
- Execution trace (steps taken with tools)
- Result output (success/failure, confidence, files)
- Performance metrics (duration, token count)

Output: `session-transcripts/workers/{task-id}/{worker-id}.jsonl`

### Training Data Aggregation

**`aggregate-sessions.py`** - Combine manager + worker sessions:
```bash
# Aggregate all sessions for a date
python3 .claude/skills/journal-tracker/scripts/aggregate-sessions.py --date 2025-11-01

# Generate training data in JSONL format
python3 .claude/skills/journal-tracker/scripts/aggregate-sessions.py --all --format training
```

**Output**: `training-data.jsonl` with hierarchical manager → worker → outcome examples suitable for fine-tuning open-source models.

**See**: `automation/SWARM_ARCHITECTURE.md` for complete documentation of manager-worker multi-agent systems (2-4 managers coordinating 100+ headless workers).
