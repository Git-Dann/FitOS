---
name: run-demo-reset
description: Safely seed, reset, snapshot, purge or verify the FitOS demo tenant. Use whenever asked to reset the demo, reseed data, clear the demo tenant, or check that demo data is correct. Required reading before any destructive data command.
---

# Demo seed, reset and purge

Reference: `docs/demo-plan.md`. This is the **only** sanctioned data-destructive path in the
repository. Never run an ad-hoc `DROP`, `TRUNCATE` or `DELETE` against any database instead.

## Commands

```bash
pnpm demo:seed     --tenant northstar-outfitters [--dry-run]
pnpm demo:snapshot --tenant northstar-outfitters
pnpm demo:reset    --tenant northstar-outfitters [--dry-run]
pnpm demo:verify   --tenant northstar-outfitters
pnpm demo:purge    --tenant northstar-outfitters [--dry-run]
```

## Before running anything destructive

1. **Dry-run first.** Always. Read what it says it will remove.
2. **Confirm the tenant is a demo tenant.** The command enforces `is_demo`, but check the slug
   yourself — the guard is the backstop, not the plan.
3. **Snapshot before reset** if the current state matters to anyone.
4. **Never pass a wildcard or omit the tenant.** There is no all-organizations path here; if someone
   asks for one, that is the break-glass procedure with its own credential and approval, not this
   skill.
5. **Ask the user first** for `purge` on any tenant you did not seed in this session.

## Which command

| Situation | Command |
| --- | --- |
| First run, or data is missing | `demo:seed` — idempotent, safe to repeat |
| Demo has been clicked through and needs to be clean | `demo:reset` |
| About to demo and want a restore point | `demo:snapshot`, then reset after |
| Checking scenarios still produce their gaps | `demo:verify` |
| Removing the demo tenant entirely | `demo:purge` — typed slug confirmation |

## After running

- `demo:seed` or `demo:reset` → run `demo:verify` and quote its output. Seeding without verifying
  leaves determinism unproven.
- Check the audit log for the run record. Every seed, reset and purge writes one, including refusals.
- If a reset fails, it rolls back or restores the last valid snapshot. Confirm which happened before
  continuing — do not re-run over an unknown state.

## Expected verify assertions

Total record count matches the pinned figure; per-fact counts match; all six scenarios produce their
expected gaps; Scenario 2 produces one evolving stock-truth gap rather than one per day; Scenario 5's
margin gap outranks the highest-revenue gap; Scenario 6's freshness gap suppresses the dependent
conversion gap; reseeding reproduces identical gap ids; seeding twice changes nothing.

A failure in any of these is a real defect. Do not reseed until it passes — reseeding to make a
verification failure disappear destroys the evidence of the bug.
