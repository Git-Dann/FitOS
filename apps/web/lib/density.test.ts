/**
 * The density preference is small enough that the only interesting question is
 * what it does when storage misbehaves — which is the case a manual check never
 * covers, because storage works on the machine you are testing on.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { DENSITY_KEY, isDensity, readDensity, writeDensity } from "./density";

/** Swaps in a storage implementation for the duration of one test. */
function withStorage(impl: unknown, body: () => void): void {
  const previous = globalThis.window;
  // @ts-expect-error -- deliberately minimal stand-in for a DOM global
  globalThis.window = { localStorage: impl };
  try {
    body();
  } finally {
    if (previous === undefined) delete (globalThis as { window?: unknown }).window;
    else globalThis.window = previous;
  }
}

test("only the two documented densities are accepted", () => {
  assert.equal(isDensity("compact"), true);
  assert.equal(isDensity("comfortable"), true);
  // The old row height token that is no longer a density choice.
  assert.equal(isDensity("touch"), false);
  assert.equal(isDensity(null), false);
  assert.equal(isDensity(""), false);
});

test("a stored preference is read back", () => {
  const store = new Map([[DENSITY_KEY, "comfortable"]]);
  withStorage({ getItem: (k: string) => store.get(k) ?? null }, () => {
    assert.equal(readDensity(), "comfortable");
  });
});

test("compact is the default, because density is the point", () => {
  withStorage({ getItem: () => null }, () => {
    assert.equal(readDensity(), "compact");
  });
});

test("a junk stored value falls back rather than reaching the class name", () => {
  // Without the guard this would return "; }" and land in a className, which is
  // the difference between an unknown preference and a broken stylesheet.
  withStorage({ getItem: () => "comfortable; }" }, () => {
    assert.equal(readDensity(), "compact");
  });
});

test("storage that throws does not take the page down", () => {
  const boom = () => {
    throw new Error("storage disabled");
  };
  withStorage({ getItem: boom, setItem: boom }, () => {
    assert.equal(readDensity(), "compact");
    // Writing must not propagate either: a blocked storage API is a lost
    // preference, not a failed interaction.
    assert.doesNotThrow(() => writeDensity("comfortable"));
  });
});
