/**
 * Demonstration gap data.
 *
 * Every row here is fictional and the UI says so on every surface that renders
 * it — `DemoDataBanner` is not optional decoration, it is the rule from
 * docs/product-spec.md §8 that demo data is labelled wherever it appears,
 * including in screenshots.
 *
 * The shape mirrors the real `Gap` aggregate field for field
 * (docs/gap-model.md §1), so the components built against it need no change
 * when the API is hosted and the source swaps. That is the whole reason this
 * file is shaped like the database rather than like the screen: a fixture
 * modelled on the view is a fixture that lies about what the view will receive.
 *
 * Formatted currency and percentage literals are permitted *here* and nowhere
 * else in `apps/web` — see docs/design-system.md §10. The values below are
 * integer minor units exactly as the aggregate stores them; the formatting
 * happens in `format.ts`, once.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type ConfidenceBand = "low" | "medium" | "high";
export type GapStatus =
  | "detected"
  | "triaged"
  | "investigating"
  | "actioned"
  | "validating"
  | "resolved"
  | "dismissed";

export interface EvidenceRef {
  canonicalEntity: string;
  metricKey: string;
  metricVersion: number;
  queryHash: string;
  sourceLabel: string;
  rowCount: number;
  sensitivity: "public" | "internal" | "confidential" | "restricted";
}

export interface Assumption {
  key: string;
  statement: string;
  value: string;
  source: string;
  kind: "observed" | "governed_metric" | "assumption";
}

export interface ConfidenceComponent {
  key: string;
  label: string;
  score: number;
}

export interface DemoGap {
  id: string;
  reference: string;
  packKey: string;
  gapType: string;
  gapTypeLabel: string;
  title: string;
  summary: string;
  scopeType: string;
  scopeId: string;

  metricKey: string;
  metricVersion: number;
  observedValue: number;
  expectedValue: number;
  unit: "count" | "ratio" | "currency_minor" | "seconds";
  observedLabel: string;
  expectedLabel: string;

  /** Integer minor units, or null when the gap carries no money — which is a
   *  complete gap, not a missing one. */
  exposureLow: number | null;
  exposureBase: number | null;
  exposureHigh: number | null;
  currency: string | null;
  isModelled: boolean;
  formulaLabel: string | null;
  assumptions: Assumption[];

  confidenceScore: number;
  confidenceBand: ConfidenceBand;
  confidenceComponents: ConfidenceComponent[];
  confidenceDropped: string[];

  severity: Severity;
  status: GapStatus;
  ownerInitials: string | null;

  firstSeenAt: string;
  lastSeenAt: string;
  asOfAt: string;
  dataFreshnessSeconds: number | null;

  ruleKey: string;
  ruleVersion: number;
  reasonCodes: string[];
  evidence: EvidenceRef[];
}

/** Fixed so the ledger renders identically on every load and in every
 *  screenshot. A demo whose ages drift is a demo that cannot be reviewed. */
export const DEMO_AS_OF = "2026-08-18T14:00:00Z";

