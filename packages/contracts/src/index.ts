/**
 * Shared contracts between the web app and the API.
 *
 * Phase A holds only the health contract, which is the one thing every
 * service must agree on before anything else exists. The generated OpenAPI
 * client lands here in Phase B; from that point these types are generated
 * from the API schema and a CI drift check fails the build if they diverge.
 */

/** Liveness: the process is up. Says nothing about dependencies. */
export type HealthStatus = {
  status: "ok";
  service: string;
  version: string;
};

/** Readiness: the service can serve traffic, with a per-dependency verdict. */
export type ReadyStatus = {
  status: "ready" | "degraded";
  service: string;
  checks: Record<string, DependencyCheck>;
};

export type DependencyCheck = {
  ok: boolean;
  /** Present only when ok is false. Never contains a secret or a host name. */
  detail?: string;
};

export const isReady = (r: ReadyStatus): boolean => r.status === "ready";
