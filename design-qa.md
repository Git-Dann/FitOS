# Customer journey design QA

**Comparison target**

- Source visual truth: `/var/folders/qm/nlhwbcsj113_khmg044bkzdh0000gn/T/codex-clipboard-71a35d09-e80b-44fe-af6c-39ac7253316b.png`
- Implementation capture: `design-qa-implementation.png`
- Full-view comparison: `design-qa-comparison.png`
- State: Customer journey, **Scan a garment label** (step 2 of 9); Busy Saturday scenario.
- Viewport: 1280 px wide browser capture. The source was 2720 × 2100 px and normalized to 1280 × 988 px for comparison; the rendered full-page implementation is 1280 × 1119 px. The source is a high-density capture; the implementation is captured at 1×.
- Focused region: the phone scan label, barcode, recognition action and manual-entry control. A focused crop was not needed because these controls are legible in the full-view comparison.

**Findings**

- [Resolved P1] Scan controls ran behind the fixed phone footer in the first rendered pass.
  - Evidence: the first post-build capture showed the manual-entry row partially obscured by the footer.
  - Fix: reduced the scan-label panel, barcode and form spacing in `.customer-reframed` while preserving the fixed device height.
  - Post-fix evidence: `design-qa-implementation.png` shows the barcode, recognition action, product-code input and “Use code” control all fully visible above the footer.

- No remaining P0, P1 or P2 differences. The redesigned composition intentionally replaces the source’s oversized editorial headline with a shorter outcome-led message, visible three-part explanation and fixed-height interaction frame.

**Required fidelity surfaces**

- **Fonts and typography:** retained the product’s sans-serif display/body system, with a smaller, scannable supporting hierarchy in the phone.
- **Spacing and layout rhythm:** the new two-column frame keeps consistent side margins, gives the phone a stable height, and prevents action controls from moving or clipping between steps.
- **Colors and tokens:** preserved the existing warm off-white, deep green, mint status and muted-gray system; the primary action remains high contrast.
- **Image quality and asset fidelity:** the previous hand-built vertical barcode has been replaced by a browser-rendered, machine-generated Code 128 barcode via `jsbarcode`. No placeholder imagery, CSS barcode art or handcrafted SVG is used in the scan label.
- **Copy and content:** copy now explains the value exchange—recognise an existing label, recommend available options and give the team a room-aware request—before the user starts.

**Interaction and runtime checks**

- Published route opened successfully: `https://fitos-retail-operations.vercel.app/demo/customer`
- Tested `Start with a garment` → Scan state; barcode has the accessible name `Barcode 5061048301128`.
- Tested `Recognise demonstration label` → Room-selection state (step 3 of 9).
- Browser console errors and warnings: none.

**Implementation checklist**

- [x] Replace fake barcode with a real Code 128 barcode.
- [x] Reframe the customer page around a stable, understandable walkthrough.
- [x] Keep the scan action and manual code entry inside the phone frame.
- [x] Verify the published interaction path and browser console.

**Follow-up polish**

- [P3] Consider adding real product photography to the later recommendation cards as the product catalogue expands.

final result: passed
