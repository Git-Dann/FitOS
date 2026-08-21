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
  { slug: "radar", url: "/", expect: "Pressure by scope and hour" },
  { slug: "inbox", url: "/inbox", expect: "Estimated exposure" },
  { slug: "metrics", url: "/metrics", expect: "Metric" },
  { slug: "sources", url: "/sources", expect: "Source" },
];

const failures = [];

/** Drives the command menu, which is now the only way to change role. */
async function selectRole(page, role) {
  await page.keyboard.press("Control+k");
  await page.waitForSelector(".command", { state: "visible" });
  await page.fill(".command-input", `act as ${role}`);
  await page.waitForTimeout(60);
  await page.keyboard.press("Enter");
  await page.waitForSelector(".command", { state: "detached" });
  await page.waitForTimeout(120);
}

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
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await selectRole(page, "frontline");
  const text = await page.textContent("body");
  if (!text?.includes("withheld"))
    failures.push("frontline: exposure was not reported as withheld");
  if (/£/.test(text ?? "")) failures.push("frontline: a currency figure survived into the payload");
  await page.screenshot({ path: path.join(outDir, "role-frontline-1440x900.png") });
  await page.close();
}

// A severity filter applied, so the review sees the narrowed state too.
{
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.click(".sev-pill-critical");
  await page.waitForTimeout(120);
  await page.screenshot({ path: path.join(outDir, "filter-critical-1440x900.png") });
  await page.close();
}

// The command menu, which the source spec calls the soul of the app.
{
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.keyboard.press("Control+k");
  await page.waitForSelector(".command", { state: "visible" });
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(160);
  const focused = await page.locator('.command-row[aria-selected="true"]').count();
  if (focused !== 1) failures.push(`command menu: ${focused} focused rows, expected exactly 1`);
  await page.screenshot({ path: path.join(outDir, "command-menu-1440x900.png") });
  await page.close();
}

// Comfortable density, which is the only place the recommended action shows.
{
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.click('.density-switch button:has-text("comfortable")');
  await page.waitForTimeout(160);
  const rows = page.locator(".gap-row");
  const box = await rows.first().boundingBox();
  // 52px per the spec, allowing for the sub-pixel rounding of a border.
  if (!box || box.height < 50) {
    failures.push(`comfortable density: row is ${box?.height ?? "?"}px, expected >= 50`);
  }
  const actions = await page.locator(".gap-action-title").count();
  if (actions === 0) failures.push("comfortable density: no recommended action rendered");
  await page.screenshot({ path: path.join(outDir, "density-comfortable-1440x900.png") });
  await page.close();
}

// Compact is the default, and its row must be the spec's 44px.
{
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark");
  const box = await page.locator(".gap-row").first().boundingBox();
  if (!box || box.height < 43 || box.height > 46) {
    failures.push(`compact density: row is ${box?.height ?? "?"}px, expected 44`);
  }
  await page.close();
}

// The row's geometry at phone width. This is the assertion the previous build
// needed and did not have: the mobile block still reshaped the three-line row
// that preceded the Linear refactor, so nine children were being laid into two
// tracks. Nothing overflowed, so nothing failed.
{
  const page = await open(browser, base + "/inbox", { width: 390, height: 844 }, "dark");
  const row = await page.evaluate(() => {
    const el = document.querySelector(".gap-row");
    if (!el) return null;
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const title = el.querySelector(".gap-title");
    return {
      tracks: style.gridTemplateColumns.split(" ").length,
      children: el.children.length,
      height: Math.round(box.height),
      right: Math.round(box.right),
      titleWidth: title ? Math.round(title.getBoundingClientRect().width) : 0,
    };
  });
  if (!row) failures.push("mobile row: no .gap-row found");
  else {
    // Counting children against tracks is the wrong test: a grid legitimately
    // flows onto implicit rows, which is exactly what the exposure and
    // confidence values are meant to do at this width. What actually goes wrong
    // when children outnumber their tracks is that boxes land on top of each
    // other, so overlap is the invariant worth asserting.
    const overlaps = await page.evaluate(() => {
      const visible = [...document.querySelector(".gap-row").children]
        .filter((child) => getComputedStyle(child).display !== "none")
        .map((child) => ({
          name: child.className || child.tagName,
          box: child.getBoundingClientRect(),
        }));
      const hits = [];
      for (let a = 0; a < visible.length; a += 1) {
        for (let b = a + 1; b < visible.length; b += 1) {
          const one = visible[a].box;
          const two = visible[b].box;
          const horizontal = one.left < two.right - 1 && two.left < one.right - 1;
          const vertical = one.top < two.bottom - 1 && two.top < one.bottom - 1;
          if (horizontal && vertical) hits.push(`${visible[a].name} / ${visible[b].name}`);
        }
      }
      return hits;
    });
    if (overlaps.length > 0) {
      failures.push(`mobile row: overlapping children — ${overlaps.join(", ")}`);
    }
    // The title is the field that says what the problem is. If it has collapsed
    // to nothing, the row is useless whatever else fits.
    if (row.titleWidth < 140) {
      failures.push(`mobile row: title is ${row.titleWidth}px wide, expected >= 140`);
    }
    if (row.right > 390) failures.push(`mobile row: extends to ${row.right}px`);
  }
  await page.close();
}

// Frontline at 390: the one combination where §5's 48px touch rule binds, and
// the one nobody had captured.
{
  const page = await open(browser, base + "/inbox", { width: 390, height: 844 }, "dark", {
    deviceScaleFactor: 2,
  });
  await selectRole(page, "frontline");
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
  const page = await open(browser, base + "/inbox", { width: 1440, height: 900 }, "dark", {
    deviceScaleFactor: 2,
  });
  await page.fill(".search", "zzzz-no-such-gap");
  await page.waitForTimeout(120);
  await page.screenshot({ path: path.join(outDir, "empty-filter-1440x900.png") });
  await page.close();
}

// Every chart on the dashboard must carry all six parts of the §7 contract.
// The props are required, so a missing one does not compile — but an empty
// string does, and an empty provenance line is exactly as useless as none.
{
  const page = await open(browser, base + "/", { width: 1440, height: 1000 }, "dark");
  const charts = await page.evaluate(() =>
    [...document.querySelectorAll(".chart")].map((chart) => ({
      title: chart.querySelector(".chart-title")?.textContent?.trim() ?? "",
      scale: chart.querySelector(".chart-scale")?.textContent?.trim() ?? "",
      summary: chart.querySelector(".chart-summary")?.textContent?.trim() ?? "",
      provenance: chart.querySelector(".chart-provenance")?.textContent?.trim() ?? "",
      rows: chart.querySelectorAll(".chart-table tbody tr").length,
    })),
  );
  if (charts.length === 0) failures.push("dashboard: no charts found");
  for (const chart of charts) {
    const name = chart.title || "(untitled)";
    if (!chart.title) failures.push("chart: no title");
    if (chart.scale.length < 8) failures.push(`${name}: no scale stated`);
    // A summary must describe the shape in numbers, not name the chart type.
    if (chart.summary.length < 40)
      failures.push(`${name}: summary is ${chart.summary.length} chars`);
    if (!/as of/.test(chart.provenance)) failures.push(`${name}: no as-of time`);
    if (!/·/.test(chart.provenance)) failures.push(`${name}: no source attribution`);
    if (chart.rows === 0) failures.push(`${name}: no data table`);
  }
  await page.screenshot({ path: path.join(outDir, "radar-full-1440x900.png"), fullPage: true });
  await page.close();
}

await browser.close();

if (failures.length > 0) {
  console.error("Capture failed:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log(`Captured to ${outDir}`);
