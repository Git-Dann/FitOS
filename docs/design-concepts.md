# Design concepts

Three distinct directions for the signed-in shell, scored and then combined. Written before any
shell code exists, as required by the brief. Linear is the interaction reference for density,
keyboard model and peek behaviour — not a visual template. No branding, colour, icon set, spacing
scale or layout is copied from it.

---

## Concept A — Gap Ledger

A compact operational issue list. The ledger is the application; everything else is reached from a
row.

### Desktop 1440 × 900

```text
┌────────────┬───────────────────────────────────────────────────────────────────────────┐
│ ◈ Northstar│  Inbox  ▾All open        ⌕ Search            ⟳ 4 sources · 2 stale    ◐ DK │
│  ⌂ Inbox 24│───────────────────────────────────────────────────────────────────────────│
│  ⚑ Gaps    │ ▾ Group: Severity   ⧉ List  ▤ Board  ◷ Timeline      Window: Last 7 days ▾ │
│  ⌕ Explore │───────────────────────────────────────────────────────────────────────────│
│  ∑ Metrics │ CRITICAL · 3                                                               │
│  ⇄ Sources │ ☐ ▲ STOCK TRUTH   Size 32 Charcoal not found on 7 checks   NS-014         │
│  ▤ Playbook│      £820–£2,400  ●●●○ med   2h old   ◔ Triaged      RS   1st: 12 May     │
│  ✓ Outcomes│ ☐ ▲ CAPACITY      Saturday service wait 2.4× baseline      NS-003         │
│            │      £1,100–£3,900 ●●○○ low   40m old  ◌ Detected     —    1st: 16 May     │
│  ── Views  │ ☐ ▲ DATA QUALITY  Footfall counter silent 31h             NS-007         │
│  ★ Mine    │      no exposure   ●●●● high  31h old  ◔ Triaged      AM   1st: 15 May     │
│  ★ Stale   │───────────────────────────────────────────────────────────────────────────│
│  ★ Unowned │ HIGH · 9                                                                   │
│            │ ☐ ● FUNNEL        App activation −18pp on 4.2.1          iOS              │
│  ⌂ Frontline│      £3,200–£9,800 ●●●○ med   6h old   ◑ Actioned    LK   1st: 09 May     │
│  ⌂ Manager │ ☐ ● MARGIN        Field Jacket returns 2.1× category      Stone           │
│  ⚙ Admin   │      £640–£1,900   ●●●○ med   1d old   ◌ Detected     —    1st: 14 May     │
└────────────┴───────────────────────────────────────────────────────────────────────────┘
     216px                                    fluid
```

`Space` on a row opens a right peek (480 px) without losing list position:

```text
                        ┌──────────────────────────────────────────┐
                        │ STOCK TRUTH · NS-014        ⤢ Open  ✕    │
                        │ Size 32 Charcoal not found on 7 checks   │
                        │──────────────────────────────────────────│
                        │ OBSERVED   7 failed checks of 9          │
                        │ EXPECTED   ≤1 of 9  (peer p50)           │
                        │ DELTA      +6  (+667%)   as of 14:00 BST │
                        │──────────────────────────────────────────│
                        │ ▨ MODELLED EXPOSURE                      │
                        │   £820 ──────●────── £2,400              │
                        │   base £1,450 · confidence medium 0.58   │
                        │   unmet × median margin × recovery 0.35  │
                        │   ⓘ 3 assumptions                        │
                        │──────────────────────────────────────────│
                        │ EVIDENCE  4 refs · 2 sources             │
                        │  ▸ inventory_snapshot  Shopify  12 rows  │
                        │  ▸ stock_check         POS CSV   9 rows  │
                        │  metric: stock_not_found_rate v2         │
                        │  detector: source_mismatch v3            │
                        │──────────────────────────────────────────│
                        │ [Assign ▾] [Status ▾] [Playbook ▾]       │
                        └──────────────────────────────────────────┘
```

### Tablet 1024 × 768

Navigation collapses to a 56 px icon rail. The list keeps type, title, exposure, confidence and
status; scope and owner move into the second line. Peek becomes a 60 %-width overlay sheet.

### Primary workflows

Triage the queue → peek → assign or dismiss → open detail when investigation is needed → record
outcome. Bulk-select with `X`, act on the selection from the command menu.

### Information hierarchy

Severity group → gap type → title → scope → exposure → confidence → freshness → status → owner.
Exposure never appears without its confidence adjacent.

### Keyboard model

`J`/`K` move · `Space` peek · `Enter` open · `X` select · `Shift+J/K` range-select · `A` assign ·
`S` status · `E` dismiss · `G` then `I/G/E/M/S` go to inbox/gaps/explore/metrics/sources ·
`Cmd/Ctrl+K` command menu · `/` search · `Esc` close.

### Advantages

The primary object is the primary experience; there is no translation step between what the product
believes and what the user sees. Density is high without being a report. Triage of 40 gaps is a
two-minute keyboard task. It scales to 10,000 rows through virtualisation with no redesign.

### Risks

