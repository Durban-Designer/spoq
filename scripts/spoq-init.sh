#!/usr/bin/env bash
set -euo pipefail
spoq_source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$spoq_source_root/code/mcp/spoq-server" spoq init "$@"
fi
if command -v spoq >/dev/null 2>&1; then
    exec spoq init "$@"
fi
echo 'Install uv or SPOQ 1.x to initialize a project.' >&2
exit 1
