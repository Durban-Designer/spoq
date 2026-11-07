# Initial source verification

The initial extraction was verified on 2026-11-07 UTC before its first push.

| Check | Observed result |
|---|---|
| Source tests, Python 3.14, search and Codex extras | 759 passed; no skips |
| Fresh wheel installation, Python 3.12, same extras | 755 package tests passed; no skips |
| Python compilation and dependency consistency | Passed |
| Wheel and source distribution builds | Passed; removed backend modules absent |
| Standalone paper build | Passed; 55-page PDF generated |
| Updated paper first page | Rendered and visually checked |
| Real stdio MCP and source bootstrap | Passed; 27 tools; create/DAG path exercised |
| Independent targeted review | 169 tests passed; no functional blocker found |
| Gitleaks 8.30.1, complete selected source tree | No credential findings |

Tests use synthetic data. Live authenticated Claude or Codex model execution
was not repeated for the extraction; local protocol and installation checks
exercise the split itself. The paper retains its existing nonfatal TeX box
warnings; this work does not claim a complete typography review of all pages.

The Git history starts with the curated snapshot. A credential scan is not an
ownership review: read [SOURCE_REVIEW.md](SOURCE_REVIEW.md) before changing
visibility. Neither package publication nor public repository visibility is
enabled by the CI workflow.

Reproduce the source checks with:

```bash
uv sync --project code/mcp/spoq-server --locked --extra search --extra codex
uv build --project code/mcp/spoq-server
uv run --project code/mcp/spoq-server --extra search --extra codex python -m pytest code/mcp/spoq-server/tests tests -q
make -C documents/latex/projects/spoq-paper pdf
```

The wheel test has four fewer tests because the repository-level source
boundary checks run against the checkout, outside the installable package.
