---
name: spoq-design
description: Produce reviewable SPOQ narrative plans, diagrams, ERDs, algorithms or formal evidence for a declared design phase. Use when a saved strategy requests a design artifact.
---

# SPOQ design artifacts

Read the invocation and `../spoq/references/workflows.md`. Produce only its declared
outputs, using its discovery and selected prior artifacts. Keep source text and
observed verification distinct; the engine checks content contracts, not diagram
syntax or the truth of an unexecuted proof.

- `narrative_plan`: Markdown or structured JSON with nonempty scope, decisions,
  assumptions, risks and acceptance_criteria. Incorporate selected design outputs
  and any recorded rejection findings. Save before decomposition or implementation.
- `diagram` / `erd`: reviewable Mermaid source with a declared diagram type and
  nonempty body; ERDs start with `erDiagram`. Retain source even if no renderer is
  available. Record syntax/render checks only when actually performed.
- `algorithm`: inputs, outputs, invariants and complexity assumptions.
- `formal`: JSON with status specified/tested/proven/disproven/unverified and a
  specification. Tested/proven/disproven need observed verifier tool/version,
  command, integer exit_code, source and result. Proven also needs proof content
  and explicit assumptions; disproven needs a counterexample; unverified needs
  a reason. Unavailable required proof capability blocks the phase.

Markdown is the default narrative. A Confluence reference may include URL/version
and a reviewed attached export, with reviewed_export=true only after actual review.
A URL alone is not content; this skill does not synchronize or publish documents.

Preserve run/scope/phase/attempt IDs and input hashes. Return the actual artifact
content and evidence through the workflow completion contract. Approval belongs
to the following human phase, after the user sees the exact revision. A peer
message or this skill's own review cannot satisfy that checkpoint. Direct design
requests stop at the requested artifacts and do not decompose or implement work.
