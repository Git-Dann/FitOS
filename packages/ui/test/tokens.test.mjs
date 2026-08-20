import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
execFileSync("node", [resolve(here, "../scripts/build-tokens.mjs")], { stdio: "pipe" });
const css = readFileSync(resolve(here, "../dist/tokens.css"), "utf8");

const dark = css.slice(css.indexOf(":root,"), css.indexOf('[data-theme="light"]'));
const light = css.slice(css.indexOf('[data-theme="light"]'));

test("emits Linear's near-OLED canvas and purple accent as the dark default", () => {
  // The source spec is emphatic that the canvas is NOT the usual #121212:
  // "Don't use #121212 — Linear is darker; the near-OLED black is part of the
  // identity". Asserting the exact value is what keeps that from drifting back.
  assert.match(dark, /--bg-canvas: #08090A;/);
  assert.doesNotMatch(css, /#121212/i);
  assert.match(dark, /--accent-fill: #5E6AD2;/);
  assert.match(dark, /--accent-pressed: #4F58B8;/);
});

test("the accent is the only accent", () => {
  // "Don't introduce a second accent color — purple alone carries action and
  // focus." Every accent-role token must resolve to the purple pair, so a
  // second hue cannot enter through a token nobody is looking at.
  const accents = [...css.matchAll(/--(accent-[a-z-]+|focus-ring): (#[0-9A-F]{6});/gi)];
  assert.ok(accents.length >= 8, `expected accent tokens in both themes, got ${accents.length}`);
  const allowed = new Set(["#5E6AD2", "#4F58B8", "#141726", "#E8EAF9"]);
  for (const [, name, value] of accents) {
    assert.ok(allowed.has(value.toUpperCase()), `${name} is ${value}, not a purple-family value`);
  }
});

test("the label on an accent fill is white in both themes", () => {
  // Linear specifies #FFFFFF on purple, and it measures 4.70:1 — it passes.
  // The previous palette was orange, where white measured 3.90:1 and failed, so
  // this token was near-black. Swapping the accent without revisiting the label
  // colour is exactly the kind of change that silently breaks AA.
  const occurrences = css.match(/--on-accent: #FFFFFF;/g) ?? [];
  assert.ok(
    occurrences.length >= 2,
    `expected >=2 white --on-accent declarations, got ${occurrences.length}`,
  );
});

test("the accent is never emitted as a foreground text token", () => {
  // #5E6AD2 is 4.24:1 on the canvas — under the body-text floor. The spec only
  // ever uses it as a fill, a glyph, a ring or a wash, and the naming has to
  // make a text use look wrong rather than merely be discouraged.
  const fg = [...css.matchAll(/--(fg-[a-z-]+): (#[0-9A-F]{6});/gi)];
  assert.ok(fg.length >= 6, `expected fg tokens in both themes, got ${fg.length}`);
  for (const [, name, value] of fg) {
    assert.notEqual(value.toUpperCase(), "#5E6AD2", `${name} sets text to the accent`);
  }
});

test("light inverts the elevation direction: white canvas, tinted surfaces", () => {
  // Linear's light mode is the mirror of the dark ladder — canvas #FFFFFF with
  // surfaces tinted downward, rather than a tinted ground with white panels.
  assert.match(light, /--bg-canvas: #FFFFFF;/);
  assert.match(light, /--bg-surface: #F4F5F8;/);
  assert.match(dark, /--bg-canvas: #08090A;/);
  assert.match(dark, /--bg-surface: #141516;/);
});

test("the selection wash differs from both the canvas and the hover ground", () => {
  // Light ships a single surface value, so hover and raised are the same colour
  // there and the wash is the only thing that can carry selection. An earlier
  // build selected rows with `bg-raised`, which in light was the same white as
  // the surface — the selected row was invisible and no test noticed.
  for (const [name, block] of [
    ["dark", dark],
    ["light", light],
  ]) {
    const read = (token) => block.match(new RegExp(`--${token}: (#[0-9A-F]{6});`, "i"))?.[1];
    const wash = read("accent-wash");
    assert.ok(wash, `${name}: no accent-wash`);
    assert.notEqual(wash, read("bg-canvas"), `${name}: wash equals the canvas`);
    assert.notEqual(wash, read("bg-raised"), `${name}: wash equals the hover ground`);
  }
});

test("every semantic reference resolved to a literal colour", () => {
  // Anything that is not a hex literal is unresolved, whatever it looks like.
  // An earlier version of this test matched only `neutral.` and `accent.`
  // references by name, so when the nested status ramps were added the resolver
  // produced `[object Object]` for every one of them and this test passed. A
  // guard that enumerates the shapes it knows about cannot catch the shape
  // nobody thought of.
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
  for (const role of ["urgent", "progress", "done", "neutral", "canceled"]) {
    assert.match(css, new RegExp(`--status-${role}: #[0-9A-F]{6};`, "i"));
  }
  // Urgent is the one severity Linear colours; the rest are differentiated by
  // the priority-bar glyph, not by hue. If they ever diverge, the rainbow the
  // spec forbids has come back.
  const readDark = (token) => dark.match(new RegExp(`--${token}: (#[0-9A-F]{6});`, "i"))?.[1];
  assert.equal(readDark("status-urgent"), "#EB5757");
  assert.equal(readDark("status-neutral"), "#8A8F98");
});

test("the light status ramp is darkened, not inherited", () => {
  // Amber, red and green at their dark values measure 1.46:1, 3.19:1 and 2.29:1
  // on the light surface. Inheriting them is the single easiest way to ship an
  // unreadable light theme, and it looks fine in a dark-mode screenshot.
  for (const role of ["urgent", "progress"]) {
    const inDark = dark.match(new RegExp(`--status-${role}: (#[0-9A-F]{6});`, "i"))?.[1];
    const inLight = light.match(new RegExp(`--status-${role}: (#[0-9A-F]{6});`, "i"))?.[1];
    assert.notEqual(inLight, inDark, `status-${role} is the same value in both themes`);
  }
});

test("no comment metadata key leaked into the CSS", () => {
  assert.doesNotMatch(css, /\$comment/);
  assert.doesNotMatch(css, /\$deviations/);
});
