// Mirrors shared/schema.py (SCHEMA_VERSION 1.0) and the shapes returned by api/main.py.
// Fields are typed loosely where the API may add keys later; the UI never assumes extras.

export type Source = "fixture" | "data" | "demo";
export type Status = "ok" | "warning" | "breach" | "indeterminate" | "refused";
export type Direction = "max" | "min";

export interface Span {
  accession: string;
  url: string;
  section?: string | null;
  char_start: number;
  char_end: number;
  text: string;
}

export interface ClauseContext {
  before: string;
  match: string;
  after: string;
}

export interface SpanWithContext extends Span {
  context?: ClauseContext | null;
  context_note?: string;
}

export interface Company {
  cik: string;
  name: string;
  ticker?: string | null;
  sic?: string | null;
}

export interface Agreement {
  accession: string;
  url: string;
  filed: string;
  kind: "original" | "amendment" | "restatement";
  redacted: boolean;
  filing_url?: string | null;
}

export interface Cap {
  kind: "pct_of" | "abs" | string;
  of?: string;
  pct?: number;
  usd?: number;
  [k: string]: unknown;
}

export interface TermNode {
  id: string;
  label: string;
  op: "sum" | "subtract" | "ratio" | "leaf" | "cap" | "floor";
  children: string[];
  cap?: Cap | null;
  span?: Span;
  clause?: SpanWithContext;
}

export interface Threshold {
  effective_from: string;
  effective_to?: string | null;
  value: number;
  source: Span;
}

export interface Covenant {
  id: string;
  kind: string;
  direction: Direction;
  numerator_term: string;
  denominator_term?: string | null;
  test_period: "ttm" | "quarter" | "point_in_time";
  thresholds: Threshold[];
  agreement_accession: string;
  span: Span;
}

export interface Refusal {
  scope: "company" | "agreement" | "covenant" | "quarter";
  ref: string;
  reason: string;
  detail: string;
}

export interface Input {
  term_node: string;
  value?: number | null;
  xbrl_concept?: string | null;
  fact_accession?: string | null;
  period_start?: string | null;
  period_end: string;
  mapping_confidence: number;
  validated: boolean;
  validation_note?: string | null;
  filing_url?: string | null;
  label?: string;
}

export interface QuarterResult {
  covenant_id: string;
  period_end: string;
  ratio_low?: number | null;
  ratio_high?: number | null;
  threshold?: number | null;
  headroom_low?: number | null;
  headroom_high?: number | null;
  status: Status;
  inputs?: Input[];
  missing: string[];
  n_inputs?: number;
}

export interface ContractExtraction {
  schema_version: string;
  generated_at: string;
  company: Company;
  agreements: Agreement[];
  terms: TermNode[];
  covenants: Covenant[];
  refusals: Refusal[];
  extraction_notes?: string[];
}

export interface CovenantArtifact {
  schema_version: string;
  generated_at: string;
  contract: ContractExtraction;
  quarters: QuarterResult[];
  refusals: Refusal[];
}

export interface DisclosedRatio {
  cik: string;
  period_end: string;
  covenant_kind: string;
  reported_value: number;
  reported_threshold?: number | null;
  span: Span;
}

export interface CovenantEvent {
  cik: string;
  date: string;
  kind: "waiver" | "amendment_loosening" | "default" | "acceleration" | string;
  span: Span;
}

// ---- API responses ----

export interface CovenantSummary {
  id: string;
  kind: string;
  direction: Direction;
  latest_period_end: string | null;
  status: Status;
  ratio_low: number | null;
  ratio_high: number | null;
  threshold: number | null;
  headroom_low: number | null;
  headroom_high: number | null;
  quarters: number;
}

export interface CompanyListItem extends Company {
  source: Source;
  covenants: CovenantSummary[];
  refusals: number;
}

export interface CompaniesResponse {
  source: Source;
  companies: CompanyListItem[];
}

export interface CompanyResponse {
  source: Source;
  artifact: CovenantArtifact;
}

export interface TimelineResponse {
  source: Source;
  company: Company;
  covenant: Covenant;
  quarters: QuarterResult[];
  thresholds: Threshold[];
  agreements: Agreement[];
  events: CovenantEvent[];
  disclosed: DisclosedRatio[];
  refusals: Refusal[];
}

export interface ProvenanceResponse {
  source: Source;
  company: Company;
  covenant: Omit<Covenant, "span" | "thresholds">;
  covenant_clause: SpanWithContext;
  threshold_clause: SpanWithContext | null;
  quarter: QuarterResult;
  inputs: Input[];
  terms: TermNode[];
  refusals: Refusal[];
}

export interface EvalResponse {
  source: Source;
  report: Record<string, unknown> | null;
}

export interface OverviewCovenant {
  cik: string;
  name: string;
  ticker: string | null;
  covenant_id: string;
  kind: string;
  direction: Direction;
  status: Status;
  latest_period_end: string | null;
  ratio_low: number | null;
  ratio_high: number | null;
  threshold: number | null;
  headroom_low: number | null;
  headroom_high: number | null;
  quarters: number;
  /** Worst-case headroom as a fraction of the threshold; negative = past the limit. */
  headroom_pct: number | null;
  history: { period_end: string; status: Status; headroom_pct: number | null }[];
}

export interface OverviewResponse {
  source: Source;
  companies: number;
  covenants: number;
  quarters: number;
  status_latest: Record<Status, number>;
  status_by_quarter: ({ quarter: string } & Record<Status, number>)[];
  closest: OverviewCovenant[];
  events: { cik: string; name: string; date: string; kind: string; span: { url: string; text: string } }[];
  events_total: number;
  refusals: Record<string, number>;
  eval_source: Source;
  ratio_accuracy: Record<string, number | string | null>;
  early_warning: Record<string, number | string | null>;
}
