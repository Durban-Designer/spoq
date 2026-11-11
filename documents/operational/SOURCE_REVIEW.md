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
The owner authorized the reviewed 1.1 refresh and public promotion on 2026-11-11.
Visibility is changed separately by the release operator after exact-source review
and CI; this note is not a claim that the promotion has already occurred.
This extraction does not change the existing published PyPI artifact.


## 1.1 source refresh

The original exclusions remain in force. New selected inputs are the generic
strategy engine, bundled Classic/PIQARD definitions, discovery/design skills,
local read-only viewer, contributor viewer source and build guard, and synthetic
unit/process/browser tests. The contributor app under `code/apps/spoq-ui` is the
local MCP viewer; the commercial marketing website and cloud infrastructure
remain excluded. No other application tree was imported.

The curated 1.0 config/CLI removals and synthetic fixture adaptations were retained.
Source version is now 1.1.0. Compiling this checkout produces a curated edition
that differs from the immutable PyPI1.1.0 wheel, including removal of commercial
HTTP/import integration. No PyPI artifact is replaced or uploaded by this update.
Repository URLs point to this GitHub project; older published metadata remains
part of those immutable artifacts.

The paper's existing research text, author identities, affiliations, citation
metadata, aggregate observations and named adopter/acknowledgments are preserved.
The owner requested public promotion after the private review period. Automated
boundary and secret scans supplement that authorization; they do not establish
ownership rights or independently prove every research claim.


## 1.1.1 repository metadata patch

This curated checkout advances its package/viewer release metadata to 1.1.1.
Production Python bodies, contributor viewer source and compiled JS/CSS are
unchanged from the reviewed1.1.0 snapshot. Only version/build-provenance stamps,
release-aware verification/CI and current installation/provenance text change.
Strategy schema/template versions and historical fixtures retain their meanings.

The separately built full PyPI1.1.1 patch corrects Project-URL repository metadata
without removing any runtime module from the original full1.1.0 distribution.
The curator's existing commercial adapter/import exclusions remain unchanged;
therefore this checkout's wheel is not the artifact to upload as that full patch.
No dependency pins were changed beyond the root distribution version.
