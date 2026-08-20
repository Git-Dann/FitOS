import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

/**
 * Browser globals whose names collide with ordinary local identifiers.
 *
 * This exists because of a real bug rather than as a precaution. `CommandMenu`
 * used to take an `open` prop; when the component was changed to be mounted
 * only while open, the prop went away but two `if (!open) return` guards did
 * not. The identifier kept resolving — to `window.open`, a function, therefore
 * always truthy — so both guards silently did nothing, TypeScript had no
 * complaint to make, the build passed and the tests passed.
 *
 * A leftover name that still resolves is the worst kind of leftover, and this
 * whole family behaves the same way: delete a `status` prop and you get
 * `window.status` (a string), a `name` prop and you get `window.name`, a
 * `length` and you get `window.length` (a number). Each one turns a deleted
 * binding into a plausible value instead of an error.
 *
 * `no-restricted-globals` fires only on a bare identifier that resolves to the
 * global — `props.open`, `window.open(…)` and a local `const open` are all
 * untouched — so it catches exactly the mistake and nothing else.
 */
const SHADOWING_GLOBALS = [
  [
    "open",
    "did you mean a local `open`? A deleted prop leaves `window.open`, which is always truthy.",
  ],
  ["name", "a deleted `name` binding leaves `window.name`, an empty string."],
  ["status", "a deleted `status` binding leaves `window.status`, an empty string."],
  ["length", "a deleted `length` binding leaves `window.length`, a number."],
  ["closed", "a deleted `closed` binding leaves `window.closed`, a boolean."],
  ["event", "use the handler's own event parameter; `window.event` is legacy and unreliable."],
  ["parent", "a deleted `parent` binding leaves `window.parent`, a Window."],
  ["top", "a deleted `top` binding leaves `window.top`, a Window."],
  ["self", "a deleted `self` binding leaves `window.self`, a Window."],
  ["frames", "a deleted `frames` binding leaves `window.frames`, a Window."],
  ["origin", "a deleted `origin` binding leaves `window.origin`, a string."],
  ["external", "a deleted `external` binding leaves `window.external`, an object."],
  ["screen", "a deleted `screen` binding leaves `window.screen`, an object."],
  ["history", "a deleted `history` binding leaves `window.history`; use next/navigation."],
  ["find", "a deleted `find` binding leaves `window.find`, a function."],
  ["stop", "a deleted `stop` binding leaves `window.stop`, a function."],
  ["print", "a deleted `print` binding leaves `window.print`, a function."],
  ["close", "a deleted `close` binding leaves `window.close`, a function."],
  ["focus", "a deleted `focus` binding leaves `window.focus`, a function."],
  ["blur", "a deleted `blur` binding leaves `window.blur`, a function."],
  ["scroll", "a deleted `scroll` binding leaves `window.scroll`, a function."],
].map(([name, message]) => ({ name, message }));

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  {
    rules: {
      // docs/design-system.md §10 — mechanised design rules. Raw HTML injection
      // is how the legacy prototype smuggled 4,000-character CSS strings into
      // components; this platform never does.
      "react/no-danger": "error",
      "no-restricted-globals": ["error", ...SHADOWING_GLOBALS],
    },
  },
  {
    // The capture and serve scripts run in Node against a real browser, where
    // `open` is a local helper and there is no DOM global to shadow.
    files: ["scripts/**"],
    rules: { "no-restricted-globals": "off" },
  },
];

export default config;
