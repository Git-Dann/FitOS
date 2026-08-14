# Design system

Tokens, primitives and product components live in `packages/ui`. FitOS owns the visual language;
Radix supplies behaviour only. A default shadcn surface is not an acceptable end state.

## 1. Token architecture

Three tiers. Components consume tier 3 only — a component that references a tier-1 value directly is
a lint failure, because that is how themes rot.

```text
1. primitive   --neutral-50 … --neutral-950, --accent-50 … --accent-950,
               --status-{critical,high,medium,low}-{400,700}
2. semantic    --bg-canvas, --bg-surface, --bg-raised, --fg-default, --fg-muted, --fg-subtle,
               --border-default, --border-strong, --accent-fg, --accent-fill, --on-accent,
               --focus-ring, --status-{critical,high,medium,low}
3. component   --row-height, --peek-width, --nav-width, --chart-grid, --chart-mark-*
```

**Dark is the default theme.** Light is a full peer, built and tested, not an afterthought applied
with a filter — but the product is designed dark-first and the dark values are the ones tuned by
eye. Both are two definitions of tier 2 over the same tier 1.

## 2. Colour

A near-black neutral ground with a single orange accent. Values live in
[`docs/design-tokens/tokens.json`](design-tokens/tokens.json) and are verified by
`node docs/design-tokens/check-contrast.mjs`, which exits non-zero on any failing pair. That script
is the source of truth for the ratios quoted below; it moves into `packages/ui` and becomes a CI
gate in Phase E.

This replaces the legacy prototype's off-white and deep-green palette, which stays in `legacy/`.

### Primitive ramps

```text
neutral   50 #F7F8F9   100 #EDEEF1   200 #DCDEE3   300 #C0C3CB   400 #9497A1   500 #7A7E88
         600 #616570   700 #494D55   800 #2E3138   900 #1A1C21   950 #0B0C0E

accent    50 #FFF4ED   100 #FFE6D5   200 #FFC9AA   300 #FFA474   400 #FF7A3C   500 #F75F14
         600 #E8490A   700 #C0350B   800 #983010   900 #7A2B11   950 #421105
```

The neutral ramp is very slightly cool, so the near-black ground reads as considered rather than as
an absence of colour. `#000000` is never used as a background.

### Semantic mapping

| Token | Dark (default) | Light |
| --- | --- | --- |
| `bg-canvas` | `#0B0C0E` | `neutral-50` |
| `bg-surface` | `#131417` | `#FFFFFF` |
| `bg-raised` | `#24262C` | `#FFFFFF` |
| `fg-default` | `neutral-100` | `neutral-900` |
| `fg-muted` | `neutral-400` | `neutral-600` |
| `fg-subtle` | `neutral-500` | `neutral-500` |
| `border-default` | `neutral-800` | `neutral-200` |
| `border-strong` | `neutral-600` | `neutral-500` |
| `accent-fg` (accent text) | `accent-400` | `accent-700` |
| `accent-fill` (primary button) | `accent-500` | `accent-500` |
| `on-accent` (label on fill) | `neutral-950` | `neutral-950` |
| `focus-ring` | `accent-400` | `accent-600` |

Two consequences worth stating because they are easy to get wrong later:

- **The label on an orange fill is near-black, in both themes.** White on orange measures 3.90:1 and
  fails AA; near-black on `accent-500` measures 6.15:1. There is no theme in which a white-on-orange
  button is acceptable here.
- **Elevation reverses between themes.** Dark conveys it by background luminance, because shadows
  are invisible on a near-black ground. Light inverts it — panels are white on a tinted ground — and
  raised surfaces separate by border and shadow rather than by luminance. The contrast checker
  applies the luminance requirement to dark only, deliberately.

### Accent discipline

Orange is reserved for **interaction**: primary actions, links, focus, selection, the active
navigation item, and the current position in a list. It is never used to mean "warning", "urgent" or
"bad".

This matters because `accent-400` and `status-high-400` sit at 1.65:1 relative luminance and are
both warm — close enough that colour alone cannot separate them. The resolution is role separation,
not hue tuning: they never appear in the same role, severity always carries an icon and a text
label, and severity chips use a small coloured dot with neutral text rather than coloured text.

### Status

| Severity | Dark | Light |
| --- | --- | --- |
| critical | `#FF6166` | `#AA2429` |
| high | `#F2CB3D` | `#856400` |
| medium | `#5EB1EF` | `#1060A3` |
| low | `#4CC38A` | `#1B6B48` |

### Rules

- Status is never carried by colour alone. Every status has an icon or a text label, for
  colour-vision deficiency and for greyscale printing.
- Contrast: 4.5:1 for body text, 3:1 for large text and non-text UI indicators, in both themes.
  Verified by the checker, gated in CI.
- Modelled data uses a distinct, non-decorative treatment — a hatched fill and a `▨` marker — not a
  different hue, because hue alone is exactly the confusion the brief prohibits.
- Chart marks come from a dedicated ordered ramp, tested for both themes and for deuteranopia. The
  accent is not a chart colour; a series must never be mistakable for an interactive element.
- Never introduce a colour outside these ramps. A one-off hex in a component is a lint error.

### On the Linear reference

The brief takes Linear as an *interaction* reference and explicitly forbids copying its branding or
colours. This palette is consistent with that: it borrows the character — near-black ground, high
density, hairline borders, restrained chrome, a single saturated accent doing all the interactive
work — while the accent itself (orange) is deliberately not Linear's blue-violet.

Prohibited by construction, with lint rules where mechanisable: purple-blue gradients, glass panels,
glowing borders, giant metric cards, decorative sparkles, random gradient blobs.

