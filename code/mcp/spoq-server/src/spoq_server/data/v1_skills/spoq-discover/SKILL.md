---
name: spoq-discover
description: Record user constraints, uncertainties and planning decisions for a SPOQ discovery phase before decomposition. Use when a saved strategy requests discovery or the user asks for PIQARD discovery.
---

# SPOQ discovery

Read the user goal, repository history and the invocation through
`../spoq/references/workflows.md`. Inspect existing code and connected context;
record known constraints, unresolved questions, decisions, alternatives and their
sources. Reuse prior user answers. Ask only questions that change correctness or
scope; make routine technical choices with stated assumptions.

This phase produces reviewable discovery content, not Features/Tasks or code.
PIQARD puts its narrative and actual human review before decomposition. Identify
needed diagram/ERD, algorithm or formal outputs from the saved route. Report
missing capabilities honestly; a specification does not establish proof.

Return the declared `discovery` output with source/provenance and observed research
or repository checks. Keep the supplied run/scope/phase/attempt identities, input
hashes and lease. The caller submits completion and advances the strategy; this
skill must not start another run or infer a user's approval. A direct discovery
request returns its findings and saved artifact references without implementation.
