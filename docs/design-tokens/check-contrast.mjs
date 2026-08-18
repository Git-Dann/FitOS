#!/usr/bin/env node
// Verifies FitOS colour tokens against WCAG 2.2 AA contrast requirements.
//   node docs/design-tokens/check-contrast.mjs
// Exits non-zero on any failing pair. Reads tokens.json so the two cannot drift.
// Moves to packages/ui and becomes a CI gate in Phase E.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const tokens = JSON.parse(
  readFileSync(new URL("./tokens.json", import.meta.url), "utf8"),
);

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

// Resolve "neutral.400" style references against the primitive scales.
const resolve = (theme, name) => {
  const raw = tokens.semantic[theme][name] ?? name;
  if (raw.startsWith("#")) return raw;
  const [scale, step] = raw.split(".");
  return tokens.primitive[scale][step];
};
const status = (severity, step) => tokens.primitive.status[severity][step];

// [label, foreground, background, minimum ratio]
// 4.5 = body text, 3 = large text / non-text UI indicators (WCAG 2.2 AA).
// Values below 3 are surface-separation checks, not WCAG requirements.
const suite = (theme) => {
  const t = (n) => resolve(theme, n);
  const canvas = t("bg-canvas");
  const surface = t("bg-surface");
  const raised = t("bg-raised");
  const sev = theme === "dark" ? "400" : "700";
  return [
    ["fg-default on canvas", t("fg-default"), canvas, 4.5],
    ["fg-default on raised", t("fg-default"), raised, 4.5],
    ["fg-muted on canvas", t("fg-muted"), canvas, 4.5],
    ["fg-muted on raised", t("fg-muted"), raised, 4.5],
    ["fg-subtle on canvas (large/UI only)", t("fg-subtle"), canvas, 3],
    ["accent-fg on canvas", t("accent-fg"), canvas, 4.5],
    ["accent-fg on raised", t("accent-fg"), raised, 4.5],
    ["on-accent label on accent fill", t("on-accent"), t("accent-fill"), 4.5],
    ["focus ring vs canvas", t("focus-ring"), canvas, 3],
    ["border-strong (selection) vs canvas", t("border-strong"), canvas, 3],
    ["surface vs canvas separation", surface, canvas, 1.05],
    // Dark conveys elevation by background luminance, because shadows are
    // ineffective on a near-black ground. Light inverts it: panels are white on
    // a tinted ground, and raised surfaces separate by border and shadow, so a
    // luminance requirement would be wrong there rather than merely unmet.
    ...(theme === "dark" ? [["raised vs canvas separation", raised, canvas, 1.25]] : []),
    ...["critical", "high", "medium", "low"].map((s) => [
      `status ${s} on canvas`,
      status(s, sev),
      canvas,
      4.5,
    ]),
  ];
};

let failures = 0;
for (const theme of ["dark", "light"]) {
  console.log(`\n=== ${theme.toUpperCase()}${theme === "dark" ? " (default)" : ""} ===`);
  for (const [label, fg, bg, need] of suite(theme)) {
    const r = contrast(fg, bg);
    const ok = r >= need;
    if (!ok) failures++;
    console.log(
      `${ok ? " ok " : "FAIL"}  ${r.toFixed(2).padStart(6)}:1  (need ${need})  ${label}  ${fg} on ${bg}`,
    );
  }
}

// Documented, deliberate collision: the accent and the "high" severity colour
// are both warm and close in luminance. Resolved by role separation, never by
// hue alone — see docs/design-system.md §2.
const collision = contrast(
  tokens.primitive.accent["400"],
  status("high", "400"),
);
console.log(
  `\nNOTE  accent-400 vs status-high-400 = ${collision.toFixed(2)}:1 — too close to separate by colour alone.` +
    `\n      Accent is reserved for interaction; severity always carries an icon and a text label.`,
);

console.log(`\n${failures} failing pair(s)`);
process.exit(failures === 0 ? 0 : 1);
