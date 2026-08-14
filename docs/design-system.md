# Design system

Tokens, primitives and product components live in `packages/ui`. FitOS owns the visual language;
Radix supplies behaviour only. A default shadcn surface is not an acceptable end state.

## 1. Token architecture

Three tiers. Components consume tier 3 only — a component that references a tier-1 value directly is
a lint failure, because that is how themes rot.

```text
1. primitive   --neutral-50 … --neutral-950, --accent-50 … --accent-950, --red/amber/green/blue-*
2. semantic    --bg-canvas, --bg-surface, --bg-raised, --fg-default, --fg-muted, --fg-subtle,
               --border-default, --border-strong, --accent-fg, --status-{critical,high,medium,low,info}
3. component   --row-height, --peek-width, --nav-width, --focus-ring, --chart-grid, --chart-mark-*
```

Light and dark are two definitions of tier 2 over the same tier 1. Both are built and tested; dark
is not an afterthought applied with a filter.

## 2. Colour

A restrained neutral system, one product accent, and semantic status colours. The legacy prototype's
deep-green and off-white palette is the starting point for the accent and canvas — it already
satisfies the brief's restraint rules and carries FitOS brand recognition — but it is re-expressed as
a full 50–950 ramp with measured contrast rather than the loose hex literals used today.

Rules:

- Status is never carried by colour alone. Every status has an icon or a text label, for
  colour-vision deficiency and for greyscale printing.
- Contrast: 4.5:1 for body text, 3:1 for large text and UI boundaries, in both themes. Checked in CI.
- Modelled data uses a distinct, non-decorative treatment — a hatched fill and a `▨` marker — not a
  different hue, because hue alone is exactly the confusion the brief prohibits.
- Chart marks come from a dedicated ordered ramp, tested for both themes and for deuteranopia.

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
`--border-strong` for focus and selection. Two shadow tokens only: `--shadow-peek` and
`--shadow-menu`. Elevation is otherwise conveyed by background, not by shadow.

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
- Contrast checks on both themes — CI failure.

The rest is caught by screenshot review at 1440 × 900, 1024 × 768 and 390 × 844 per route, compared
against this document by the design-reviewer subagent before a route is marked complete.
