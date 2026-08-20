# Design system

Tokens, primitives and product components live in `packages/ui`. FitOS owns the visual language;
Radix supplies behaviour only. A default shadcn surface is not an acceptable end state.

## 0. Source

The visual language is **Linear's iOS design system**, taken from
`design-md/productivity/linear/DESIGN.md` in
[Meliwat/awesome-ios-design-md](https://github.com/Meliwat/awesome-ios-design-md) and copied
exactly. Colour values, the type ramp, the spacing and radius scales, the elevation model, the
motion durations, the row geometry and the component specs below are that document's, quoted where
it is easier to quote than to paraphrase.

This is a reversal. Earlier revisions of this file took Linear as an *interaction* reference and
said the brief "explicitly forbids copying its branding or colours", with an orange accent chosen
specifically so as not to be Linear's blue-violet. That is no longer the instruction and the file
should not read as though it were.

Every place the implementation departs from the source is listed in §10 with its reason, and the
machine-checkable ones are recorded in `$deviations` in
[`tokens.json`](design-tokens/tokens.json). Two constraints outrank the source spec and are the
origin of most of those departures:

- **WCAG 2.2 AA** (§9) is a commitment the source document does not make. It is not dropped to
  match a value.
- **The gap model.** `gap-model.md` §3 requires exposure to appear as a range with its confidence
  band adjacent, on every surface. An issue tracker has nothing equivalent, so the row's trailing
  zone carries two values Linear's does not.

## 1. Token architecture

Three tiers. Components consume tier 3 only — a component that references a tier-1 value directly is
a lint failure, because that is how themes rot.

```text
1. primitive   --ink-{canvas,surface1..3,divider,text1..3,white}
               --paper-{canvas,surface1..3,divider,text1..3}
               --purple-{base,pressed,wash-dark,wash-light}
               --status-{amber,red,green}[-on-light][-glyph-on-light]
2. semantic    --bg-{canvas,surface,raised,pressed}, --fg-{default,muted,subtle},
               --border-{default,strong}, --accent-{fill,pressed,glyph,wash}, --on-accent,
               --focus-ring, --status-{urgent,progress,done,neutral,canceled},
               --success, --warning, --error
3. component   --row-height-{compact,comfortable}, --text-*, --track-*, --space-*, --radius-*,
               --motion-*, --nav-width, --peek-width, --command-width, --topbar-height
```

**Dark is the default theme.** The source system is dark-first and calls light a limited variant;
light is still built, reachable from the top bar, persisted, and captured at every viewport by
`apps/web/scripts/capture.mjs`, because a theme nobody can switch to is a theme nobody has looked
at. Both are two definitions of tier 2 over the same tier 1.

## 2. Colour

A near-OLED black ground with a single purple accent. Values live in
[`docs/design-tokens/tokens.json`](design-tokens/tokens.json) and are verified by
`node docs/design-tokens/check-contrast.mjs`, which exits non-zero on any failing pair. That script
is the source of truth for the ratios quoted below.

### Primitive values

```text
ink      canvas #08090A   surface1 #141516   surface2 #1C1D1F   surface3 #232428
         divider #23252A  text1 #F7F8F8      text2 #8A8F98      text3 #5C5F6A

paper    canvas #FFFFFF   surface1 #F4F5F8   surface3 #EDEFF4   divider #E1E4EA
         text1 #08090A    text2 #6B6F76      text3 #8A8F98

purple   base #5E6AD2     pressed #4F58B8    wash-dark #141726  wash-light #E8EAF9

status   amber #F2C94C    red #EB5757        green #4CB782
```

The canvas is `#08090A`, and the source spec is emphatic that this is not negotiable: *"Don't use
`#121212` — Linear is darker; the near-OLED black is part of the identity."* A test asserts the
value and asserts `#121212` appears nowhere.

### Accent discipline

Purple is the only accent. It marks the primary action, the focused command-menu row, the active
list selection and the active sidebar item, and nothing else. *"When something turns purple, it is
**the** thing you should act on."*

**The accent is never a text colour.** `#5E6AD2` measures 4.24:1 on the canvas and 3.59:1 on a
raised row — under the 4.5:1 body-text floor, over the 3:1 floor for a glyph, a ring or a focus
indicator. That is the only way the source spec ever uses it (*"Active item: label `#F7F8F8`, 16pt
icon `#5E6AD2`"*), so the token is named `--accent-glyph` to make a text use look wrong at the call
site, and a test fails if any `--fg-*` token resolves to it. Labels on a purple ground are
`#FFFFFF`, which measures 4.70:1 and passes — unlike the previous orange accent, where white
measured 3.90:1 and the label had to be near-black.

### Status

Status is a **drawn glyph language**, not a set of coloured badges. From the source spec, twice:
*"Use the iconographic status system (drawn glyphs) instead of colored fills or text badges"* and
*"Don't use colored status badges with text — the drawn icon system **is** the language."*

| Role | Glyph | Colour |
| --- | --- | --- |
| `detected` | dashed ring | `--status-neutral` |
| `triaged` | thin ring | `--status-neutral` |
| `investigating` | half-filled pie | `--status-progress` |
| `actioned` | three-quarter pie | `--status-progress` |
| `validating` | near-full ring | `--status-done` |
| `resolved` | filled disc with a knocked-out check | `--status-done` |
| `dismissed` | filled disc with a knocked-out cross | `--status-canceled` |

Severity uses the source spec's **priority bars**: *"Urgent renders as a filled amber/red square
with `!`; High = 3 filled, Medium = 2, Low = 1, None = 3 dimmed."* Only critical takes a colour;
high, medium and low are all `--status-neutral` and differ by how many bars are filled. That is
what makes severity survive greyscale without a coloured chip, and it is why the severity rail and
the severity chip that preceded it are both gone — accent and severity must not compete for the same
three pixels of a row's left edge.

### Rules

- No second accent. A test enumerates every accent-role token in both themes and fails if one
  resolves outside the purple family.
- `#000000` is never a background; `#08090A` is.
- The label-pill dot colour is workspace data, never UI chrome.
- Light darkens the status ramp rather than inheriting it. Amber, red and green at their dark values
  measure 1.46:1, 3.19:1 and 2.29:1 on the light surface — unreadable, and invisible in a dark-mode
  screenshot. A test fails if a light status token equals its dark counterpart.

## 3. Typography

**Inter** at 400 / 500 / 600 and nothing else — *"no light, no bold/black"* — with
`font-feature-settings: "cv11", "ss03"` and tabular numerals wherever a count or an identifier
appears. Monospace carries identity, never content: gap references and keyboard shortcuts.

| Token | Size / line | Tracking | Use |
| --- | --- | --- | --- |
| `text-2xs` | 11 / 1.2 | +0.4 | Uppercase group and section labels, 600 |
| `text-xs` | 12 / 1.3 | 0 | Meta, counts, label pills, command shortcuts |
| `text-sm` | 13 / 1.35 | 0 | Metadata, mono gap references |
| `text-md` | 14 / 1.3 | −0.1 | Command rows, sidebar items, buttons |
| `text-base` | 15 / 1.35 | −0.1 | Row title at 500; body at 400 with 1.5 line height |
| `text-lg` | 17 / 1.3 | −0.2 | Section headers, group headers, top-bar title |
| `text-xl` | 22 / 1.25 | −0.3 | View titles, the detail-route title |
| `text-2xl` | 28 / 1.2 | −0.4 | The largest step there is |

There is **no display step**, because the product has no marketing surface: *"the issue title is the
headline"*. Negative tracking is on titles only, easing to 0 at body. Nothing renders below 11px —
the previous ramp bottomed out at 10px and put 30 of its 42 font-size declarations at 10 or 11.

## 4. Spacing, radius, borders, elevation

4px base. Scale: **4, 6, 8, 12, 16, 20, 24, 32, 40, 56**. Standard margin 16px horizontal on lists.
Rows touch — *"separation is via hover state and group headers, not gaps"*.

Radius, exactly five steps: **0** dividers and full-bleed rows · **6px** label pills, icon-button
hover, dropdown menus · **8px** buttons, inputs, status pills · **12px** the command sheet and
modals · **50%** avatars only.

Elevation is *"a one-step background lift and a precise 1pt border, not blur"*:

| Level | Treatment |
| --- | --- |
| Flat | Rows, list canvas, group headers — no shadow |
| Hover | Background shift to `--bg-raised`, no shadow |
| Popover | `--shadow-menu` + 1px `--border-default` |
| Command sheet | `--shadow-peek` + 1px `--border-default` |
| Scrim | `--scrim` behind the command menu and modals |

Two shadows, both large, dark and soft, and only on floating surfaces. *"Shadows cost compositing
time and Linear optimizes for instant."*

The contrast gate checks elevation as lift **and** border, in both themes, rather than as a
luminance threshold alone: on a near-OLED canvas the lift the source palette achieves is 1.18:1, and
the hairline is what finishes the job. This is a wider check than the dark-only luminance test it
replaced.

## 5. Density

| Token | Value | Applies to |
| --- | --- | --- |
| `--row-height-compact` | 44px | The gap inbox default |
| `--row-height-comfortable` | 52px | Persisted user preference; adds the recommended-action line |

Both are the source spec's own row heights. Compact is the default because *"density is the value
proposition"* and *"Don't pad issue rows for 'breathing room' — that destroys the density that makes
Linear fast."* The preference is stored in `localStorage`, read through `useSyncExternalStore`, and
reachable from the toolbar and the command menu.

Frontline is touch-first: 48px minimum targets below 720px, asserted by the capture script, which
fails the run if any nav item, view tab or severity pill measures under 44px there.

## 6. Motion

Durations **90–240ms**, and nothing above it: *"anything over ~250ms feels broken"*.

| Token | Duration | Use |
| --- | --- | --- |
| `--motion-row` | 90ms | Row selection — a colour cross-fade, no movement |
| `--motion-command` | 120ms | Command menu, opacity 0→1 with scale 0.96→1 |
| `--motion-morph` | 150ms | Status glyph state change |
| `--motion-sidebar` | 220ms | Sidebar slide-over |
| `--motion-panel` | 240ms | Detail panel push |

`prefers-reduced-motion: reduce` replaces transform animation with opacity alone and disables layout
animation, as a token-level switch rather than a per-component conditional.

No fake live activity. Nothing pulses, shimmers or animates to imply data is arriving when it is
not.

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

The rest is caught by screenshot review at 1440 × 900, 1024 × 768 and 390 × 844 per route **in both
themes**, compared against this document by the design-reviewer subagent before a route is marked
complete. `apps/web/scripts/capture.mjs` produces that set and asserts what does not need an eye: no
console errors, no horizontal overflow at 390 or 320, no touch target under 44px on the frontline
mobile surface, the compact row at 44px and the comfortable row at 52px, exactly one focused command
row, and no currency figure surviving into a frontline payload. It writes nothing if any of those
fail.

### Deviations from the source spec

Ten, each with a reason. Nothing here is a preference.

| Deviation | Why |
| --- | --- |
| Light gets a darkened status ramp | The source ships four light values and no light status ramp. Amber, red and green measure 1.46:1, 3.19:1 and 2.29:1 on the light surface — below AA for text. Each hue is scaled toward black by the smallest factor that clears 4.5:1. |
| Light divider and pressed step derived | Not in the source spec. Derived to sit between the light canvas and surface, keeping the hairline mechanism the dark theme uses. |
| `bg-surface` and `bg-raised` are the same value in light | The source light mode has one surface. Selection is carried by the purple wash it does define, and a test asserts the wash differs from both the canvas and the hover ground in both themes. |
| The selection wash is stored flattened, not as `rgba()` | `rgba(94,106,210,0.14)` over a known ground is a known colour, and a known colour is checkable by the contrast gate. |
| The row's trailing zone carries exposure and confidence | `gap-model.md` §3 requires them adjacent on every surface. An issue row has no equivalent, and this is the slot the source layout leaves for right-aligned numerics. |
| The recommended action appears at comfortable density only | It is the row's answer to "so what", and putting it on every row made a three-line row and cost the density the source calls the value proposition. |
| A situation strip above the list | The source list opens straight onto rows. A gap ledger's first question is "how bad is today", which a list cannot answer — the reason this exists is a user rejecting the bare list outright. It is styled as a caption band at the 17px step, not the 28px one, with no fills, cards or shadow. |
| Light keeps its own shadow opacity | The source shadows are tuned for a near-black canvas; the same alpha on white reads as dirt. Geometry is unchanged, opacity is reduced. |
| JetBrains Mono stands in for Berkeley Mono | Berkeley Mono is a paid licence. SF Mono still wins on Apple hardware through the fallback stack the source specifies. |
| No bottom tab bar, no haptics, no iPad two-pane | This is a web app. The source is an iOS spec; its slide-over sidebar, keyboard model and command menu carry over, its device-specific affordances do not. |
