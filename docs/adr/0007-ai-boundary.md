# ADR 0007 — AI boundary

Status: accepted · Date: 2026-08-14 · Phase: H

## Context

The product's defensibility is governed numbers with traceable evidence. An AI layer that can
produce, adjust or interpolate a number destroys that in one sentence, and no amount of disclaimer
copy repairs it. At the same time, explaining a gap in plain language, summarising evidence and
drafting an action plan are genuinely useful and hard to do with templates alone.

## Decision

**AI is a supporting layer. It never produces numeric truth.**

Concretely:

1. The assistant receives a **structured evidence bundle** assembled by the API and semantic layer
   under the caller's permissions. It has no database access, no SQL, and no ability to widen its own
   query.
2. Every number in an answer must be a **citation** to a value already in the bundle. Numbers are
   rendered by the UI from the cited object, not from the model's text.
3. Every answer cites internal metric, gap and evidence identifiers that the UI can open. A citation
   that does not resolve inside the bundle causes the answer to be **rejected**, not displayed with a
   warning.
4. Confidence scores and exposure ranges are computed by the detector and exposure models. The AI may
   explain a confidence score; it may not set, adjust or round one.
5. Source text (feedback, reviews, support messages, product descriptions) enters inside an explicit
   untrusted-content envelope. It is data, never instruction.
6. The MCP server is **read-first**: `list_metrics`, `get_metric_definition`,
   `query_certified_metric`, `list_gaps`, `get_gap`, `get_gap_evidence`, `list_source_health`. Write
   actions such as assignment or status change are separate tools with explicit permissions and
   confirmation.
7. Tenant context is applied server-side on every tool call. The model never supplies an
   organization id.
8. Causal language is prohibited unless an experiment or declared attribution method supports it.
   This is checked by an evaluation fixture, not only by a prompt instruction.

## Alternatives considered

**Text-to-SQL over the warehouse.** Powerful and increasingly expected. Rejected: it makes the model
the query author, which means the tenant filter, the dimension allowlist and the metric definition
all become things a model chose. Every guarantee in this product collapses at that point.

**AI as a detector.** Rejected by the brief and independently correct: detection must be
deterministic, versioned and replayable. A finding that cannot be reproduced at a pinned version
cannot be evidence.

**No AI at all.** Defensible, and tempting. Rejected because explanation and summarisation are real
work that templates do badly, and the boundary above makes the risk manageable.

## Consequences

- Bundle assembly is real engineering: it must gather the gap, its metric definitions, evidence
  references, confidence components, related gaps and source health, and filter all of it by the
  caller's capabilities before the model sees anything.
- Answer validation is a required component, not a nicety. An answer that fails citation resolution
  is dropped and the user is told the assistant could not ground its response.
- The evaluation suite gates Phase H: correct numeric citation, refusal to claim causation from
  correlation, confidence and assumption disclosure, tenant isolation, prompt injection inside source
  text, unsupported-question handling.
- Because the model cannot invent numbers, it will sometimes have to say "I cannot answer that from
  the available evidence." That is a correct behaviour and the UI treats it as one, not as an error
  state to be designed around.
