import type { Direction, Refusal, Status } from "./types";

const KIND_LABELS: Record<string, string> = {
  max_leverage: "Max leverage",
  max_senior_leverage: "Max senior leverage",
  min_interest_coverage: "Min interest coverage",
  min_fixed_charge_coverage: "Min fixed charge coverage",
  min_liquidity: "Min liquidity",
  other: "Other covenant",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? humanize(kind);
}

export function humanize(s: string): string {
  const t = s.replace(/[_-]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export const STATUS_LABEL: Record<Status, string> = {
  ok: "OK",
  warning: "Warning",
  breach: "Breach",
  indeterminate: "Indeterminate",
  refused: "Refused",
};

export const STATUS_HELP: Record<Status, string> = {
  ok: "Whole computed range is clear of the threshold with margin.",
  warning: "Whole range is compliant but within the warning margin of the threshold.",
  breach: "Whole computed range is on the wrong side of the threshold.",
  indeterminate: "The computed range crosses the threshold, or one side is unbounded. Compliance cannot be called either way.",
  refused: "Not computed. See the refusal reason.",
};

export function directionHelp(d: Direction): string {
  return d === "max" ? "Breach if ratio is above the threshold" : "Breach if ratio is below the threshold";
}

const MINUS = "−";

function num(v: number, digits = 2): string {
  const s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return v < 0 ? `${MINUS}${s}` : s;
}

/** A covenant ratio like 4.87x. */
export function fmtRatio(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  return `${num(v, digits)}x`;
}

export function fmtSigned(v: number, digits = 2): string {
  if (v > 0) return `+${num(v, digits)}x`;
  return `${num(v, digits)}x`;
}

/**
 * A ratio range. A null side on a computed quarter means that side is unbounded
 * (an uncapped addback), never zero.
 */
export function fmtRatioRange(lo: number | null | undefined, hi: number | null | undefined, status?: Status): string {
  if (status === "refused") return "Not computed";
  const hasLo = lo !== null && lo !== undefined;
  const hasHi = hi !== null && hi !== undefined;
  if (!hasLo && !hasHi) return "Unbounded";
  if (!hasLo) return `≤ ${fmtRatio(hi)} (lower side unbounded)`;
  if (!hasHi) return `≥ ${fmtRatio(lo)} (upper side unbounded)`;
  if (Math.abs(lo - hi) < 0.00005) return fmtRatio(lo);
  return `${fmtRatio(lo)} to ${fmtRatio(hi)}`;
}

/** Headroom range, worst case first. Null side on a computed quarter is unbounded. */
export function fmtHeadroomRange(lo: number | null | undefined, hi: number | null | undefined, status?: Status): string {
  if (status === "refused") return "Not computed";
  if (lo == null && hi == null) return "Unbounded";
  if (lo == null) return `unbounded to ${fmtSigned(hi as number)}`;
  if (hi == null) return `${fmtSigned(lo)} to unbounded`;
  if (Math.abs(lo - hi) < 0.00005) return fmtSigned(lo);
  return `${fmtSigned(lo)} to ${fmtSigned(hi)}`;
}

export function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  const a = Math.abs(v);
  const sign = v < 0 ? MINUS : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(a >= 1e10 ? 1 : 2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(a >= 1e8 ? 0 : 1)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(0)}K`;
  return `${sign}$${a.toFixed(0)}`;
}

export function fmtUsdFull(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  return (v < 0 ? MINUS : "") + "$" + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** ISO date (YYYY-MM-DD) to "Sep 30, 2024" without timezone drift. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** Period end to fiscal-calendar-ish label: "Q3 2024" (calendar quarter of the period end). */
export function fmtQuarter(iso: string): string {
  const [y, m] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m) return iso;
  return `Q${Math.ceil(m / 3)} ${y}`;
}

export function fmtPct(v: number, digits = 0): string {
  return `${(v * 100).toFixed(digits)}%`;
}

export function dateToMs(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, (m || 1) - 1, d || 1);
}

export const REASON_LABEL: Record<string, string> = {
  redacted: "Redacted agreement",
  ambiguous_definition: "Ambiguous definition",
  missing_filing: "Missing filing",
  unmapped_term: "Unmapped term",
  pro_forma_adjustment: "Pro forma adjustment",
  currency_or_units: "Currency or units",
  other: "Other",
};

export function reasonLabel(r: string): string {
  return REASON_LABEL[r] ?? humanize(r);
}

export function refusalScopeLabel(r: Refusal): string {
  switch (r.scope) {
    case "quarter":
      return `Quarter ending ${fmtDate(r.ref)}`;
    case "covenant":
      return `Covenant ${r.ref}`;
    case "agreement":
      return `Agreement ${r.ref}`;
    default:
      return "Whole company";
  }
}

export const EVENT_LABEL: Record<string, string> = {
  waiver: "Waiver",
  amendment_loosening: "Loosening amendment",
  default: "Default",
  acceleration: "Acceleration",
};

export function eventLabel(k: string): string {
  return EVENT_LABEL[k] ?? humanize(k);
}

export const OP_LABEL: Record<string, string> = {
  sum: "sum",
  subtract: "subtract",
  ratio: "ratio",
  leaf: "input",
  cap: "capped",
  floor: "floor",
};
