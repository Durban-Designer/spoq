# Source verification

## Initial 1.0 extraction

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


## Curated 1.1 refresh — 2026-11-11

These checks were performed locally before the reviewed update's Git commit,
GitHub CI and public-visibility action. They describe the curated edition, not
replacement PyPI artifacts or live model inference.

| Check | Observed result |
|---|---|
| Locked source tests, Python3.14, search/Codex extras | 1597 passed; no skips |
| Fresh installed wheel, Python3.12, same extras | 1593 passed; no skips |
| Installed wheel identity/cohort reuse | Exact wheel SHA unchanged; all57 installed versions match repaired lock |
| Contributor viewer units | 39 passed across5 files |
| Viewer format/build/fingerprint and package asset guard | Passed |
| Locked Python runtime audit, all extras | 52 packages; zero advisory flags |
| Viewer npm dependency audit | Zero advisory flags |
| Installed Classic CLI and PIQARD MCP paths | Passed scripted delivery, revision, rejection, negative and eight fault/recovery cases |
| Installed packaged viewer with real browser | Passed; strategy/work/history/evidence/reconnect actions checked |
| Final sdist fresh install and workflow smoke | Nine commands passed in a separate Python3.12 environment |
| Python compileall, dependency consistency, wheel/sdist builds | Passed |
| Standalone paper build | Passed;55-page PDF; paper source unchanged |

The first full source run had23 failures because two generic normative support
inputs were omitted from the selected copy. The missing synthetic viewer fixture,
strategy contract and referenced UI contract were selected explicitly; all31
affected/boundary cases then passed. The next full source and installed suites
passed. A full locked dependency audit exposed67 advisory flags across nine stale
transitive pins retained from1.0. The already-audited1.1 lock was checked against
this curated manifest and applied; the final audit is clean and the source suite
passed again on that repaired cohort. GitHub CI now requires the runtime audit.
No advisory was suppressed and no implementation attempt budget was increased.

The final wheel SHA-256 is
`ac09a0777b7495c40bdc808775fb2c98e86f54d04aae1bb74aed4756cd126297`.
The final source-distribution SHA-256 is
`0db3a7ab6d89ca202a8328f4629812c7ba04ca547d4f3756c412e64b0fe09640`.
The dependency repair changes the sdist lockfile but leaves the wheel bytes
unchanged. Previously passing installed/runtime/browser evidence was reused only
after comparing the exact wheel digest, installed package contents and all57
resolved distribution versions to the final locked cohort. The final sdist was
separately installed and exercised after its rebuild.

The initial sdist smoke harness omitted a required Feature parent; the product
correctly rejected it. The corrected harness created a Project Plan first and
passed in a separate workspace. No product defect or fabricated success is hidden
by that correction. Raw failed checks remain in the release operator's local
review evidence, alongside current receipts.

The four repository-level source-boundary cases explain the difference between
source and installed test counts. Guard mutation tests use isolated temporary
frontend copies; the checked-in viewer inputs/assets were not mutated by parallel
suites. The final publication review separately binds source selection, archive
contents, secret scans, retained history and GitHub CI to an exact commit.

No authenticated Claude/Codex model call or native Windows/macOS test was run.
Browser checks used host Chromium; no broad cross-browser or new performance
claim is made. Historical paper text and nonfatal TeX box warnings remain; the
unchanged paper did not receive a new full-page visual typography audit.
