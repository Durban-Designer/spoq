# Map: [Map Name]

## Vision

[TODO: 2-5 sentences describing the program-level objective. What outcome does completing all epics in this map achieve? Why does this collection of work need coordinated execution rather than independent epic planning?]

## Program Structure

```
[TODO: ASCII diagram showing epic relationships and data flow]

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Epic A     │────►│  Epic B     │────►│  Epic C     │
│  (foundation│     │  (core)     │     │  (integration│
└─────────────┘     └─────────────┘     └─────────────┘
        │                                      ▲
        │           ┌─────────────┐            │
        └──────────►│  Epic D     │────────────┘
                    │  (parallel) │
                    └─────────────┘
```

## Epics

### epic-slug-a
- **Status:** pending
- **Dependencies:** none
- **Summary:** One paragraph describing scope, key deliverables, and the role this epic plays within the broader map.

### epic-slug-b
- **Status:** pending
- **Dependencies:** [epic-slug-a]
- **Summary:** One paragraph describing scope, key deliverables, and how this epic builds on prior work.

### epic-slug-c
- **Status:** pending
- **Dependencies:** [epic-slug-a, epic-slug-b]
- **Summary:** One paragraph describing scope, key deliverables, and integration points with upstream epics.

## Epic Dependencies

```
[TODO: ASCII DAG of inter-epic relationships]

Wave 0:
    epic-slug-a ──────────┐
                          │
Wave 1:                   │
    epic-slug-b ──────────┼──► epic-slug-c (Wave 2)
                          │
```

## Dispatch Strategy

**Wave 0 (Parallel):** epic-slug-a
- Foundation work with no cross-epic dependencies

**Wave 1 (Sequential):** epic-slug-b
- Builds on Wave 0 outputs

**Wave 2 (Integration):** epic-slug-c
- Integrates deliverables from both prior waves

## Success Criteria

- [ ] [Program-level criterion spanning multiple epics]
- [ ] [End-to-end workflow verification across epic boundaries]
- [ ] [Performance or quality target for the assembled system]
- [ ] [Integration test covering cross-epic interfaces]
- [ ] [Deployment or operational readiness check]

**Critical Path:** epic-slug-a -> epic-slug-b -> epic-slug-c (3 epics, 3 waves)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [Cross-epic interface mismatch] | Medium | High | [Define interfaces in Wave 0 epic] |
| [Scope creep across epics] | Medium | Medium | [Freeze scope per-epic before Wave 1] |
| [Integration complexity] | Low | High | [Incremental integration tests per wave] |
