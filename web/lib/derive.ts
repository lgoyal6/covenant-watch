import { dateToMs } from "./format";
import type { CardSummary } from "@/components/CovenantCard";
import type { CovenantArtifact, CovenantEvent, QuarterResult, Refusal, Status } from "./types";

const SEVERITY: Record<Status, number> = { breach: 4, indeterminate: 3, warning: 2, ok: 1, refused: 0 };

export function severity(s: Status): number {
  return SEVERITY[s] ?? 0;
}

/** Quarters for one covenant, oldest first. */
export function quartersFor(a: CovenantArtifact, covId: string): QuarterResult[] {
  return a.quarters
    .filter((q) => q.covenant_id === covId)
    .sort((x, y) => dateToMs(x.period_end) - dateToMs(y.period_end));
}

/** Latest computed (non-refused) quarter, else the latest quarter. Matches api covenant_summary. */
export function latestQuarter(qs: QuarterResult[]): QuarterResult | null {
  const computed = qs.filter((q) => q.status !== "refused");
  return computed.at(-1) ?? qs.at(-1) ?? null;
}

/** Refusals that explain a given quarter of a covenant. */
export function refusalsForQuarter(refusals: Refusal[], covId: string, periodEnd: string): Refusal[] {
  return refusals.filter(
    (r) =>
      (r.scope === "quarter" && r.ref === periodEnd) ||
      (r.scope === "covenant" && r.ref === covId) ||
      r.scope === "company",
  );
}

/** The quarter the demo should open: last computed quarter on or before the first event, else the most severe. */
export function pickDemoQuarter(qs: QuarterResult[], events: CovenantEvent[]): QuarterResult | null {
  const computed = qs.filter((q) => q.status !== "refused");
  if (!computed.length) return qs[0] ?? null;
  const firstEvent = events.map((e) => dateToMs(e.date)).sort((a, b) => a - b)[0];
  if (firstEvent !== undefined) {
    const before = computed.filter((q) => dateToMs(q.period_end) <= firstEvent);
    if (before.length) return before[before.length - 1];
  }
  return [...computed].sort((a, b) => severity(b.status) - severity(a.status) || dateToMs(b.period_end) - dateToMs(a.period_end))[0];
}

/** Covenant card summaries for an artifact (latest computed quarter per covenant). */
export function summarize(a: CovenantArtifact): CardSummary[] {
  return a.contract.covenants.map((c) => {
    const qs = quartersFor(a, c.id);
    const l = latestQuarter(qs);
    return {
      id: c.id,
      kind: c.kind,
      direction: c.direction,
      status: l?.status ?? "refused",
      latest_period_end: l?.period_end ?? null,
      ratio_low: l?.ratio_low,
      ratio_high: l?.ratio_high,
      threshold: l?.threshold,
      headroom_low: l?.headroom_low,
      headroom_high: l?.headroom_high,
      quarters: qs.length,
      refused: qs.filter((q) => q.status === "refused").length,
    };
  });
}

