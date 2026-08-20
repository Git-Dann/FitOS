#!/usr/bin/env node
// Verifies FitOS colour tokens against WCAG 2.2 AA contrast requirements.
//   node docs/design-tokens/check-contrast.mjs
// Exits non-zero on any failing pair. Reads tokens.json so the two cannot drift.
//
// The palette is Linear's, copied exactly. That palette is internally AA-safe
// for a reason worth stating: Linear never sets text in its accent colour.
// #5E6AD2 measures 4.24:1 on the canvas and 3.59:1 on a raised row — under the
// 4.5:1 body-text floor, and comfortably over the 3:1 floor for a glyph, a ring
// or a focus indicator, which is the only way the source spec ever uses it
// ("Active item: label #F7F8F8, 16pt icon #5E6AD2"). So the accent is checked
// here as a non-text indicator, and `accent-glyph` is named to make a text use
// of it look wrong at the call site.

import { readFileSync } from "node:fs";

const tokens = JSON.parse(readFileSync(new URL("./tokens.json", import.meta.url), "utf8"));

const hex = (h) => {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const channel = (c) => {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = (h) => {
  const [r, g, b] = hex(h).map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/** Resolve a semantic name, or a "scale.step" primitive reference, to a hex. */
const resolve = (theme, name) => {
  const raw = tokens.semantic[theme][name] ?? name;
  if (raw.startsWith("#")) return raw;
  const value = raw.split(".").reduce((node, key) => node?.[key], tokens.primitive);
  if (typeof value !== "string") throw new Error(`unresolvable reference: ${raw}`);
  return value;
};

// [label, foreground, background, minimum ratio]
// 4.5 = body text, 3 = large text / non-text UI indicators (WCAG 2.2 AA).
// Values below 3 are surface-separation checks, not WCAG requirements.
const suite = (theme) => {
  const t = (n) => resolve(theme, n);
  const canvas = t("bg-canvas");
  const surface = t("bg-surface");
  const raised = t("bg-raised");
  return [
    ["fg-default on canvas", t("fg-default"), canvas, 4.5],
    ["fg-default on surface", t("fg-default"), surface, 4.5],
    ["fg-default on raised", t("fg-default"), raised, 4.5],
    ["fg-default on pressed", t("fg-default"), t("bg-pressed"), 4.5],
    ["fg-default on the selection wash", t("fg-default"), t("accent-wash"), 4.5],
    ["fg-muted on canvas", t("fg-muted"), canvas, 4.5],
    ["fg-muted on surface", t("fg-muted"), surface, 4.5],
    ["fg-muted on raised", t("fg-muted"), raised, 4.5],
    ["fg-subtle on canvas (large/UI only)", t("fg-subtle"), canvas, 3],
    // The accent is a fill, a glyph, a ring and a wash — never a text colour.
    ["accent glyph on canvas (UI indicator)", t("accent-glyph"), canvas, 3],
    ["accent glyph on raised (UI indicator)", t("accent-glyph"), raised, 3],
    ["label on accent fill", t("on-accent"), t("accent-fill"), 4.5],
    ["label on accent pressed", t("on-accent"), t("accent-pressed"), 4.5],
    ["focus ring vs canvas", t("focus-ring"), canvas, 3],
    ["border-strong (selection) vs canvas", t("border-strong"), canvas, 3],
    // Status text sits on the canvas and on rows; both grounds are checked.
    ["status urgent on canvas", t("status-urgent"), canvas, 4.5],
    ["status urgent on raised", t("status-urgent"), raised, 4.5],
    ["status progress on canvas", t("status-progress"), canvas, 4.5],
    ["status neutral on canvas", t("status-neutral"), canvas, 4.5],
    ["status canceled on canvas (UI only)", t("status-canceled"), canvas, 3],
    ["success on canvas", t("success"), canvas, 4.5],
    ["warning on canvas", t("warning"), canvas, 4.5],
    ["error on canvas", t("error"), canvas, 4.5],
    // Elevation, in both themes. The source spec is explicit that elevation is
    // "a one-step background lift and a precise 1pt border, not blur" — so a
    // luminance-only threshold is the wrong test for this palette. On a
    // near-OLED canvas the lift Linear actually achieves is 1.18:1, and the
    // border is what finishes the job. Both are required, in both directions,
    // which is a wider check than the luminance-only one it replaces.
    ["raised lifts off canvas", raised, canvas, 1.05],
    // The selected row must be distinguishable from both the canvas and the
    // hover ground, in both themes. Light has only one surface value in the
    // source spec, so hover and raised resolve to the same colour there and
    // the purple wash is what carries selection — an earlier build set
    // selection to `bg-raised`, which in light was the same white as the
    // surface, and the selected row was invisible.
    ["selection wash separates from canvas", t("accent-wash"), canvas, 1.05],
    ["selection wash separates from raised", t("accent-wash"), raised, 1.04],
    ["surface lifts off canvas", surface, canvas, 1.05],
    ["border separates from canvas", t("border-default"), canvas, 1.05],
    ["border separates from surface", t("border-default"), surface, 1.05],
  ];
};

let failures = 0;
for (const theme of ["dark", "light"]) {
  console.log(`\n=== ${theme.toUpperCase()}${theme === "dark" ? " (default)" : " (limited variant)"} ===`);
  for (const [label, fg, bg, need] of suite(theme)) {
    const r = contrast(fg, bg);
    const ok = r >= need;
    if (!ok) failures++;
    console.log(
      `${ok ? " ok " : "FAIL"}  ${r.toFixed(2).padStart(6)}:1  (need ${need})  ${label}  ${fg} on ${bg}`,
    );
  }
}

// The reason the accent is never a text colour, stated as a number rather than
// as a convention someone can quietly break.
const asText = contrast(tokens.primitive.purple.base, tokens.primitive.ink.canvas);
console.log(
  `\nNOTE  accent as body text on the dark canvas = ${asText.toFixed(2)}:1 — under the 4.5:1 floor.` +
    `\n      This is why the token is called accent-glyph and why every label on a purple ground is` +
    `\n      ${tokens.primitive.ink.white}. See docs/design-system.md §2.`,
);

console.log(`\n${failures} failing pair(s)`);
process.exit(failures === 0 ? 0 : 1);
