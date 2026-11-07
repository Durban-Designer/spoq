# SPOQ MCP server

SPOQ 1.x stores Project Plans, Features, Tasks, journals, task claims, and
agent discussions in local SQLite. It exposes 27 MCP tools and a matching CLI.

```bash
pipx install spoq
spoq init --target /path/to/project --with-mcp --agents claude,codex
spoq mcp --root /path/to/project
```

Use `/spoq` for the composed delivery workflow, `/spoq-plan` to plan, and
`/spoq-plan-validation`, `/spoq-execution`, or `/spoq-validation` to invoke
individual stages. Use the corresponding skill mentions in clients that
support them. Upgrades prompt before converting old files: maps become
Project Plans, epics become Features, and source backups are retained.

Optional `spoq[search]` enables CPU embeddings and sqlite-vec; `spoq[codex]`
adds the app-server notification bridge. Keyword search needs no model.

This source includes legacy filesystem compatibility with `SPOQ_STORE=fs`;
commercial HTTP integrations are excluded. It was extracted after the PyPI
1.0.0 release and must be built and versioned separately before a new upload.

From a source checkout, run `uv sync`, `uv run pytest`, and `uv build` in this
directory. See the repository root for methodology, paper, and separation notes.
