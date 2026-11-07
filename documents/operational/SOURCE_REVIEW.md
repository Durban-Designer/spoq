# Source separation review

This repository was created as a new Git history from an explicit file selection.
It contains the generic Python MCP server, bundled agent skills, synthetic tests,
methodology references, and the existing paper's LaTeX sources and bibliography.

The extraction excludes the commercial HTTP adapter and its import commands,
API-specific tests and fixtures, private planning corpus, journals, transcripts,
application experiments, website, cloud deployment configuration, local agent
configuration, databases, credentials, and generated release evidence.

Changes made for independence:

- Removed the commercial backend selector and retained SQLite plus explicit
  legacy filesystem support. Unsupported backends fail before opening a store.
- Replaced product-specific labels in synthetic fixtures with generic examples.
- Kept generic filesystem export coverage using the public parsers.
- Pointed compiler tests at bundled resources, without a private workspace path.
- Replaced website-dependent paper deployment with a local PDF build.
- Updated source repository URLs while preserving authorship and MIT attribution.

Before making the repository public, review the included paper and citation
metadata. The paper preserves its research text, aggregate observations, author
affiliations, and named external adopter/acknowledgments from the existing paper.
No customer repository contents or raw deployment inventory are included.
Historical methodology references are marked as such; the current 1.x guide
describes the SQLite rewrite without attributing old study results to it.

Automated boundary tests and a credential scan provide useful evidence, but
they cannot establish ownership or publication rights for every sentence.
Repository visibility is intentionally private for the owner's review.
This extraction does not change the existing published PyPI artifact.
