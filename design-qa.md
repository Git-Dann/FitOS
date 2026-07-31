# Manager decision view design QA

**Comparison target**

- Source visual truth: `/var/folders/qm/nlhwbcsj113_khmg044bkzdh0000gn/T/codex-clipboard-10122c44-870a-4695-b8f6-f3641ca7e009.png`
- Implementation capture: `design-qa-manager-implementation.png`
- Full-view comparison: `design-qa-manager-comparison.png`
- State: Manager view, Busy Saturday, Today.
- Viewport: 1280 px wide browser capture. The source was 2676 × 2122 px and normalized to 1280 × 1015 px for comparison; the rendered full-page implementation is 1280 × 1812 px. The source is a high-density capture; the implementation is captured at 1×.
- Focused region: the priority action, two operating signals and action rows are all legible in the full-view comparison; no additional crop was needed.

**Findings**

- [Resolved P1] The source presented a dense reporting wall: four repeated sections, many low-priority metrics and no obvious first decision.
  - Fix: replaced it with one priority action, queue-pressure and delivery-health cards, and three concise follow-up signals.
  - Post-fix evidence: the implementation makes the restock decision, peak hours and demand signal readable before any supporting evidence.

- [Resolved P2] Drill-down actions were visually repeated without explaining why one mattered more than another.
  - Fix: surfaced the recommended stock action in the priority panel, then ranked the remaining three signals in a compact action list.

- No remaining P0, P1 or P2 visual issues. The new page intentionally has more whitespace and fewer metrics than the source because the requested outcome is a usable decision surface, not a report dashboard.

**Required fidelity surfaces**

- **Fonts and typography:** uses the same product sans-serif hierarchy, with one concise display headline and reduced small-text density.
- **Spacing and layout rhythm:** clear page margins, a stable two-card grid and compact action rows remove the long, repetitive vertical rhythm from the source.
- **Colors and visual tokens:** retains the existing off-white, deep green, mint, amber and semantic status palette; primary action has strong contrast.
- **Image quality and asset fidelity:** no image assets are required by the manager dashboard. Data charts are semantic UI visualizations with accessible labels, not placeholder imagery.
- **Copy and content:** every line either states the decision, the evidence, or a concrete next action. Modelled demand remains explicitly caveated.

**Interaction and runtime checks**

- Published route opened successfully: `https://fitos-retail-operations.vercel.app/demo/manager`
- Tested `View the evidence` → evidence drawer for Size 32 / Charcoal demand.
- Period filters and each compact action row remain interactive.
- Browser console errors and warnings: none.

**Implementation checklist**

- [x] Remove repeated metric/report sections.
- [x] Make the recommended action the dominant first decision.
- [x] Keep only the operating signals that contextualize the decision.
- [x] Preserve caveats for modelled value and test the evidence drawer.

**Follow-up polish**

- [P3] Add retailer-defined demand thresholds when real pilot data is available.

final result: passed
