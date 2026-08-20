/**
 * The stylesheet's own contract.
 *
 * A `var(--does-not-exist)` is not an error in CSS. The declaration is dropped
 * and the property falls back to its inherited or initial value, so the page
 * still renders, the build still passes, and the only symptom is that something
 * is the wrong colour — which nobody notices in a diff.
 *
 * The Linear refactor shipped four of these. Replacing the palette deleted
 * `--status-critical`, `--status-high`, `--status-medium` and `--status-low`,
 * and twelve references to them survived: every connector-state dot on the
 * sources route lost its colour, and so did the dismissal refusal message and
 * the invalid-textarea border — the exact error state a design review had
 * already flagged once for being invisible.
 *
 * These tests read the real files rather than a fixture, because the point is
 * to check what ships.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const globals = readFileSync(resolve(here, "../app/globals.css"), "utf8");
const tokens = readFileSync(resolve(here, "../../../packages/ui/dist/tokens.css"), "utf8");

/** Comments document the source spec's hex values, so they are not code. */
const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
const globalsCode = stripComments(globals);

/**
 * Custom properties supplied from outside the stylesheets. `next/font` emits
 * these into a generated CSS module and sets the class on `<html>`, so they are
 * genuinely defined at runtime and genuinely absent from any file here.
 */
const EXTERNAL = new Set(["--font-sans", "--font-mono"]);

/**
 * The first capture group of every match, dropping any that did not capture.
 *
 * `noUncheckedIndexedAccess` types a destructured group as `string | undefined`
 * even where the pattern makes it unreachable, and asserting it away would
 * defeat the setting on every future use of this helper.
 */
function captures(css: string, pattern: RegExp): string[] {
  return [...css.matchAll(pattern)]
    .map((match) => match[1])
    .filter((value): value is string => value !== undefined);
}

/** Custom properties a stylesheet defines: `--name:` at a declaration site. */
function defined(css: string): Set<string> {
  return new Set(captures(css, /(--[a-z0-9-]+)\s*:/gi));
}

/** Custom properties a stylesheet reads, ignoring any with a fallback value. */
function referenced(css: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (const name of captures(css, /var\(\s*(--[a-z0-9-]+)\s*\)/gi)) {
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return counts;
}

test("both stylesheets were actually read", () => {
  // Every assertion below is vacuous over an empty string.
  assert.ok(globals.length > 5000, `globals.css is ${globals.length} bytes`);
  assert.ok(tokens.length > 1000, `tokens.css is ${tokens.length} bytes`);
});

test("every custom property the product reads is defined somewhere", () => {
  const available = new Set([...defined(tokens), ...defined(globalsCode), ...EXTERNAL]);
  const missing = [...referenced(globalsCode)]
    .filter(([name]) => !available.has(name))
    .map(([name, count]) => `${name} (${count}×)`);
  assert.deepEqual(missing, [], `undefined custom properties: ${missing.join(", ")}`);
});

test("no selector survives for an element the markup no longer renders", () => {
  // Dead rules are harmless until one of them starts matching again, and then
  // it is a treatment nobody remembers writing. These three were left behind by
  // the Linear refactor: the row's old two-tier body, its old metadata line and
  // its old right-hand column.
  for (const selector of [".gap-main", ".gap-side", ".gap-meta-secondary", ".confidence-pips"]) {
    assert.ok(!globalsCode.includes(selector), `${selector} is styled but never rendered`);
  }
});

test("the typeface class is declared once", () => {
  // `.mono` was declared twice. The later rule won, which replaced the loaded
  // mono face with the system stack and shrank every gap reference in the
  // ledger from 13px to 11px. A duplicated class is not a conflict CSS reports.
  const declarations = [...globalsCode.matchAll(/^\.mono\s*[,{]/gm)];
  assert.equal(declarations.length, 1, `.mono declared ${declarations.length} times`);
});

test("no colour literal appears outside the token files", () => {
  // design-system.md §10: "A colour literal outside the token ramps — lint
  // error." Until that rule exists, this is the check.
  const literals = [...globalsCode.matchAll(/#[0-9a-f]{3,8}\b/gi)].map(([hex]) => hex);
  assert.deepEqual(literals, [], `colour literals in globals.css: ${literals.join(", ")}`);
});

test("no motion exceeds the source spec's ceiling", () => {
  // "Animate fast (90–240ms) — every transition should feel near-instant" and
  // "Don't animate slowly — anything over ~250ms feels broken in Linear."
  const durations = captures(globalsCode, /--motion-[a-z]+:\s*(\d+)ms/g).map(Number);
  assert.ok(durations.length >= 4, `expected the motion tokens, found ${durations.length}`);
  for (const ms of durations) {
    assert.ok(ms >= 90 && ms <= 240, `${ms}ms is outside the 90–240ms range`);
  }
});
