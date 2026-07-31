import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${pathname}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the FitOS marketing experience", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html[^>]*lang="en-GB"/i);
  assert.match(html, /<title>FitOS — Fitting room operations<\/title>/i);
  assert.match(html, /Turn fitting-room intent into fulfilled sales\./);
  assert.match(html, /Fitting-room operations/);
  assert.match(html, /Existing barcode\. Existing device\./);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("keeps production metadata and routes connected", async () => {
  const [page, layout, marketing, customer, associate, manager, pilot] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/ui/Marketing.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/demo/customer/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/demo/associate/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/demo/manager/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/pilot/page.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(page, /MarketingHome/);
  assert.match(layout, /lang="en-GB"/);
  assert.match(layout, /Fitting room operations/);
  assert.match(layout, /openGraph/);
  assert.match(marketing, /not an AI stylist/);
  assert.match(marketing, /not a guaranteed promise/);
  for (const route of [customer, associate, manager, pilot]) {
    assert.match(route, /export default function/);
  }
});

test("serves every public product route", async () => {
  const routes = ["/", "/platform", "/demo", "/demo/customer", "/demo/associate", "/demo/manager", "/pilot"];
  const responses = await Promise.all(routes.map((route) => render(route)));

  for (const response of responses) {
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  }
});
