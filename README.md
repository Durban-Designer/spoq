# SPOQ

Specialist Orchestrated Queuing combines dependency-aware coding agents,
planning and implementation quality gates, and human participation.

This curated source repository contains the generic MCP/CLI, portable skills,
local viewer and its build inputs, synthetic tests, methodology and paper source.
SPOQ 1.1 stores **Project Plans → Features → Tasks** in SQLite: a Project Plan
has a Feature DAG and each Feature has one task DAG. A separate strategy graph
records how discovery, design, review, planning and delivery proceed.

## Start using SPOQ 1.1

Python 3.12 or newer is required. To install the already-published distribution:

```bash
pipx install spoq==1.1.0
spoq init --target /path/to/project --with-mcp --agents claude,codex
```

Open that project in your coding client and use `/spoq "your goal"` to deliver
end to end, or `/spoq-plan "your goal"` for planning only. Codex uses `$spoq`
and `$spoq-plan` skill mentions. Claude Code, Codex, Qwen Code and Cursor
scaffolding is included; the coding client supplies models and permissions.

Classic retains planning, planning validation, execution and implementation
validation. Compact Classic adjusts effort for small, clear work without dropping
gates. PIQARD (“plan it quickly, AI records decisions”) gathers decisions and
selected diagrams, ERDs, algorithms or formal records into a narrative plan,
then requires a human response to that exact revision before decomposition.
Recorded formal evidence is not an independently executed theorem proof.

```bash
spoq workflow list --root /path/to/project
spoq workflow inspect RUN_ID --root /path/to/project
spoq ui --root /path/to/project --run RUN_ID --no-open
```

Replace RUN_ID with an actual saved run. Open the printed loopback URL to view
strategy phases, work DAGs, attempts, artifacts and evidence. The packaged viewer
is read-only, launches no model and needs no Node runtime on end-user machines.
Task claims, phase leases, validation and retry budgets persist across restarts.

## Upgrade existing projects

```bash
pipx upgrade spoq
spoq workflow upgrade --root /path/to/project --dry-run
spoq workflow upgrade --root /path/to/project --yes
spoq init --upgrade --target /path/to/project
```

Review the schema preview before confirming. Existing schema-1 stores need an
explicit backed-up upgrade to schema 2; old binaries reject schema 2. Historical
pre-1.0 files have a separate `spoq migrate --dry-run` conversion preview. Maps
become Project Plans, epics become Features, and dependencies/backups are retained.
Reload existing client sessions after refreshing skills and MCP registration.

## Develop from this source

Install [uv](https://docs.astral.sh/uv/) and run:

```bash
uv sync --project code/mcp/spoq-server --locked --extra search --extra codex
uv run --project code/mcp/spoq-server spoq --help
python3 code/scripts/build-spoq-ui.py --check
uv build --project code/mcp/spoq-server
uv run --project code/mcp/spoq-server python -m pytest code/mcp/spoq-server/tests tests -q
```

The source bootstrap is `./scripts/spoq-init.sh --target /path/to/project`.
Optional `search` dependencies provide local CPU embeddings and SQLite vector
search; keyword search is included without model weights. The `codex` extra
supports the optional local app-server bridge. Native subagents can use relay
or inbox reads; their runtime handles are not CLI session UUIDs.

To change the local viewer, use Node 22.13+ and its locked contributor build:

```bash
npm --prefix code/apps/spoq-ui ci
npm --prefix code/apps/spoq-ui test -- --runInBand
npm --prefix code/apps/spoq-ui run format:check
npm --prefix code/apps/spoq-ui run build
python3 code/scripts/build-spoq-ui.py
python3 code/scripts/build-spoq-ui.py --check
```

Commit the generated package assets alongside changed production inputs.
The guard rejects stale inputs, escaping paths and private environment files.
GitHub CI verifies this build before source/installed Python checks.

## Methodology and paper

- [Current operation and migration](documents/operational/SPOQ_1.md)
- [Original methodology](documents/core/architecture/METHODOLOGY.md)
- [Validation framework](documents/core/architecture/VALIDATION.md)
- [Paper source](documents/latex/projects/spoq-paper/src/main.tex)
- [Source separation and provenance](documents/operational/SOURCE_REVIEW.md)
- [Verification record](documents/operational/SOURCE_VERIFICATION.md)

With TeX Live's recommended, extra, science, pictures and font packages, run
`make -C documents/latex/projects/spoq-paper pdf`. The result is
`documents/latex/projects/spoq-paper/output/main.pdf`. Research observations,
model configurations and historical terminology describe the original evaluated
workloads, rather than new performance measurements of 1.1.

This repository retains its curated history beginning at the 1.0 snapshot. It
omits optional commercial HTTP integrations that exist in the immutable PyPI
1.0.0/1.1.0 distributions. A wheel built from this checkout identifies as 1.1.0
but is a **curated source edition**, not a byte-identical reconstruction of the
published PyPI wheel. This update does not replace or republish those artifacts.
Package publication and repository visibility changes are not automated by CI.

MIT license. Attribution and citation metadata remain in [LICENSE](LICENSE)
and [CITATION.cff](CITATION.cff).
