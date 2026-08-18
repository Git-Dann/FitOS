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
  const unresolved = css.match(/--[a-z-]+: (neutral|accent)\.\d+;/g);
  assert.equal(unresolved, null, `unresolved token references: ${unresolved}`);
});

test("no comment metadata key leaked into the CSS", () => {
  assert.doesNotMatch(css, /--\$comment/);
});
