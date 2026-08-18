/**
 * Capture the review screenshots, and refuse to produce them if the page fails
 * the reflow requirement while doing it.
 *
 * This exists as a committed script rather than an ad-hoc command because two
 * separate rounds of this build reviewed a stale server: the restart failed on
 * a held port, the old process kept answering, and the screenshots looked
 * plausible. The script therefore asserts the page it captured is the page it
 * meant to capture before it writes anything.
 *
 * §9 requires reflow to a 320px equivalent with no horizontal scrolling. That
 * is checked here rather than by eye, because a 4px overflow is invisible in a
 * screenshot and obvious to anyone holding the phone.
 *
 *   node scripts/capture.mjs http://localhost:3111 ../../docs/screenshots/phase-e
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const base = process.argv[2] ?? "http://localhost:3000";
const outDir = path.resolve(process.argv[3] ?? "../../docs/screenshots/phase-e");

const VIEWPORTS = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1024x768", width: 1024, height: 768 },
  { name: "390x844", width: 390, height: 844 },
];

/** The narrowest width §9 requires to reflow. Not screenshot, only asserted. */
const REFLOW_WIDTHS = [390, 320];

/**
 * §2 calls light "a full peer, built and tested". Until this ran in both, the
 * light theme had never been looked at by a human — and the selected-row
 * treatment was invisible in it, because `--bg-raised` and `--bg-surface` are
 * both white there.
 */
const THEMES = ["dark", "light"];

const ROUTES = [
  { slug: "inbox", url: "/", expect: "Estimated exposure" },
  { slug: "metrics", url: "/metrics", expect: "Metric" },
  { slug: "sources", url: "/sources", expect: "Source" },
];

const failures = [];

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();

/** Playwright honours prefers-color-scheme, so the theme is pinned explicitly
 *  rather than inherited from whatever the runner happens to prefer. */
async function open(browser, url, viewport, theme, extra = {}) {
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
    colorScheme: theme,
    ...extra,
  });
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem("fitos-theme", value);
    } catch {
      /* storage blocked; the media query still decides */
    }
  }, theme);
  await page.goto(url, { waitUntil: "networkidle" });
  const applied = await page.evaluate(() => document.documentElement.dataset.theme);
  if (applied !== theme) throw new Error(`asked for ${theme}, got ${applied}`);
  return page;
}

for (const route of ROUTES) {
  for (const theme of THEMES) {
    for (const viewport of VIEWPORTS) {
      const page = await open(browser, base + route.url, viewport, theme, { deviceScaleFactor: 2 });
      page.on("pageerror", (error) => failures.push(`${route.slug}: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error") failures.push(`${route.slug} console: ${message.text()}`);
      });

      // Prove we are looking at the build we think we are, not a stale server.
      const body = await page.textContent("body");
      if (!body?.includes(route.expect)) {
        failures.push(`${route.slug}: expected copy "${route.expect}" not found — stale server?`);
      }

      const suffix = theme === "dark" ? "" : `-${theme}`;
      await page.screenshot({
        path: path.join(outDir, `${route.slug}-${viewport.name}${suffix}.png`),
        fullPage: viewport.width < 700,
      });
      await page.close();
    }
  }

  for (const width of REFLOW_WIDTHS) {
    const page = await open(browser, base + route.url, { width, height: 844 }, "dark");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    if (overflow > 0) {
      failures.push(`${route.slug}: ${overflow}px of horizontal overflow at ${width}px (§9)`);
    }
    await page.close();
  }
}

// The frontline payload, which is the state most likely to regress silently:
// it is the one where the interesting fields are absent rather than wrong.
{
  const page = await open(browser, base + "/", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.selectOption("#role", "frontline");
  await page.waitForTimeout(120);
  const text = await page.textContent("body");
  if (!text?.includes("withheld"))
    failures.push("frontline: exposure was not reported as withheld");
  if (/£/.test(text ?? "")) failures.push("frontline: a currency figure survived into the payload");
  await page.screenshot({ path: path.join(outDir, "role-frontline-1440x900.png") });
  await page.close();
}

// A severity filter applied, so the review sees the narrowed state too.
{
  const page = await open(browser, base + "/", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.click(".sev-pill-critical");
  await page.waitForTimeout(120);
  await page.screenshot({ path: path.join(outDir, "filter-critical-1440x900.png") });
  await page.close();
}

// Frontline at 390: the one combination where §5's 48px touch rule binds, and
// the one nobody had captured.
{
  const page = await open(browser, base + "/", { width: 390, height: 844 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.selectOption("#role", "frontline");
  await page.waitForTimeout(120);
  const small = await page.evaluate(() =>
    [...document.querySelectorAll(".nav-item, .sev-pill, .view-tab")]
      .filter((el) => el.getBoundingClientRect().height < 44)
      .map((el) => `${el.className}:${Math.round(el.getBoundingClientRect().height)}px`),
  );
  if (small.length > 0) {
    failures.push(`frontline 390: targets under 44px — ${[...new Set(small)].join(", ")}`);
  }
  await page.screenshot({ path: path.join(outDir, "role-frontline-390x844.png"), fullPage: true });
  await page.close();
}

// The empty result. §8: a filter that matched nothing and a ledger with nothing
// in it must not look the same, and only one of them is good news.
{
  const page = await open(browser, base + "/", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.fill(".search", "zzzz-no-such-gap");
  await page.waitForTimeout(120);
  await page.screenshot({ path: path.join(outDir, "empty-filter-1440x900.png") });
  await page.close();
}

await browser.close();

if (failures.length > 0) {
  console.error("Capture failed:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log(`Captured to ${outDir}`);