export const DEMO_GAPS: DemoGap[] = [
  {
    id: "0199a1d2-0000-7000-8000-000000000014",
    reference: "NS-014",
    packKey: "retail_omnichannel",
    gapType: "stock_truth_mismatch",
    gapTypeLabel: "Stock truth",
    title: "Stock records and counts disagree at Oxford Street (34% of checks)",
    summary:
      "34% of 120 stock checks in this window found a quantity different from the inventory record. The two sources disagree; which one is right is not established by this metric.",
    scopeType: "location",
    scopeId: "Oxford Street",
    metricKey: "stock_discrepancy_rate",
    metricVersion: 1,
    observedValue: 0.34,
    expectedValue: 0.02,
    unit: "ratio",
    observedLabel: "41 of 120 checks disagreed",
    expectedLabel: "≤ 2% (estate baseline)",
    exposureLow: 615000,
    exposureBase: 902000,
    exposureHigh: 1271000,
    currency: "GBP",
    isModelled: true,
    formulaLabel: "discrepant checks × unit margin band",
    assumptions: [
      {
        key: "discrepant_checks",
        statement: "41 of 120 stock checks disagreed with the record",
        value: "41",
        source: "stock_discrepancy_rate@v1",
        kind: "observed",
      },
      {
        key: "unit_margin_minor",
        statement: "Contribution margin per unit, set by the organisation",
        value: "150..310 (base 220)",
        source: "organization_assumption",
        kind: "assumption",
      },
    ],
    confidenceScore: 0.905,
    confidenceBand: "high",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 1.0 },
      { key: "source_agreement", label: "Source agreement", score: 0.66 },
      { key: "freshness", label: "Freshness", score: 1.0 },
    ],
    confidenceDropped: ["completeness", "identity_match", "metric_stability"],
    severity: "critical",
    status: "triaged",
    ownerInitials: "RS",
    firstSeenAt: "2026-08-12T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 7200,
    ruleKey: "source_mismatch",
    ruleVersion: 1,
    reasonCodes: ["source_disagreement", "modelled_exposure"],
    evidence: [
      {
        canonicalEntity: "fact_stock_count",
        metricKey: "stock_discrepancy_rate",
        metricVersion: 1,
        queryHash: "9f2c41ab",
        sourceLabel: "POS CSV upload",
        rowCount: 120,
        sensitivity: "internal",
      },
      {
        canonicalEntity: "fact_inventory_snapshot",
        metricKey: "stock_discrepancy_rate",
        metricVersion: 1,
        queryHash: "9f2c41ab",
        sourceLabel: "Inventory REST",
        rowCount: 118,
        sensitivity: "internal",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000007",
    reference: "NS-007",
    packKey: "retail_omnichannel",
    gapType: "source_freshness_breach",
    gapTypeLabel: "Data quality",
    title: "Footfall counter is 31 hours behind its expected cadence",
    summary:
      "The newest record from the footfall counter is 31 hours old, against a declared cadence of 1 hour. Metrics built on this source describe an older world than they appear to.",
    scopeType: "organization",
    scopeId: "footfall_counter",
    metricKey: "source_freshness",
    metricVersion: 1,
    observedValue: 111600,
    expectedValue: 3600,
    unit: "seconds",
    observedLabel: "31h since the newest record",
    expectedLabel: "1h declared cadence",
    exposureLow: null,
    exposureBase: null,
    exposureHigh: null,
    currency: null,
    isModelled: false,
    formulaLabel: null,
    assumptions: [],
    confidenceScore: 1.0,
    confidenceBand: "high",
    confidenceComponents: [{ key: "detector_fit", label: "Detector fit", score: 1.0 }],
    confidenceDropped: [
      "sample_size",
      "completeness",
      "freshness",
      "source_agreement",
      "identity_match",
      "metric_stability",
    ],
    severity: "critical",
    status: "triaged",
    ownerInitials: "AM",
    firstSeenAt: "2026-08-17T07:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 111600,
    ruleKey: "source_freshness",
    ruleVersion: 1,
    reasonCodes: ["source_late"],
    evidence: [
      {
        canonicalEntity: "connector_run",
        metricKey: "source_freshness",
        metricVersion: 1,
        queryHash: "3ab7d190",
        sourceLabel: "Footfall counter",
        rowCount: 1,
        sensitivity: "internal",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000021",
    reference: "NS-021",
    packKey: "retail_omnichannel",
    gapType: "conversion_below_band",
    gapTypeLabel: "Conversion",
    title: "Conversion rate at Trafford is 62% below its peer group",
    summary:
      "Conversion rate at Trafford was 0.11 over 480 observations: 62% below its peer group median of 0.29. These are comparisons, not explanations — nothing here establishes what differs.",
    scopeType: "location",
    scopeId: "Trafford",
    metricKey: "conversion_rate",
    metricVersion: 2,
    observedValue: 0.11,
    expectedValue: 0.29,
    unit: "ratio",
    observedLabel: "11% over 480 sessions",
    expectedLabel: "29% peer median (9 stores)",
    exposureLow: null,
    exposureBase: null,
    exposureHigh: null,
    currency: null,
    isModelled: false,
    formulaLabel: null,
    assumptions: [],
    confidenceScore: 0.724,
    confidenceBand: "high",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 0.7 },
      { key: "source_agreement", label: "Peer group size", score: 0.9 },
    ],
    confidenceDropped: ["completeness", "freshness", "identity_match", "metric_stability"],
    severity: "high",
    status: "detected",
    ownerInitials: null,
    firstSeenAt: "2026-08-16T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 5400,
    ruleKey: "baseline_comparison",
    ruleVersion: 1,
    reasonCodes: ["below_peer_group"],
    evidence: [
      {
        canonicalEntity: "fact_transaction",
        metricKey: "conversion_rate",
        metricVersion: 2,
        queryHash: "c41e7b02",
        sourceLabel: "POS CSV upload",
        rowCount: 480,
        sensitivity: "internal",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000033",
    reference: "NS-033",
    packKey: "retail_omnichannel",
    gapType: "purchase_funnel_drop",
    gapTypeLabel: "Funnel",
    title: "Order step on iOS 4.2.1: 16% continue (expected 70%)",
    summary:
      "920 of 1,100 people who reached Order in the purchase funnel did not continue. That is 16% against an expected 70%. This locates the step; it does not establish why.",
    scopeType: "channel",
    scopeId: "iOS 4.2.1",
    metricKey: "funnel_counts",
    metricVersion: 1,
    observedValue: 0.16,
    expectedValue: 0.7,
    unit: "ratio",
    observedLabel: "180 of 1,100 continued",
    expectedLabel: "70% expected at this step",
    exposureLow: 2655000,
    exposureBase: 2655000,
    exposureHigh: 2655000,
    currency: "GBP",
    isModelled: true,
    formulaLabel: "conversions short × value per conversion",
    assumptions: [
      {
        key: "conversions_short",
        statement: "590 fewer continued than the expected 70% of 1,100",
        value: "590",
        source: "funnel_counts",
        kind: "observed",
      },
      {
        key: "value_per_conversion_minor",
        statement: "Value of one conversion at this step, set by the organisation",
        value: "4500",
        source: "organization_assumption",
        kind: "assumption",
      },
    ],
    confidenceScore: 1.0,
    confidenceBand: "high",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 1.0 },
    ],
    confidenceDropped: [
      "completeness",
      "freshness",
      "identity_match",
      "metric_stability",
      "source_agreement",
    ],
    severity: "critical",
    status: "actioned",
    ownerInitials: "LK",
    firstSeenAt: "2026-08-09T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 1800,
    ruleKey: "funnel_drop",
    ruleVersion: 1,
    reasonCodes: ["funnel_step_below_threshold", "stage_order", "modelled_exposure"],
    evidence: [
      {
        canonicalEntity: "fact_session",
        metricKey: "funnel_counts",
        metricVersion: 1,
        queryHash: "77aa1e5c",
        sourceLabel: "App analytics REST",
        rowCount: 10000,
        sensitivity: "internal",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000045",
    reference: "NS-045",
    packKey: "retail_omnichannel",
    gapType: "margin_leakage",
    gapTypeLabel: "Margin",
    title: "Margin on Field Jacket fell 8.0% against the prior period",
    summary:
      "Margin rate on Field Jacket was 28.0% against 36.0% in the prior period, while revenue rose. The figures name what moved; discounting, mix shift, supplier cost and returns are indistinguishable in a margin rate and none of them is established here.",
    scopeType: "product_variant",
    scopeId: "Field Jacket · Stone",
    metricKey: "gross_margin_rate",
    metricVersion: 1,
    observedValue: 0.28,
    expectedValue: 0.36,
    unit: "ratio",
    observedLabel: "28.0% this period",
    expectedLabel: "36.0% prior period",
    exposureLow: 96000,
    exposureBase: 96000,
    exposureHigh: 96000,
    currency: "GBP",
    isModelled: false,
    formulaLabel: "revenue × margin points lost",
    assumptions: [
      {
        key: "revenue_minor",
        statement: "Revenue in the window, from the ledger",
        value: "1200000",
        source: "fact_financial_line",
        kind: "observed",
      },
      {
        key: "margin_points_lost",
        statement: "Margin rate fell 0.08 against the prior period",
        value: "0.08",
        source: "fact_financial_line",
        kind: "observed",
      },
    ],
    confidenceScore: 1.0,
    confidenceBand: "high",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 1.0 },
      { key: "completeness", label: "Completeness", score: 1.0 },
    ],
    confidenceDropped: ["freshness", "identity_match", "metric_stability", "source_agreement"],
    severity: "high",
    status: "detected",
    ownerInitials: null,
    firstSeenAt: "2026-08-14T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 86400,
    ruleKey: "financial_leakage",
    ruleVersion: 1,
    reasonCodes: ["margin_below_prior_period", "revenue_up_margin_down"],
    evidence: [
      {
        canonicalEntity: "fact_financial_line",
        metricKey: "gross_margin_rate",
        metricVersion: 1,
        queryHash: "b1d0e922",
        sourceLabel: "Finance export",
        rowCount: 800,
        // Margin figures are not internal-by-default.
        sensitivity: "confidential",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000052",
    reference: "NS-052",
    packKey: "retail_omnichannel",
    gapType: "campaign_below_baseline",
    gapTypeLabel: "Attribution",
    title:
      "Attributable orders per pound for Spring Refresh is below its baseline (0.62 against 1.00)",
    summary:
      "Attributable orders per pound for Spring Refresh was 0.62 over 900 observations, against a baseline of 1.00. This coincides with the spend in this window under the last_touch model; the model assigns credit, it does not establish that the spend produced the outcome.",
    scopeType: "campaign",
    scopeId: "Spring Refresh",
    metricKey: "attributable_orders_per_pound",
    metricVersion: 1,
    observedValue: 0.62,
    expectedValue: 1.0,
    unit: "ratio",
    observedLabel: "0.62 orders per pound",
    expectedLabel: "1.00 baseline",
    exposureLow: 6800,
    exposureBase: 13700,
    exposureHigh: 23900,
    currency: "GBP",
    isModelled: true,
    formulaLabel: "shortfall × attributable share (last touch)",
    assumptions: [
      {
        key: "attributed_shortfall",
        statement: "342 units below baseline over 900 observations",
        value: "342",
        source: "attributable_orders_per_pound@v1",
        kind: "observed",
      },
      {
        key: "attributable_share",
        statement:
          "Share genuinely attributable under the last_touch model, set by the organisation",
        value: "0.20..0.70 (base 0.40)",
        source: "organization_assumption:last_touch",
        kind: "assumption",
      },
    ],
    // Capped at medium by construction. A correlation between spend and
    // outcome does not establish the link, and no sample size changes that.
    confidenceScore: 0.84,
    confidenceBand: "medium",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 0.6 },
    ],
    confidenceDropped: [
      "completeness",
      "freshness",
      "identity_match",
      "metric_stability",
      "source_agreement",
    ],
    severity: "medium",
    status: "investigating",
    ownerInitials: "DK",
    firstSeenAt: "2026-08-11T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 10800,
    ruleKey: "attribution_comparison",
    ruleVersion: 1,
    reasonCodes: ["attribution_below_baseline", "method_last_touch", "attribution_limited"],
    evidence: [
      {
        canonicalEntity: "fact_campaign_spend",
        metricKey: "attributable_orders_per_pound",
        metricVersion: 1,
        queryHash: "5c9f30de",
        sourceLabel: "Ad platform REST",
        rowCount: 900,
        sensitivity: "confidential",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000061",
    reference: "NS-061",
    packKey: "retail_omnichannel",
    gapType: "data_completeness_drop",
    gapTypeLabel: "Data quality",
    title: "Loyalty feed delivered 41.0% of expected records",
    summary:
      "2,950 of 5,000 records from the loyalty feed were rejected or never arrived in this window. Metrics over this source are computed on a denominator that is missing rows.",
    scopeType: "organization",
    scopeId: "loyalty_feed",
    metricKey: "data_completeness",
    metricVersion: 1,
    observedValue: 0.41,
    expectedValue: 1.0,
    unit: "ratio",
    observedLabel: "2,050 of 5,000 accepted",
    expectedLabel: "100% expected",
    exposureLow: null,
    exposureBase: null,
    exposureHigh: null,
    currency: null,
    isModelled: false,
    formulaLabel: null,
    assumptions: [],
    confidenceScore: 0.672,
    confidenceBand: "medium",
    confidenceComponents: [
      { key: "detector_fit", label: "Detector fit", score: 1.0 },
      { key: "completeness", label: "Completeness", score: 0.41 },
    ],
    confidenceDropped: [
      "sample_size",
      "freshness",
      "identity_match",
      "metric_stability",
      "source_agreement",
    ],
    severity: "critical",
    status: "detected",
    ownerInitials: null,
    firstSeenAt: "2026-08-18T06:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 3600,
    ruleKey: "data_completeness",
    ruleVersion: 1,
    reasonCodes: ["records_missing"],
    evidence: [
      {
        canonicalEntity: "connector_run",
        metricKey: "data_completeness",
        metricVersion: 1,
        queryHash: "e70b4413",
        sourceLabel: "Loyalty REST",
        rowCount: 5000,
        sensitivity: "internal",
      },
    ],
  },
  {
    id: "0199a1d2-0000-7000-8000-000000000078",
    reference: "NS-078",
    packKey: "retail_omnichannel",
    gapType: "stock_truth_mismatch",
    gapTypeLabel: "Stock truth",
    title: "Stock records and counts disagree at Leeds (9% of checks)",
    summary:
      "9% of 210 stock checks in this window found a quantity different from the inventory record. The two sources disagree; which one is right is not established by this metric.",
    scopeType: "location",
    scopeId: "Leeds",
    metricKey: "stock_discrepancy_rate",
    metricVersion: 1,
    observedValue: 0.09,
    expectedValue: 0.02,
    unit: "ratio",
    observedLabel: "19 of 210 checks disagreed",
    expectedLabel: "≤ 2% (estate baseline)",
    exposureLow: 285000,
    exposureBase: 418000,
    exposureHigh: 589000,
    currency: "GBP",
    isModelled: true,
    formulaLabel: "discrepant checks × unit margin band",
    assumptions: [
      {
        key: "discrepant_checks",
        statement: "19 of 210 stock checks disagreed with the record",
        value: "19",
        source: "stock_discrepancy_rate@v1",
        kind: "observed",
      },
      {
        key: "unit_margin_minor",
        statement: "Contribution margin per unit, set by the organisation",
        value: "150..310 (base 220)",
        source: "organization_assumption",
        kind: "assumption",
      },
    ],
    confidenceScore: 0.949,
    confidenceBand: "high",
    confidenceComponents: [
      { key: "sample_size", label: "Sample size", score: 1.0 },
      { key: "detector_fit", label: "Detector fit", score: 1.0 },
      { key: "source_agreement", label: "Source agreement", score: 0.91 },
      { key: "freshness", label: "Freshness", score: 1.0 },
    ],
    confidenceDropped: ["completeness", "identity_match", "metric_stability"],
    severity: "medium",
    status: "detected",
    ownerInitials: null,
    firstSeenAt: "2026-08-15T00:00:00Z",
    lastSeenAt: "2026-08-18T14:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 5400,
    ruleKey: "source_mismatch",
    ruleVersion: 1,
    reasonCodes: ["source_disagreement", "modelled_exposure"],
    evidence: [
      {
        canonicalEntity: "fact_stock_count",
        metricKey: "stock_discrepancy_rate",
        metricVersion: 1,
        queryHash: "2d81ff06",
        sourceLabel: "POS CSV upload",
        rowCount: 210,
        sensitivity: "internal",
      },
    ],
  },
];

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

/** Groups by severity in the fixed order, dropping empty groups. */
export function groupBySeverity(gaps: DemoGap[]): { severity: Severity; gaps: DemoGap[] }[] {
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    gaps: gaps.filter((gap) => gap.severity === severity),
  })).filter((group) => group.gaps.length > 0);
}
