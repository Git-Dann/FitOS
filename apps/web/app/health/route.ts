import type { HealthStatus } from "@fitos/contracts";

export const dynamic = "force-dynamic";

/** Liveness only. Readiness for the web tier is its ability to reach the API,
 *  which is checked by the API's own /ready — the web app never probes
 *  infrastructure directly (docs/architecture.md §2). */
export function GET(): Response {
  const body: HealthStatus = {
    status: "ok",
    service: "web",
    version: process.env.npm_package_version ?? "0.0.0",
  };
  return Response.json(body);
}
