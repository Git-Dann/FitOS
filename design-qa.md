# Guided demo design QA

## Evidence

- Source visual truth: `/var/folders/qm/nlhwbcsj113_khmg044bkzdh0000gn/T/codex-clipboard-a95252ea-2c0b-4efb-88f9-926d34d69c1a.png`
- Implementation capture: `design-qa-implementation.png`
- Combined comparison: `design-qa-comparison.png`
- Source pixels: 2540 × 1540. It was normalized to 1280px wide for the combined comparison.
- Implementation pixels / CSS viewport / density: 1280 × 720 / 1280 × 720 / 1×.
- State: `/demo`, Quiet Store, Customer step, desktop light theme.
- Primary interactions checked: all four scenario selectors; Next step through Associate and Manager; corresponding role links present.

## Comparison history

### Pass 1

The source capture shows the pre-change scenario stage. The implementation intentionally adds a fixed-height stage and an evidence-led ROI lens, so the initial viewport starts higher in the page and the stage's lower content sits below the first 720px capture. This is intentional product scope rather than a fidelity mismatch.

The fixed stage did not change size while moving from Stock Discrepancy / Associate to Stock Discrepancy / Manager. Scenario cards retain their fixed desktop height, and the action row remains in the same position.

## Required fidelity surfaces

- **Fonts and typography:** The display hierarchy, dense UI labels, dark ink, all-caps eyebrow treatment, and compact action labels remain consistent with the source. The added proof cells use the existing small-label rhythm; no wrapping or truncation was visible in the tested desktop states.
- **Spacing and layout rhythm:** Scenario cards remain an even four-column row. The walkthrough is a fixed 508px desktop frame, with a fixed 472px content card and anchored actions. This removes the content-height shifts that previously moved the action row.
- **Colors and tokens:** The existing paper, deep green, mint status and fine grey-rule palette is retained. Added ROI evidence blocks use the existing green/muted token family and preserve contrast.
- **Image quality and asset fidelity:** The selected surface contains no photographic or decorative image asset. No image asset was substituted, generated, cropped or degraded.
- **Copy and content:** The generic signal callout was replaced with explicit `How it works`, `Value to validate` and `Measure in pilot` statements. The ROI lens explicitly says that ROI is not promised and names the retailer-verifiable measures instead.

## Findings

No actionable P0, P1 or P2 findings remain in the tested desktop flow.

### Follow-up polish

- [P3] Capture a dedicated 1440px presentation-mode screenshot if the demo will be shown on a large boardroom display; the current responsive stage is already stable at 1280px.

## Implementation checklist

- [x] Lock scenario card and walkthrough frame heights on desktop.
- [x] Keep primary actions in a fixed action row.
- [x] Add per-step mechanism, value and pilot-measure explanation.
- [x] Add a transparent ROI lens tied to observed pilot measures.
- [x] Verify scenario and step interactions.

final result: passed
