# Source repository instructions

- Keep the public source limited to the generic MCP, methodology, paper, tests,
  and their build inputs. Do not copy customer source, private work plans,
  credentials, conversation logs, or deployment infrastructure into this repo.
- Keep project data in ignored `.spoq/`; do not commit working databases.
- Use Project Plans → Features → Tasks and the bundled `/spoq` stages.
- Add meaningful unit tests for behavior changes. Compile and run the changed
  code; fix failures before declaring work complete.
- From the root, use `uv run --project code/mcp/spoq-server python -m pytest
  code/mcp/spoq-server/tests tests -q` and `uv build --project code/mcp/spoq-server`.
- Build the paper with `make -C documents/latex/projects/spoq-paper pdf`.
- Use `docker compose` if Compose is introduced.
- Record local work in ignored `journal.md`, with accurate timestamps and a
  confidence score from 0.0 to 1.0. Keep externally shared claims grounded in checks.
- Do not publish packages, change repository visibility, or push without explicit
  user authorization. The initial extraction is authorized as a private snapshot.