## 3. Typography

One sans family with tabular figures for the product; the marketing surfaces may keep a display
scale, the signed-in product may not.

| Token | Size / line | Use |
| --- | --- | --- |
| `text-2xs` | 10 / 14 | Dense metadata in rows |
| `text-xs` | 11 / 16 | Secondary row line, labels |
| `text-sm` | 13 / 18 | Body default in product |
| `text-base` | 15 / 22 | Detail prose |
| `text-lg` | 18 / 24 | Panel titles |
| `text-xl` | 22 / 28 | Route titles |
| `text-2xl` | 28 / 34 | Largest permitted in signed-in product |

`font-variant-numeric: tabular-nums` on every numeric cell, so columns align and a changing value
does not reflow its row. No `clamp()` display headlines inside the product — the legacy
`clamp(45px, 5.8vw, 74px)` treatment stays in `legacy/` and on marketing routes.

## 4. Spacing, radius, borders, shadow

4 px base scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64. Radii 6–10 px only; `999px` reserved for
avatars and count badges, not for every control. Borders are 1 px hairlines at `--border-default`;
`--border-strong` for selection. Two shadow tokens only: `--shadow-peek` and `--shadow-menu`.

Elevation is theme-dependent, as set out in §2: dark uses background luminance and treats shadow as
decoration; light uses border and shadow, because a white panel on a tinted ground has nowhere to go
luminance-wise. Do not implement one mechanism and let the other theme inherit it.

Whitespace is used to group, not to fill. A route that shows three numbers in a viewport is a
failure of density, which is the main design defect carried over from the prototype.

## 5. Density

| Token | Value | Applies to |
| --- | --- | --- |
| `--row-height-compact` | 32 px | Gap inbox default |
| `--row-height-comfortable` | 44 px | User preference, persisted per user |
| `--row-height-touch` | 48 px | Frontline surfaces, always |

Frontline is touch-first: 48 px minimum targets, 44 px minimum spacing between destructive and
non-destructive controls.

## 6. Motion

Motion for React, used only where movement explains state or preserves spatial context. Durations
120–220 ms; peek open/close 180 ms; row selection 120 ms; nothing above 240 ms.

`prefers-reduced-motion: reduce` replaces transform animations with opacity changes and disables
layout animation entirely. This is a token-level switch, not a per-component conditional.

No fake live activity. Nothing pulses, shimmers or animates to imply data is arriving when it is not.

## 7. Component inventory

**Primitives (Radix behaviour + FitOS visuals):** Button, IconButton, Input, Select, Combobox,
Checkbox, Radio, Switch, Tooltip, Popover, Dialog, Sheet, DropdownMenu, ContextMenu, Tabs, Toast,
Toggle, Separator, ScrollArea, VisuallyHidden.

**Product components:** AppShell, NavRail, TopBar, CommandMenu, SavedViewPicker, GapRow, GapList
(virtualised), PeekPanel, DetailPanes, ExposureRange, ConfidenceMeter, ConfidenceBreakdown,
EvidenceList, EvidenceRef, LineageTrail, MetricDefinitionCard, SourceHealthChip, FreshnessChip,
StatusChip, SeverityChip, OwnerAvatar, BulkActionBar, FilterBar, TimeWindowPicker, QuarantineTable,
MappingEditor, DetectorConfigPreview, HeatGrid, PresenterFrame, DemoDataBanner.

**Charts (`packages/charts`, Visx + D3 scales):** TimeSeries, SmallMultiples, FunnelSteps,
DistributionBand, PeerComparison, HeatGrid, Sparkline.

Every chart ships with: a scale, an axis, a source attribution, an as-of time, an accessible text
summary, and a data table or export path. A chart without all six does not merge — this is the
single most-violated rule in the legacy prototype, where CSS `div` bars carry no scale or source at
all.

## 8. State coverage

Every product component ships with all of: default, hover, focus-visible, active, selected,
disabled, loading, empty, partial, stale, error, unauthorised. Storybook stories exist for each, and
the Playwright visual suite captures them.

- **Loading** skeletons match the final layout exactly. A skeleton that reflows on load is a bug.
- **Stale** is distinct from loading: the data is real but older than its expected cadence, shown
  with the age, never hidden.
- **Partial** means some sources answered and some did not, and it names which — a partial result
  silently rendered as complete is a correctness failure, not a UX one.
- **Empty** distinguishes "no gaps" (good) from "no data" (bad). They must never look the same.

## 9. Accessibility baseline

WCAG 2.2 AA. Full keyboard operation, visible focus on every interactive element, screen-reader
names and structure, table and chart summaries, non-colour status cues, reduced motion, zoom and
reflow to 320 px equivalent, mobile touch targets, errors programmatically associated with inputs,
and live regions for background progress. Detail in [docs/accessibility.md](accessibility.md),
created in Phase E.

## 10. Enforcement

Design rules that can be mechanised are:

- `<style>` elements over 200 characters — build failure.
- Numeric literals formatted as currency or percentage in `apps/web` outside fixtures — build failure.
- Tier-1 token references inside components — lint error.
- Missing `aria-label` on icon-only controls — lint error.
- axe violations on any story or route — CI failure.
- `node docs/design-tokens/check-contrast.mjs` (both themes) — CI failure on any pair below its
  minimum. Runs today; moves into `packages/ui` in Phase E.
- A colour literal outside the token ramps — lint error.

The rest is caught by screenshot review at 1440 × 900, 1024 × 768 and 390 × 844 per route, compared
against this document by the design-reviewer subagent before a route is marked complete.
