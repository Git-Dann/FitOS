# FitOS Gap Intelligence

> FitOS turns fragmented operational data into a governed ledger of gaps,
> evidence and actions.

The primary object is a **Gap**: an observed value, what it was compared
against, how large the difference is, what business exposure it may represent
as a range, how reliable that estimate is, and which records and metric
definitions support it. The primary experience is a **Gap Ledger** that behaves
like an operational issue system, not a BI dashboard.

Start with [docs/product-spec.md](docs/product-spec.md) for what it is, and
[docs/architecture.md](docs/architecture.md) for how it is built.

## Current state — Phase A

The monorepo, local infrastructure and CI exist. **No product code yet.** The
phase plan and per-phase acceptance criteria are in
[docs/implementation-plan.md](docs/implementation-plan.md); live status is in
[docs/build-state.md](docs/build-state.md).

The original browser prototype is preserved and still runnable under
[`legacy/fitos-prototype/`](legacy/fitos-prototype/). It is not part of the
pnpm workspace — see
[ADR 0008](docs/adr/0008-hosting-target-and-legacy-runtime.md).

## Prerequisites

| Tool   | Version         | Why                          |
| ------ | --------------- | ---------------------------- |
| Node   | ≥ 22.13         | web app and tooling          |
| pnpm   | 10.33           | workspace package manager    |
| uv     | ≥ 0.8           | Python dependency management |
| Docker | with Compose v2 | local infrastructure         |

## Quick start

```bash
pnpm install          # JS workspace
uv sync --all-packages # Python services
pnpm dev:infra        # postgres, clickhouse, minio, temporal, cube — waits for health
pnpm dev              # web on :3000, api on :8000
```

Check it came up:

```bash
curl localhost:3000/health   # {"status":"ok","service":"web",...}
curl localhost:8000/health   # {"status":"ok","service":"api",...}
curl localhost:8000/ready    # per-dependency readiness; 503 when degraded
```

`pnpm dev:infra:down` stops infrastructure and **preserves data volumes**.

## Commands

| Command                           | Does                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------- |
| `pnpm verify`                     | The gate before claiming a phase complete: format, lint, typecheck, unit tests, token contrast |
| `pnpm build`                      | Production build of every workspace package                                                    |
| `pnpm lint` / `lint:py`           | ESLint / ruff                                                                                  |
| `pnpm typecheck` / `typecheck:py` | tsc / mypy                                                                                     |
| `pnpm test:unit` / `test:unit:py` | Unit tests                                                                                     |
| `pnpm test:tokens`                | Colour tokens against WCAG 2.2 AA in both themes                                               |
| `pnpm dev:infra footprint`        | Container memory and CPU, via `infra/scripts/dev-infra.sh`                                     |

Commands that exit non-zero with a "added in Phase X" message are declared but
not yet implemented. That is deliberate: a command that silently succeeds
without doing anything is worse than one that admits it does not exist.

`test:e2e`, `test:visual` (Phase E), `test:data` (Phase D) and `demo:*`
(Phase F) are in that category today.

## Layout

```text
apps/web            Next.js product application
services/api        FastAPI control and product API
services/worker     Temporal workers — ingestion, mapping, detectors
services/semantic   Cube Core configuration
packages/config     shared TypeScript settings
packages/contracts  types shared between web and API
packages/ui         design tokens and, from Phase E, product components
infra/compose       local Docker Compose environment
infra/scripts       lifecycle scripts
docs                specification set, ADRs, design tokens
legacy              preserved prototype
```

## Design

Dark is the default theme: a near-black neutral ground with a single orange
accent. Values live in
[docs/design-tokens/tokens.json](docs/design-tokens/tokens.json) and are
verified — not asserted — by `pnpm test:tokens`, which checks 31 contrast
pairs across both themes and exits non-zero on any failure.
`packages/ui` generates the CSS custom properties from that one file, so a
colour cannot drift between documentation and product.

Full rules: [docs/design-system.md](docs/design-system.md).

## Non-negotiables

Enforced, not aspirational — see [CLAUDE.md](CLAUDE.md):

- `organization_id` comes from the verified token, never from a request.
- Capabilities, not roles. `can("gap.assign")`, never `role === "manager"`.
- No analytical value or currency literal in a React component.
- No gap without a metric version, detector version, evidence and an as-of time.
- No modelled money without low, base, high, assumptions and confidence.
- AI cites; it never calculates.
- No silent failure: rejected records are quarantined with a reason and counted.

## Documentation

| Document                                                                                    | Covers                                                       |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [product-spec](docs/product-spec.md)                                                        | Roles, gap families, surfaces, editorial rules               |
| [gap-model](docs/gap-model.md)                                                              | The Gap aggregate, lifecycle, exposure, confidence, evidence |
| [data-contracts](docs/data-contracts.md)                                                    | Layers, envelope, facts, dimensions, metric contract         |
| [architecture](docs/architecture.md)                                                        | Services, request paths, boundaries                          |
| [design-concepts](docs/design-concepts.md)                                                  | Three scored shell concepts and the decision                 |
| [design-system](docs/design-system.md)                                                      | Tokens, density, motion, state coverage                      |
| [connector-sdk](docs/connector-sdk.md)                                                      | Manifest, interface, tiers, contract tests                   |
| [security-and-privacy](docs/security-and-privacy.md) · [threat-model](docs/threat-model.md) | Controls and the threats they answer                         |
| [demo-plan](docs/demo-plan.md)                                                              | Northstar Outfitters, six scenarios, reset and purge         |
| [implementation-plan](docs/implementation-plan.md)                                          | Phases A–I with acceptance criteria                          |
| [spec-review](docs/spec-review.md)                                                          | Contradictions found and how each was resolved               |
| [adr/](docs/adr/)                                                                           | Eight architecture decisions                                 |
