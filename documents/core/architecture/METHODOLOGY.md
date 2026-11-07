# SPOQ Methodology Reference

> Historical methodology reference. For the SQLite 1.x entity model and current
> commands, see [SPOQ 1.0](../../operational/SPOQ_1.md). Model names and old
> epic/map examples below describe the original paper implementation.

This document provides a comprehensive reference for the SPOQ (Specialist Orchestrated Queuing) methodology.

## Overview

SPOQ is a methodology for orchestrating multi-agent software development through wave-based parallel execution with structured quality gates.

### How Parallel Execution Works

Claude Code's Task tool spawns sub-agents that run concurrently. In practice:
- A single terminal session can run **10-20+ parallel sub-agents**
- Each sub-agent works independently on its assigned task
- The orchestrating agent coordinates results as they complete

This is real parallelism, not simulated. Tasks within a wave execute simultaneously, limited only by API rate limits and context management.

### Core Principles

1. **Wave-Based Dispatch**: Tasks execute in parallel waves determined by dependency analysis
2. **Dual Validation Gates**: Quality checks before and after execution
3. **Human-as-an-Agent (HaaA)**: Humans participate as specialized agents in the swarm
4. **Hierarchical Specialization**: Different model tiers for different roles

## Three-Tier Agent Hierarchy

SPOQ uses three agent tiers optimized for different roles:

### Worker Tier (Opus)

**Role**: Primary task execution

**Characteristics**:
- Highest capability model
- Handles complex implementation work
- Writes production code
- Creates comprehensive tests

**When to use**: All primary development tasks

### Reviewer Tier (Sonnet)

**Role**: Quality assurance and validation

**Characteristics**:
- Balanced capability and cost
- Reviews completed work
- Scores against metrics
- Identifies issues

**When to use**: Post-execution validation, code review

### Investigator Tier (Haiku)

**Role**: Failure triage and analysis

**Characteristics**:
- Lowest cost, fastest response
- Analyzes build failures
- Provides quick diagnostics
- Suggests fixes

**When to use**: When execution fails, initial error analysis

### Platform Independence

SPOQ methodology is platform-agnostic. The tier structure maps to other providers:

| Tier | Anthropic | OpenAI | Google |
|------|-----------|--------|--------|
| Worker | Opus | GPT-4 | Ultra/Pro |
| Reviewer | Sonnet | GPT-4-turbo | Pro |
| Investigator | Haiku | GPT-3.5 | Flash |

## Four-Stage Pipeline

### Stage 1: Plan

**Activities**:
- Define epic goal and scope
- Decompose into atomic tasks
- Establish dependencies
- Assign wave numbers

**Output**: EPIC.md + task YAML files

**Commands**:
```bash
/epic-planning "Feature description"
```

### Stage 2: Execute

**Activities**:
- Dispatch waves sequentially
- Run tasks within each wave in parallel
- Capture results in journal
- Handle failures with investigators

**Output**: Code changes, tests, artifacts

**Commands**:
```bash
/agent-execution @spoq/epics/epic-name
```

### Stage 3: Validate

**Activities**:
- Score work against 10 code metrics
- Verify acceptance criteria
- Check test coverage
- Review security

**Output**: Validation scores, pass/fail determination

**Commands**:
```bash
/agent-validation
```

### Stage 4: Integrate

**Activities**:
- Merge changes to main branch
- Update journal with completion
- Archive epic if complete
- Prepare for next phase

**Output**: Merged code, updated journal

## Wave-Based Topological Dispatch

### How Waves Work

Tasks are organized into waves based on their dependencies:

```
Wave 0: Independent tasks (no dependencies)
Wave 1: Tasks depending only on Wave 0
Wave 2: Tasks depending on Wave 0 or Wave 1
...
Wave N: Tasks depending on any previous wave
```

### Algorithm

```
1. Build dependency graph from task definitions
2. Topological sort to identify execution order
3. Group tasks by longest path to root
4. Tasks with same longest path = same wave
5. Execute waves sequentially, tasks within waves in parallel
```

### Example

```yaml
# Task A (Wave 0): No dependencies
# Task B (Wave 0): No dependencies
# Task C (Wave 1): Depends on A
# Task D (Wave 1): Depends on B
# Task E (Wave 2): Depends on C and D

Wave 0: [A, B]      # Parallel
Wave 1: [C, D]      # Parallel (after Wave 0)
Wave 2: [E]         # After Wave 1
```

### Critical Path

The **critical path** is the longest chain of dependent tasks. It determines:
- Minimum possible project duration
- Which tasks cannot be parallelized
- Where delays have maximum impact

## Epic Structure

### EPIC.md Format

```markdown
# Epic Title

## Overview
[Brief description]

## Architecture
[System design, ASCII diagrams]

## Wave Structure
[Task dependencies and wave assignments]

## Success Criteria
[Measurable completion conditions]

## Risk Assessment
[Known risks and mitigations]
```

### Task YAML Format

```yaml
# Identity
id: 01-task-name
title: Human-readable title
description: |
  Detailed task description

# Execution
phase: 0  # Wave number
depends_on:
  - other-task-id

# Deliverables
deliverables:
  - path/to/file.ts
  - path/to/test.ts

# Quality
acceptance_criteria:
  - Specific, testable criterion
  - Another criterion

# Optional
human_required: false
expertise_tags:
  - typescript
  - api-design
```

## Human-as-an-Agent (HaaA)

### Concept

The human participates as a specialized agent in the swarm, not just as an orchestrator.

### Human Roles

1. **Strategic Decisions**: High-level direction and priorities
2. **Review Gating**: Approve critical changes before merge
3. **Domain Expertise**: Provide knowledge agents lack
4. **Exception Handling**: Handle edge cases agents can't resolve

### Consultation Pattern

Agents can request human consultation during execution:

```
Agent: "I need clarification on [specific question]"
       "Options: A, B, or C"
       "My recommendation: B because [reasoning]"