# Epic: [Epic Name]

## Overview

[TODO: 2-3 sentences describing what this epic accomplishes, why it matters, and the target outcome]

## Architecture

```
[TODO: ASCII diagram showing components and data flow]

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Component A │────►│ Component B │────►│ Component C │
└─────────────┘     └─────────────┘     └─────────────┘
        │                   │
        │                   ▼
        │           ┌─────────────┐
        └──────────►│ Component D │
                    └─────────────┘
```

## Components

### 1. [Component Name]
- Key responsibility
- Files/modules involved
- External dependencies

### 2. [Component Name]
- Key responsibility
- Files/modules involved
- External dependencies

### 3. [Component Name]
- Key responsibility
- Files/modules involved
- External dependencies

## Success Criteria

- [ ] [Specific, measurable criterion with verification command]
- [ ] [Service health check: `curl http://localhost:8080/health`]
- [ ] [Test suite passes: `npm test` or `./gradlew test`]
- [ ] [Build succeeds: `npm run build` or `./gradlew build`]
- [ ] [Integration test: specific endpoint returns expected response]
- [ ] [Performance: operation completes in <X seconds]
- [ ] [Documentation: README updated with usage instructions]
- [ ] [No regressions: existing functionality preserved]

## Task Dependencies

```
[TODO: ASCII DAG showing task relationships]

Wave 0 (foundation):
    01 ──────────┐
                 │
    02 ──────────┼──► Wave 1
                 │
    03 ──────────┘

Wave 1 (implementation):
         ┌──► 04 ──┐
    ─────┤         ├──► Wave 2
         └──► 05 ──┘

Wave 2 (integration):
    ─────────────────► 06
```

## Dispatch Strategy

**Wave 0 (Parallel):** Tasks 01, 02, 03
- Foundation setup with no dependencies
- Can be executed concurrently by separate agents

**Wave 1 (Parallel):** Tasks 04, 05
- Core implementation
- Requires Wave 0 completion

**Wave 2 (Sequential):** Task 06
- Integration and testing
- Requires Wave 1 completion

**Critical Path:** 01 → 04 → 06 (3 tasks)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [External API dependency] | Medium | High | [Mock service for testing] |
| [Database schema changes] | Low | Medium | [Migration scripts with rollback] |
| [Integration complexity] | Medium | Medium | [Incremental integration testing] |
| [Performance requirements] | Low | High | [Early load testing] |

## Prerequisites

Before starting this epic, ensure:
- [ ] [Required service is running]
- [ ] [Database is set up]
- [ ] [API keys are configured]
- [ ] [Development environment is ready]

## Notes

[Any additional context, decisions made, or technical debt to address]
