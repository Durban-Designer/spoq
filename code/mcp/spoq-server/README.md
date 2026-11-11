# SPOQ MCP server

SPOQ 1.1 stores Project Plans, Features, Tasks, journals, claims, conversations and
workflow history in local SQLite. It exposes 47 MCP tools and a matching CLI.

```bash
pipx install spoq==1.1.0
spoq init --target /path/to/project --with-mcp --agents claude,codex
spoq mcp --root /path/to/project
```

Use `/spoq` for saved Classic/PIQARD delivery, `/spoq-plan` for planning only,
and the independently invocable planning/execution/validation stages as needed.
PIQARD adds `/spoq-discover` and `/spoq-design`; a response to one narrative
revision cannot approve a replacement. Both strategies retain their quality gates.
The server records supplied evidence and computes verdicts; the coding client
performs checks and model work. The bundled `spoq ui` viewer is local/read-only.

Existing schema-1 stores require a previewed, confirmed schema-2 upgrade with a
consistent SQLite backup. Historical file conversion remains explicit: maps
become Project Plans, epics become Features, and dependencies/backups are kept.

Optional `spoq[search]` enables CPU embeddings and sqlite-vec; `spoq[codex]` adds
the local app-server bridge. Keyword search needs no embedding model. This
curated source keeps `SPOQ_STORE=fs` legacy compatibility and excludes commercial
HTTP adapters/import commands. Unsupported backend selection fails explicitly.

The curated source edition is version 1.1.0 and intentionally differs from the
immutable PyPI 1.1.0 package because excluded commercial integrations stay absent.
Building this source does not overwrite or republish an existing PyPI artifact.
Run `uv sync --locked`, `uv build` and `uv run pytest` in this directory; the
repository root documents reproducible viewer builds and all verification steps.