Uniform rows flatten severity — a critical stock gap and a minor freshness gap look alike at a
glance unless grouping and colour carry real weight. It is weakest at "what is happening in my store
right now", which is the manager's actual first question. A list of issues is also the least
impressive thing to put on a screen in a first demo.

### Fit by role

frontline ○ · manager ●● · analyst ●●● · admin ●● · presenter ○

---

## Concept B — Operations Radar

Live signals arranged by location, channel and time. The shell is a pressure map; gaps are what you
click into.

### Desktop 1440 × 900

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Northstar Outfitters · Operations        Sat 16 May 14:12 BST   ⟳ 4 sources · 2 stale  │
│────────────────────────────────────────────────────────────────────────────────────────│
│ Stores ▾   Channels ▾   Window: Today ▾                          ⌕   ⌘K   ◐ DK        │
│────────────────────────────────────────────────────────────────────────────────────────│
│         10   11   12   13   14   15   16   17        OPEN GAPS BY EXPOSURE             │
│ NS-001  ░    ░    ▒    ▒    ▒    ░    ░    ░         ─────────────────────────         │
│ NS-003  ░    ▒    ▒    █    █    █    ▒    ░         FUNNEL  app 4.2.1                 │
│ NS-007  ▒    ▒    ▒    ▒    ▒    ▒    ▒    ▒  ⚠      £3.2k ──────── £9.8k  med         │
│ NS-014  ░    ░    ▒    █    █    ▒    ░    ░         CAPACITY  NS-003 Sat              │
│ NS-022  ░    ░    ░    ▒    ▒    ░    ░    ░         £1.1k ────── £3.9k    low         │
│ …7 more                                              STOCK  32/Charcoal               │
│  ░ normal  ▒ elevated  █ pressure  ⚠ no data         £0.8k ──── £2.4k     med         │
│────────────────────────────────────────────────────────────────────────────────────────│
│  WEB           APP            STORES          STOCK          STAFF                     │
│  conv 2.1%     activation     conv 18.4%      not-found      req/hr 6.2                │
│  ▁▂▃▃▂▁ −0.2pp 61% ▇▆▅▃▂ −18pp ▃▄▅▄▃ flat     4.1% ▂▃▅▇ ▲     ▃▄▆▇ ▲ 2 gaps            │
│  1 gap         2 gaps         —               3 gaps         1 gap                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Tablet 1024 × 768

The heat grid keeps 12 rows but drops to four-hour buckets. Channel strip becomes a horizontally
scrolling row of five cards. Gap list moves below the fold.

### Primary workflows

Scan for pressure → click a hot cell → filtered gap list for that store-hour → peek → act. Compare
two stores side by side. Watch a shift unfold.

### Information hierarchy

Time and place first, metric second, gap third. The opposite of Concept A.

### Keyboard model

Arrow keys move a cell cursor across the grid; `Enter` drills in; `Cmd/Ctrl+K` commands. Weaker than
A because a 2-D grid has no natural linear order, so bulk triage is essentially impossible here.

### Advantages

Answers "where is it hurting right now" instantly. Excellent for the manager view and outstanding in
a demo — the Saturday capacity scenario tells itself. Naturally surfaces data-quality holes as
visible gaps in the grid rather than as an absence of rows.

### Risks

Heat grids invite pattern-matching without evidence, which is the exact failure mode this product
exists to prevent. There is no obvious home for confidence or exposure ranges — a coloured cell has
no room for "±". Triage does not scale: at 10,000 gaps the radar is decoration. It also drifts
toward the "generic BI dashboard" the brief prohibits, and the pull is strong.

### Fit by role

frontline ●● · manager ●●● · analyst ○ · admin ○ · presenter ●●●

---

## Concept C — Evidence Workbench

A three-pane split joining gaps, metric definitions and source records in one surface. Built for the
person whose job is deciding whether a finding is real.

### Desktop 1440 × 900

```text
┌───────────────────┬──────────────────────────────┬─────────────────────────────────────┐
│ GAPS              │ STOCK TRUTH · NS-014         │ EVIDENCE                            │
│ ⌕ filter          │ Size 32 Charcoal             │ ▾ metric  stock_not_found_rate v2   │
│───────────────────│──────────────────────────────│   grain    date × location × variant│
│ ▸ STOCK   NS-014 ●│  observed 7/9   expected ≤1  │   owner    retail-pack              │
│ ▸ CAPACITY NS-003 │  ┌─ stock_not_found_rate ──┐ │   tests    3 passing · 0 failing    │
│ ▸ DATAQ   NS-007 ⚠│  │        ╭──╮             │ │   ⤢ definition   ⤢ lineage          │
│ ▸ FUNNEL  iOS     │  │ p50 ───┼──┼── baseline  │ │─────────────────────────────────────│
│ ▸ MARGIN  Stone   │  │ ───────╯  ╰────────     │ │ ▾ records   21 rows · 2 sources     │
│ ▸ CAMPAIGN NW     │  │ 09  11  13  15  17     │ │  inventory_snapshot   shopify        │
│                   │  └────────────────────────┘ │   14:00  units 4   conf —            │
│ ── related ──     │  ▨ MODELLED                  │   13:00  units 4   conf —            │
│ ▸ DATAQ   NS-014  │  £820 ──●── £2,400  med .58 │  stock_check          pos_csv         │
│   suppresses ↑    │  unmet × margin × recovery  │   14:02  found NO  staff RS          │
│                   │  ⓘ recovery 0.35 assumed    │   13:31  found NO  staff LK          │
│                   │──────────────────────────────│   ⤢ raw object  ⤢ mapping v4        │
│                   │ [Assign] [Status] [Playbook] │─────────────────────────────────────│
│ 24 open           │ detector source_mismatch v3  │ ▾ confidence  0.58 medium           │
│                   │ run 8f2c · window 7d · 210ms │   sample .9 complete .7 fresh .8    │
│                   │                              │   agreement .4 ◀ two sources differ │
└───────────────────┴──────────────────────────────┴─────────────────────────────────────┘
      280px                   fluid                            420px
```

