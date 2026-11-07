# Epic: Config Validator Service

## Overview

Build a configuration validation microservice that checks YAML and JSON config files against predefined schemas. The service exposes a REST API for integration with CI/CD pipelines and includes a lightweight React form for manual uploads. Validation results are returned as structured JSON reports suitable for both human review and automated gating.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ REST API     │────►│ Validator    │────►│ Schema Store │
│ (FastAPI)    │     │ Engine       │     │ (File-based) │
└──────────────┘     └──────────────┘     └──────────────┘
        │                    │
        ▼                    ▼
┌──────────────┐     ┌──────────────┐
│ Auth Layer   │     │ Report Gen   │
└──────────────┘     └──────────────┘
```

The **REST API** receives file uploads and delegates parsing to the **Validator Engine**, which loads schemas from a local file store. An optional **Auth Layer** guards sensitive endpoints, while the **Report Generator** formats structured output for downstream consumers.

## Components

### 1. Config Parser
- Parses YAML and JSON configuration files into a normalized internal representation
- Detects file format from content headers rather than extensions alone
- Files: src/config.py

### 2. Web Interface
- React-based form for uploading configuration files manually
- Provides instant client-side feedback before server round-trip
- Files: src/components/Form.tsx

### 3. REST API
- FastAPI endpoints handling validation requests and health monitoring
- Returns structured JSON with per-field error annotations
- Files: src/config.py, src/api.py

### 4. Test Suite
- Comprehensive integration and unit tests covering all validation paths
- Includes edge-case fixtures for malformed input
- Files: tests/test_api.py

## Success Criteria

- [ ] Config parser handles YAML and JSON formats without data loss
- [ ] React upload form renders and validates file type before submission
- [ ] POST /validate endpoint returns structured validation results
- [ ] Health check endpoint responds with 200 within 50ms
- [ ] Integration tests cover the full upload-to-report workflow
- [ ] Docker container builds and starts without manual intervention
- [ ] Error responses include actionable messages with line numbers

## Task Dependencies

```
Wave 0 (Parallel):
    01-setup ──────────┐
                       │
    02-core ───────────┼──► 03-api ──► 04-tests
                       │
```

Tasks 01-setup and 02-core execute concurrently in Wave 0 since they have no mutual dependencies. Task 03-api waits for both to finish because the API layer integrates the config parser from 01 and receives uploads initiated by the form from 02. Task 04-tests runs last, exercising the assembled system end-to-end.

## Dispatch Strategy

**Wave 0 (Parallel):** Tasks 01, 02
- Foundation setup and front-end component work, no inter-dependencies

**Wave 1 (Sequential):** Task 03
- API implementation, depends on both 01-setup and 02-core

**Wave 2 (Sequential):** Task 04
- Integration testing, depends on 03-api

**Critical Path:** 01 -> 03 -> 04 (3 tasks)

