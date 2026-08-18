// GENERATED FILE — do not edit.
//
// Produced by data/metrics/compile.py. Edit the compiler, not this file.

module.exports = {
  /**
   * Multi-tenancy for the semantic layer.
   *
   * organization_id comes from the security context, which Cube derives from
   * the verified JWT. It is never read from the query: a caller-supplied tenant
   * is a caller-chosen tenant.
   *
   * The filter is appended, so a caller's own filters are ANDed with ours and a
   * wider filter cannot widen the result.
   */
  queryRewrite: (query, { securityContext }) => {
    const organizationId = securityContext && securityContext.org;

    if (!organizationId) {
      // Refused, not defaulted. Returning everything would be catastrophic;
      // returning nothing would look like an empty dataset and get "fixed".
      throw new Error("no organization in the security context; refusing to query");
    }

    query.filters = query.filters || [];
    query.filters.push({
      member: "organization_id",
      operator: "equals",
      values: [organizationId],
    });

    return query;
  },

  /**
   * The tenant is part of the cache key. Without this, one tenant's cached
   * result is served to another — a cache that ignores the tenant is a
   * cross-tenant read with a performance benefit.
   */
  contextToAppId: ({ securityContext }) =>
    `fitos_${(securityContext && securityContext.org) || "unknown"}`,

  contextToOrchestratorId: ({ securityContext }) =>
    `fitos_${(securityContext && securityContext.org) || "unknown"}`,
};