### Tablet 1024 × 768

Three panes do not fit. Collapses to two, with evidence as a bottom sheet — which is a real
degradation, not a graceful one.

### Primary workflows

Open a gap → read the metric definition without leaving → inspect contributing records → check the
confidence breakdown → confirm or dismiss with a reason. Compare a gap with the data-quality gap
suppressing it.

### Information hierarchy

Claim, then the definition behind the claim, then the records behind the definition. Left-to-right
is literally the chain of provenance.

### Keyboard model

`Tab` cycles panes, `J`/`K` within a pane, `[`/`]` collapse panes, `Cmd/Ctrl+K` commands. Coherent
but requires learning; there is no fast path for triaging many gaps.

### Advantages

The single strongest answer to "how do I know this number is real", which is the product's whole
defensibility claim. Makes confidence components and metric versions visible by default rather than
behind a click. Structurally hard to confuse observed and modelled, because they sit in different
panes.

### Risks

Expensive to build and the least forgiving of small screens. Overkill for a manager with four
minutes. Three panes at 1440 px leaves each one cramped, and the middle pane carries the most
content. Highest implementation risk of the three by a clear margin.

### Fit by role

frontline ○ · manager ● · analyst ●●● · admin ●● · presenter ●

---

## Scoring

1 (weak) to 5 (strong). Weights reflect what this product must be good at: it is an operational
ledger first, and its defensibility is evidence.

| Criterion | Weight | A Ledger | B Radar | C Workbench |
| --- | --- | --- | --- | --- |
| Speed of triage | 3 | 5 | 2 | 2 |
| Clarity of the primary object | 3 | 5 | 2 | 4 |
| Data density | 2 | 5 | 4 | 4 |
| Frontline usability | 2 | 2 | 4 | 1 |
| Analyst depth | 3 | 3 | 1 | 5 |
| Demo value | 2 | 2 | 5 | 3 |
| Implementation risk (5 = lowest) | 3 | 4 | 3 | 2 |
| **Weighted total** | **18** | **70** | **46** | **59** |

Working: A = 15+15+10+4+9+4+12 = 70. B = 6+6+8+8+3+10+9 = 46. C = 6+12+8+2+15+6+6 = 59.

## Decision

**Concept A is the spine. Concept C is the gap detail. Concept B is a bounded manager view.**

Not a compromise — each concept wins a different question, and the questions belong to different
routes:

- **A becomes the shell and `/inbox`.** It scores highest, and it is the only one of the three that
  survives 10,000 gaps. Its peek panel is a compressed Concept C, which is what makes the
  combination coherent rather than three products stapled together.
- **C becomes `/gaps/[gapId]` and `/explore`.** Its cost is acceptable on two routes and unacceptable
  as a shell. The three-pane layout is a detail-view layout; forcing it into the tablet breakpoint
  is only a problem if it is also the home screen, and it is not.
- **B becomes a section of `/manager` and the opening beat of the presenter flow.** It earns its
  place by answering "where is pressure now", and it is contained: it is one component on one route,
  not a navigation model. Every cell links to filtered gaps, so it can never become a dashboard that
  terminates in a chart.

Concept A was written first and did win. That is a scoring outcome, not an ordering one: B loses on
triage and analyst depth, C loses on implementation risk and frontline usability, and the ranking is
unchanged if implementation risk is dropped from the table entirely (A 58, B 37, C 53).

### What this decision commits us to

1. A row component dense enough to carry nine attributes at ~32 px, with tabular numerals.
2. A peek panel that is genuinely the same component as the detail middle pane at a narrower width —
   built once, in `packages/ui`.
3. A heat-grid component with an accessible table equivalent and per-cell gap links, used on exactly
   one route.
4. A keyboard model owned centrally, not per route, so `J`/`K` mean the same thing everywhere.

### Rejected outright

A chat-first home screen, a metric-card landing page, and any shell whose default view is a chart.
All three were considered and none answers "what should I do next", which is the only question the
signed-in home is allowed to answer.
