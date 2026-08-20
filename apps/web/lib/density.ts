/**
 * Row density, persisted per user.
 *
 * DESIGN.md §4 gives the issue row two heights — "44pt (compact) / 52pt
 * (comfortable)" — and §5 of our own design system has promised a persisted
 * density preference since Phase A without ever shipping one.
 *
 * Compact is the default because the source spec is unambiguous that density is
 * the point: "44pt rows pack the maximum number of issues into a viewport —
 * Linear is a triage tool". Comfortable buys the recommended-action line.
 */
export type Density = "compact" | "comfortable";

export const DENSITIES: readonly Density[] = ["compact", "comfortable"];

export const DENSITY_KEY = "fitos-density";

export function isDensity(value: unknown): value is Density {
  return value === "compact" || value === "comfortable";
}

/** Reads the stored preference. Storage being unavailable is not an error. */
export function readDensity(): Density {
  try {
    const stored = window.localStorage.getItem(DENSITY_KEY);
    return isDensity(stored) ? stored : "compact";
  } catch {
    return "compact";
  }
}

export function writeDensity(density: Density): void {
  try {
    window.localStorage.setItem(DENSITY_KEY, density);
  } catch {
    // The preference simply does not survive a reload.
  }
  listeners.forEach((listener) => listener());
}

/**
 * The preference is external state, so React reads it through
 * `useSyncExternalStore` rather than copying it into `useState` inside an
 * effect. Copying it means rendering once with the wrong value and correcting
 * it, which is both a visible reflow of every row and a cascading render.
 *
 * `storage` covers another tab changing it; the local set covers this one,
 * because a tab does not receive its own storage event.
 */
const listeners = new Set<() => void>();

export function subscribeDensity(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** Dark-horse detail: this must be referentially stable, or the store re-reads
 *  forever. Returning the literal union satisfies that; an object would not. */
export const serverDensity = (): Density => "compact";
