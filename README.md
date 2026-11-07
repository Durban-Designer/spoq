# SPOQ

Specialist Orchestrated Queuing combines dependency-aware agent execution,
planning and implementation quality gates, and human participation.

This repository contains the MCP server, portable agent skills, tests,
methodology reference, and paper source. The 1.x model is **Project Plans →
Features → Tasks**: a Project Plan has a Feature DAG, and each Feature has a
Task DAG. SQLite in `.spoq/spoq.db` is the authoritative project store.

## Start using SPOQ

Python 3.12 or newer is required.

```bash
pipx install spoq
spoq init --target /path/to/project --with-mcp --agents claude,codex
```

In your coding client, use `/spoq "your goal"` for delivery from planning
through verification, or `/spoq-plan "your goal"` for planning only. Clients
with skill mentions can use `$spoq` and `$spoq-plan`. Claude Code, Codex,
Qwen Code, and Cursor scaffolding is included.

For existing projects, run `spoq init --upgrade --target /path/to/project`.
Review the conversion preview before confirming. Legacy maps become Project
Plans; epics become Features; task dependencies and source backups are preserved.

## Develop from source

Install [uv](https://docs.astral.sh/uv/) and then run:

```bash
uv sync --project code/mcp/spoq-server --locked
uv run --project code/mcp/spoq-server spoq --help
uv run --project code/mcp/spoq-server python -m pytest code/mcp/spoq-server/tests tests -q
uv build --project code/mcp/spoq-server
```

The source bootstrap is `./scripts/spoq-init.sh --target /path/to/project`.
The default MCP launcher is `spoq mcp --root /path/to/project`. Optional
`search` dependencies provide local CPU embeddings and SQLite vector search;
the core installation includes keyword search. `codex` dependencies support
the optional app-server notification bridge. Model downloads and live coding
clients need their respective network access or accounts.

## Read and build the paper

- [Current operation and migration](documents/operational/SPOQ_1.md)
- [Original methodology](documents/core/architecture/METHODOLOGY.md)
- [Validation framework](documents/core/architecture/VALIDATION.md)
- [Paper source](documents/latex/projects/spoq-paper/src/main.tex)
- [Source separation review](documents/operational/SOURCE_REVIEW.md)

With TeX Live, including the recommended, extra, science, pictures, and fonts
packages, run `make -C documents/latex/projects/spoq-paper pdf`. The result is
`documents/latex/projects/spoq-paper/output/main.pdf`.

This repository begins with a curated source snapshot and has no imported Git
history. The already-published PyPI 1.0.0 package predates this extraction;
this source omits optional commercial integrations and is not a byte-identical
reconstruction of that distribution. No package publication is automated here.

MIT license. Attribution and research citation metadata are in [LICENSE](LICENSE)
and [CITATION.cff](CITATION.cff). Study results and historical terminology in
the paper describe the evaluated implementation, rather than measurements of
the SQLite rewrite.
