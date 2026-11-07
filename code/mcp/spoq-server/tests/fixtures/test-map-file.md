# Map: Test Pipeline

## Vision

Build a three-stage data processing pipeline with a foundation service, an API layer, and an end-to-end test suite. Each stage is delivered as an independent epic, coordinated through this map to enforce ordering and integration constraints.

## Program Structure

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  alpha-service  │────►│  beta-api       │────►│  gamma-tests    │
│  (foundation)   │     │  (api layer)    │     │  (validation)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Epics

### alpha-service
- **Status:** pending
- **Dependencies:** none
- **Summary:** Foundation service providing core data models and a configuration parser. Establishes the shared schema consumed by downstream epics.

### beta-api
- **Status:** pending
- **Dependencies:** [alpha-service]
- **Summary:** REST API layer built on top of alpha-service. Exposes CRUD endpoints and validation routes that delegate to the foundation models.

### gamma-tests
- **Status:** pending
- **Dependencies:** [beta-api]
- **Summary:** End-to-end test suite exercising the full pipeline from API calls through the foundation service. Verifies cross-epic integration.

## Epic Dependencies

```
Wave 0:
    alpha-service ──► beta-api (Wave 1) ──► gamma-tests (Wave 2)
```

## Dispatch Strategy

**Wave 0 (Parallel):** alpha-service
- Foundation data models and configuration with no prerequisites

**Wave 1 (Sequential):** beta-api
- API implementation consuming alpha-service outputs

**Wave 2 (Sequential):** gamma-tests
- Integration testing across the assembled pipeline

## Success Criteria

- [ ] Foundation models parse and validate configuration files
- [ ] API endpoints return structured responses
- [ ] End-to-end tests exercise the complete data flow
- [ ] All three epics pass individual validation
- [ ] Cross-epic interfaces are documented

