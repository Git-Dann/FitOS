import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
execFileSync("node", [resolve(here, "../scripts/build-tokens.mjs")], { stdio: "pipe" });
const css = readFileSync(resolve(here, "../dist/tokens.css"), "utf8");

test("emits the near-black canvas and orange accent as the dark default", () => {
  const root = css.slice(css.indexOf(":root,"), css.indexOf('[data-theme="light"]'));
  assert.match(root, /--bg-canvas: #0B0C0E;/);
  assert.match(root, /--accent-fill: #F75F14;/);
  assert.match(root, /--accent-fg: #FF7A3C;/);
});

test("the label on an accent fill is near-black in both themes", () => {
  // White on orange measures 3.90:1 and fails AA; near-black measures 6.15:1.
  const occurrences = css.match(/--on-accent: #0B0C0E;/g) ?? [];
  assert.ok(
    occurrences.length >= 2,
    `expected >=2 --on-accent declarations, got ${occurrences.length}`,
  );
  assert.doesNotMatch(css, /--on-accent: #FFFFFF;/i);
});

test("light inverts elevation: tinted canvas, white panels", () => {
  const light = css.slice(css.indexOf('[data-theme="light"]'));
  assert.match(light, /--bg-canvas: #F7F8F9;/);
  assert.match(light, /--bg-surface: #FFFFFF;/);
});

test("every semantic reference resolved to a literal colour", () => {
  // Anything that is not a hex literal is unresolved, whatever it looks like.
  // The previous version of this test matched only `neutral.` and `accent.`
  // references by name, so when the status ramps were added — nested one level
  // deeper than the flat scales — the resolver produced `[object Object]` for
  // every one of them and this test passed. A guard that enumerates the shapes
  // it knows about cannot catch the shape nobody thought of.
  const declarations = [...css.matchAll(/^\s*--([a-z0-9-]+): (.+);$/gm)];
  assert.ok(
    declarations.length > 40,
    `expected a populated stylesheet, got ${declarations.length}`,
  );
  const unresolved = declarations
    .filter(([, , value]) => !/^#[0-9A-F]{6}$/i.test(value))
    .map(([, name, value]) => `${name}: ${value}`);
  assert.deepEqual(unresolved, [], `unresolved token references: ${unresolved.join(", ")}`);
});

test("the semantic tier carries status, so no component reaches into tier 1", () => {
  // §1: components consume tier 3, which resolves through tier 2. Until these
  // existed, every severity rule in globals.css referenced a primitive ramp and
  // then hand-wrote its own light-theme override — the drift §1 describes.
  for (const severity of ["critical", "high", "medium", "low"]) {
    assert.match(css, new RegExp(`--status-${severity}: #[0-9A-F]{6};`, "i"));
    assert.match(css, new RegExp(`--status-${severity}-border: #[0-9A-F]{6};`, "i"));
  }
  // Dark takes the 400 step and light the 700 step; if both themes emitted the
  // same value the mapping would be missing and nothing else here would notice.
  const dark = css.slice(css.indexOf(":root,"), css.indexOf('[data-theme="light"]'));
  const light = css.slice(css.indexOf('[data-theme="light"]'));
  assert.match(dark, /--status-critical: #FF6166;/);
  assert.match(light, /--status-critical: #AA2429;/);
});

test("no comment metadata key leaked into the CSS", () => {
  assert.doesNotMatch(css, /--\$comment/);
});
