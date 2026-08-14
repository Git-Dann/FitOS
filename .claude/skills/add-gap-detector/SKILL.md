---
name: add-gap-detector
description: Add a new gap detector to the FitOS detection framework. Use when asked to detect a new kind of gap, add a detector rule, or implement a threshold, comparison, funnel, anomaly, mismatch or data-quality check.
---

# Add a gap detector

Reference: `docs/gap-model.md`. Detection is deterministic, versioned and replayable. AI is never the
detector.

## Steps

1. **Name the comparison.** In one sentence: what is observed, and what is it compared against? A
   detector with no defined expectation produces a metric with an opinion, not a gap. If you cannot
   write the sentence, stop.

2. **Pick the class** from the twelve in the brief: static threshold, ratio threshold, baseline,
   peer/location, funnel drop, seasonality-aware anomaly, source mismatch, freshness, completeness,
   schema drift, repeated exception, financial leakage.

3. **Declare inputs.** Governed metrics by key and version, plus any canonical facts. If the metric
   does not exist yet, define it first — never compute the formula inside the detector, because that
   duplicates a definition and breaks the one-formula rule.

4. **Write the versioned configuration schema.** Thresholds, windows, minimum sample size, peer group
   definition. Bump `rule_version` on any change that alters output; old versions must stay
   replayable because gaps reference them.

5. **Implement** against the detector interface with typed inputs and outputs. The run must record
   detector and rule version, input metric versions, query hash, observation window, thresholds,
   output candidates, suppressed candidates, dedupe decisions, duration and errors.

6. **Exposure.** If the gap carries money, produce `low`, `base`, `high`, the formula key and
   version, and every assumption with its source. Never a point estimate. If the `high/low` ratio
   exceeds the pack limit, add reason code `wide_exposure_interval` and cap the band.

7. **Confidence.** Emit component scores; do not emit a total. The framework combines them. Drop
   components that do not apply and record which were dropped. Attribution-based detectors are
   capped at `medium` with reason code `attribution_limited`.

8. **Dedupe key.** Must exclude the observation window and the values, so the same problem in the
   same scope on consecutive days is one evolving gap with a timeline. Test this explicitly with a
   multi-day fixture — it is the failure mode that floods the ledger.

9. **Suppression.** If a contributing source has an open freshness or completeness gap, emit
   `suppressed_by_data_quality`, cap confidence and link the data-quality gap. Do not hide the gap: a
   data outage must not look like calm.

10. **Golden fixtures.** A fixed input produces a byte-identical gap set. Cover: fires correctly,
    does not fire below threshold, dedupes across days, handles a null denominator, handles an empty
    window, and respects the minimum sample size.

11. **Replay.** Re-running at the pinned version over the same window reproduces the same output.

## Verify

`pnpm test:data --filter detectors/<key>`, then `pnpm demo:verify` to confirm the seeded scenarios
still produce their expected gaps. A new detector that changes an existing scenario's output is a
regression until proven otherwise.
