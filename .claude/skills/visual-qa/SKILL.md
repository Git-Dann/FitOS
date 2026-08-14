---
name: visual-qa
description: Capture and review UI screenshots for a FitOS route before marking it complete. Use when finishing a route, checking responsive behaviour, or asked to review how something looks.
---

# Visual QA

Reference: `docs/design-system.md` and `docs/design-concepts.md`. A route is not complete until this
has run and its findings are fixed.

## 1. Capture

Three viewports, every time:

| Viewport | Size |
| --- | --- |
| Desktop | 1440 × 900 |
| Tablet | 1024 × 768 |
| Mobile | 390 × 844 |

```bash
pnpm test:visual --route <route> --update
```

Screenshots land in `docs/screenshots/<route>/`. Capture against the seeded demo tenant so the
content is deterministic — screenshots from ad-hoc data cannot be compared across runs.

## 2. Capture the states too

A happy path alone is not completion. Capture: empty, loading, delayed, partial, error and
unauthorised. Chromium is pre-installed; do not run `playwright install`.

Loading skeletons must match the final layout. Compare the loading and loaded captures directly — if
anything reflows, that is a defect.

## 3. Review

Hand the captures to the `design-reviewer` subagent with the route name and the document sections
that apply. It returns findings with severities.

Check yourself, before delegating, the four things most often missed:

- Tabular numerals on every numeric column, and columns that stay aligned as values change.
- Every chart has all six of: scale, axis, source, as-of time, accessible summary, data table or
  export.
- Observed and modelled values are visibly different components, not the same card with different
  words.
- Exposure never appears without its confidence band adjacent.

## 4. Accessibility

```bash
pnpm test:e2e --grep @a11y --route <route>
```

axe must pass. Then check by hand what axe cannot: keyboard reachability of every control, visible
focus, logical tab order, status conveyed by more than colour, and reflow at 320 px equivalent.

## 5. Fix and re-verify

Fix P0 and P1 findings, re-capture, re-review. Do not mark the route complete with an open P0 or P1.

Commit the approved screenshots as the visual baseline. Note in the commit message which findings
were fixed, and record any deliberate deviation from a design rule with its reason — an explained
deviation is not a defect, but an unexplained one is.
