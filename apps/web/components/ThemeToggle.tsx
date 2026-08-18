"use client";

/**
 * Light/dark toggle.
 *
 * §2 calls light "a full peer, built and tested, not an afterthought", and the
 * product hard-coded `data-theme="dark"` with no way to reach the other one. A
 * theme nobody can switch to is a theme nobody has looked at — which is how the
 * selected-row treatment came to be invisible in light, where `--bg-raised` and
 * `--bg-surface` are both white.
 *
 * The current theme is read from the DOM through `useSyncExternalStore` rather
 * than mirrored into React state. The attribute is set before hydration by the
 * inline script in `layout.tsx`, so it is genuinely external state; copying it
 * into `useState` inside an effect means rendering once with the wrong value
 * and then correcting it, which is both a flash and a cascading render.
 */
import { useSyncExternalStore } from "react";

type Theme = "dark" | "light";

const STORAGE_KEY = "fitos-theme";

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function readTheme(): Theme {
  return document.documentElement.dataset["theme"] === "light" ? "light" : "dark";
}

/** Dark on the server, matching the attribute the document ships with. */
function serverTheme(): Theme {
  return "dark";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, readTheme, serverTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function choose() {
    document.documentElement.dataset["theme"] = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A blocked storage API is not a reason to refuse the switch; the choice
      // simply does not survive a reload.
    }
  }

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={choose}
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
    >
      <span aria-hidden="true">{theme === "dark" ? "◐" : "◑"}</span>
      <span className="theme-toggle-word">{next}</span>
    </button>
  );
}
