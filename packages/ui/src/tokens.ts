/**
 * Token loader. The single source of truth is docs/design-tokens/tokens.json,
 * which `node docs/design-tokens/check-contrast.mjs` verifies against WCAG 2.2 AA.
 * Nothing here restates a colour value — restating one is how a palette drifts.
 */
import tokens from "../../../docs/design-tokens/tokens.json" with { type: "json" };

export type Theme = "dark" | "light";
export type Tokens = typeof tokens;

/** Dark is the default theme; light is a tested peer. See docs/design-system.md §2. */
export const DEFAULT_THEME: Theme = "dark";

export const primitives = tokens.primitive;
export const semantic = tokens.semantic;
export default tokens;
