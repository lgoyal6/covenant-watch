"use client";

import { useCallback, useMemo, useState } from "react";
import { refusalsForQuarter, summarize } from "@/lib/derive";
import {
  fmtDate,
  fmtHeadroomRange,
  fmtQuarter,
  fmtRatio,
  fmtRatioRange,
  kindLabel,
  reasonLabel,
  refusalScopeLabel,
  eventLabel,
} from "@/lib/format";
import type { Breakeven, CovenantArtifact, Refusal, Source, TimelineResponse } from "@/lib/types";
import CompanyAgent from "./agents/CompanyAgent";
import { CovenantCard, type CardSummary } from "./CovenantCard";
import ProvenanceDrawer from "./ProvenanceDrawer";
import Timeline, { TimelineLegend } from "./Timeline";
import { ExternalLink, FixtureBadge, StatusChip } from "./ui";

interface Props {
  source: Source;
  artifact: CovenantArtifact;
  timelines: Record<string, TimelineResponse | null>;
  timelineErrors: Record<string, string>;
  initialCov?: string | null;
  initialQuarter?: string | null;
  breakeven?: Breakeven[];
}

function setUrl(cov: string | null, q: string | null) {
  try {
    const u = new URL(window.location.href);
    if (cov) u.searchParams.set("cov", cov);
    else u.searchParams.delete("cov");
    if (q) u.searchParams.set("q", q);
    else u.searchParams.delete("q");
    window.history.replaceState(null, "", u.toString());
  } catch {}
}

export default function CompanyView({ source, artifact, timelines, timelineErrors, initialCov, initialQuarter, breakeven }: Props) {
  const c = artifact.contract.company;
  const covenants = artifact.contract.covenants;
  const summaries = useMemo(
    () =>
      summarize(artifact).map((s) => {
        const b = breakeven?.find((x) => x.covenant_id === s.id);
        return { ...s, breakeven: b ? { earnings: b.earnings_change_to_breach_pct, other: b.other_change_to_breach_pct } : null };
      }),
    [artifact, breakeven],
  );
  const [cov, setCov] = useState<string | null>(
    initialCov && covenants.some((x) => x.id === initialCov) ? initialCov : covenants[0]?.id ?? null,
  );
  const [quarter, setQuarter] = useState<string | null>(initialQuarter ?? null);

  const chooseCov = (id: string) => {
    setCov(id);
    setQuarter(null);
    setUrl(id, null);
  };
  const openQuarter = (pe: string) => {
    setQuarter(pe);
    setUrl(cov, pe);
  };
  const closeDrawer = useCallback(() => {
    setQuarter(null);
    setUrl(cov, null);
  }, [cov]);

  const events = useMemo(() => {
    const seen = new Set<string>();
    return Object.values(timelines)
      .flatMap((t) => t?.events ?? [])
      .filter((e) => (seen.has(e.date + e.kind) ? false : (seen.add(e.date + e.kind), true)))
      .sort((x, y) => (x.date < y.date ? 1 : -1));
  }, [timelines]);
  const tl = cov ? timelines[cov] : null;
  const covObj = covenants.find((x) => x.id === cov) ?? null;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <CompanyHero source={source} artifact={artifact} summaries={summaries} events={events} />

      {/* covenant cards */}
      {covenants.length === 0 ? (
        <div className="callout callout-muted">
          No covenants could be extracted for this company. See the refusals below for why.
        </div>
      ) : (
        <div className="grid-2">
          {summaries.map((s) => (
            <CovenantCard key={s.id} s={s} selected={s.id === cov} onClick={() => chooseCov(s.id)} />
          ))}
        </div>
      )}

      {covenants.length > 0 && <CompanyAgent cik={artifact.contract.company.cik} company={artifact.contract.company.name} />}

      <div className="co-pair">
        <Agreements artifact={artifact} />
        <EventsCard events={events} />
      </div>

      {/* timeline */}
      {covObj && (
        <section className="card" id="timeline">
          <div className="card-head">
            <div className="stack" style={{ gap: 2 }}>
              <h2>Headroom timeline: {kindLabel(covObj.kind)}</h2>
              <span className="small muted">
                Computed ratio range per quarter vs the threshold in force. Click a quarter for the clause and filing behind it.
              </span>
            </div>
            {tl && (
              <TimelineLegend
                direction={covObj.direction}
                hasEvents={tl.events.length > 0}
                hasDisclosed={tl.disclosed.length > 0}
                hasAmendments={tl.agreements.some((a) => a.kind !== "original")}
              />
            )}
          </div>
          <div className="card-pad">
            {tl ? (
              tl.quarters.length ? (
                <div className="chart-scroll">
                  <Timeline data={tl} selected={quarter} onSelect={openQuarter} />
                </div>
              ) : (
                <div className="empty">
                  <h3>No quarters computed</h3>
                  <p>This covenant has no quarterly results yet.</p>
                </div>
              )
            ) : (
              <div className="error-box small">Timeline unavailable: {timelineErrors[covObj.id] ?? "unknown error"}</div>
            )}
          </div>
          {tl && <ThresholdSchedule tl={tl} />}
          {tl && tl.quarters.length > 0 && (
            <QuarterTable tl={tl} selected={quarter} onSelect={openQuarter} />
          )}
        </section>
      )}

      <RefusalsPanel artifact={artifact} />

      {(artifact.contract.extraction_notes?.length ?? 0) > 0 && (
        <section className="card card-pad stack" style={{ gap: 6 }}>
          <h3>Extraction notes</h3>
          <ul style={{ margin: 0, paddingLeft: 18 }} className="small text-2">
            {artifact.contract.extraction_notes!.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      {cov && <ProvenanceDrawer cik={c.cik} covenantId={cov} periodEnd={quarter} onClose={closeDrawer} />}
    </div>
  );
}

function Agreements({ artifact }: { artifact: CovenantArtifact }) {
  const ags = artifact.contract.agreements;
  if (!ags.length) return null;
  return (
    <div className="card agreements-card">
      <div className="card-head"><h2>Credit agreements</h2><span className="small muted">{ags.length} filed</span></div>
      <div className="table-wrap">
      <table className="t">
        <tbody>
          {ags.map((a) => (
            <tr key={a.accession}>
              <td>
                <span className={`chip ${a.kind === "original" ? "chip-neutral" : "chip-indeterminate"}`} style={a.kind === "original" ? undefined : { color: "var(--accent)", background: "var(--accent-soft)" }}>
                  {a.kind === "original" ? "Original" : a.kind === "amendment" ? "Amendment" : "Restatement"}
                </span>
              </td>
              <td className="num small">{fmtDate(a.filed)}</td>
              <td className="small">
                <ExternalLink href={a.url} className="mono tiny">
                  {a.accession}
                </ExternalLink>
                {a.redacted && (
                  <span className="chip chip-refused" style={{ marginLeft: 6 }}>
                    Redacted
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function ThresholdSchedule({ tl }: { tl: TimelineResponse }) {
  if (!tl.thresholds.length) return null;
  return (
    <div style={{ padding: "0 18px 14px" }} className="row small">
      <span className="upper" style={{ marginRight: 4 }}>Threshold schedule</span>
      {tl.thresholds.map((t, i) => (
        <span key={i} className="chip chip-neutral num" title={`"${t.source.text}" (${t.source.accession}${t.source.section ? `, section ${t.source.section}` : ""})`}>
          {tl.covenant.direction === "max" ? "≤" : "≥"} {fmtRatio(t.value)}
          <span className="muted" style={{ fontWeight: 500 }}>
            {fmtDate(t.effective_from)} to {t.effective_to ? fmtDate(t.effective_to) : "maturity"}
          </span>
        </span>
      ))}
    </div>
  );
}

function QuarterTable({ tl, selected, onSelect }: { tl: TimelineResponse; selected: string | null; onSelect: (pe: string) => void }) {
  const rows = [...tl.quarters].sort((a, b) => (a.period_end < b.period_end ? 1 : -1));
  const disclosed = new Map(tl.disclosed.map((d) => [d.period_end, d]));
  return (
    <div className="table-wrap" style={{ borderTop: "1px solid var(--border)" }}>
      <table className="t">
        <thead>
          <tr>
            <th>Quarter</th>
            <th>Status</th>
            <th className="r">Computed ratio</th>
            <th className="r">Threshold</th>
            <th className="r">Headroom (worst to best)</th>
            <th className="r">Company reported</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((q) => {
            const d = disclosed.get(q.period_end);
            const refs = q.status === "refused" ? refusalsForQuarter(tl.refusals, tl.covenant.id, q.period_end) : [];
            return (
              <tr
                key={q.period_end}
                className={`clickable ${selected === q.period_end ? "selected" : ""}`}
                onClick={() => onSelect(q.period_end)}
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && onSelect(q.period_end)}
              >
                <td className="num nowrap">
                  <strong>{fmtQuarter(q.period_end)}</strong> <span className="muted tiny">{fmtDate(q.period_end)}</span>
                </td>
                <td>
                  <StatusChip status={q.status} />
                </td>
                <td className="r num">{fmtRatioRange(q.ratio_low, q.ratio_high, q.status)}</td>
                <td className="r num">{fmtRatio(q.threshold)}</td>
                <td className="r num">{fmtHeadroomRange(q.headroom_low, q.headroom_high, q.status)}</td>
                <td className="r num" style={{ color: d ? "var(--disclosed)" : undefined }}>
                  {d ? fmtRatio(d.reported_value) : <span className="muted">n/a</span>}
                </td>
                <td className="small text-2">
                  {q.status === "refused"
                    ? refs.length
                      ? refs.map((r) => `${reasonLabel(r.reason)}: ${r.detail}`).join(" ")
                      : "Not computed"
                    : q.missing.length
                      ? `Unmapped: ${q.missing.join(", ")}`
                      : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RefusalsPanel({ artifact, title = "Refusals" }: { artifact: CovenantArtifact; title?: string }) {
  const items: { r: Refusal; extra?: string }[] = [];
  const seen = new Set<string>();
  for (const r of [...artifact.contract.refusals, ...artifact.refusals]) {
    const k = `${r.scope}|${r.ref}|${r.reason}|${r.detail}`;
    if (seen.has(k)) continue;
    seen.add(k);
    items.push({ r });
  }
  for (const a of artifact.contract.agreements) {
    if (a.redacted && !items.some((i) => i.r.ref === a.accession)) {
      items.push({ r: { scope: "agreement", ref: a.accession, reason: "redacted", detail: "The filed agreement is redacted; covenant terms cannot be read from it." } });
    }
  }
  const refusedQuarters = artifact.quarters.filter((q) => q.status === "refused");
  const byReason = new Map<string, number>();
  for (const i of items) byReason.set(i.r.reason, (byReason.get(i.r.reason) ?? 0) + 1);

  return (
    <section className="card">
      <div className="card-head">
        <div className="stack" style={{ gap: 2 }}>
          <h2>{title}</h2>
          <span className="small muted">What could not be computed and why. Covenant Watch refuses rather than guesses.</span>
        </div>
        <div className="row">
          {[...byReason.entries()].map(([r, n]) => (
            <span key={r} className="chip chip-refused">
              {reasonLabel(r)} {n}
            </span>
          ))}
          {refusedQuarters.length > 0 && (
            <span className="chip chip-neutral num">
              {refusedQuarters.length} refused covenant quarter{refusedQuarters.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>
      {items.length === 0 ? (
        <div className="card-pad small muted">Nothing was refused. Every covenant quarter in this artifact was computed.</div>
      ) : (
        <table className="t">
          <thead>
            <tr>
              <th>Reason</th>
              <th>Scope</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map(({ r }, i) => (
              <tr key={i}>
                <td>
                  <span className="chip chip-refused">{reasonLabel(r.reason)}</span>
                </td>
                <td className="small num" style={{ whiteSpace: "nowrap" }}>{refusalScopeLabel(r)}</td>
                <td className="small text-2">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}


type Ev = { cik: string; date: string; kind: string; span: { url: string; text: string } };

const pct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%`;

/** Company header: identity on the left, the tightest covenant on the right, a hairline stat strip below. */
function CompanyHero({ source, artifact, summaries, events }: { source: Source; artifact: CovenantArtifact; summaries: CardSummary[]; events: Ev[] }) {
  const c = artifact.contract.company;
  const rels = summaries
    .map((s) => ({ s, rel: s.history?.filter((h) => h.rel !== null).at(-1)?.rel ?? null }))
    .filter((x) => x.rel !== null && x.s.status !== "refused") as { s: CardSummary; rel: number }[];
  const tight = rels.sort((a, b) => a.rel - b.rel)[0] ?? null;
  const computed = artifact.quarters.filter((q) => q.status !== "refused").length;
  const counts = summaries.reduce<Record<string, number>>((m, s) => ((m[s.status] = (m[s.status] ?? 0) + 1), m), {});
  return (
    <section className="co-hero">
      <div className="co-hero-main">
        <div className="row" style={{ gap: 8 }}>
          {c.ticker && <span className="chip chip-neutral">{c.ticker}</span>}
          {c.sic && <span className="chip chip-neutral">SIC {c.sic}</span>}
          <FixtureBadge source={source} />
        </div>
        <h1 className="ch-name">{c.name}</h1>
        <div className="ch-meta num">
          CIK {c.cik} · {artifact.contract.agreements.length} agreement{artifact.contract.agreements.length === 1 ? "" : "s"} · updated {fmtDate(artifact.generated_at)}
        </div>
      </div>
      <div className="co-hero-side">
        <div className="upper">Tightest covenant now</div>
        {tight ? (
          <>
            <div className="co-tight num" style={{ color: `var(--${tight.s.status})` }}>{pct(tight.rel)}</div>
            <div className="small text-2">
              worst-case headroom on <strong>{kindLabel(tight.s.kind)}</strong> vs a {tight.s.direction === "max" ? "≤" : "≥"} {fmtRatio(tight.s.threshold)} limit
            </div>
            <div className="row" style={{ gap: 8, marginTop: 4 }}>
              <StatusChip status={tight.s.status} />
              {tight.s.latest_period_end && <span className="tiny muted">{fmtQuarter(tight.s.latest_period_end)}</span>}
            </div>
          </>
        ) : (
          <div className="small muted" style={{ marginTop: 8 }}>No computable covenant yet. See the refusals below.</div>
        )}
      </div>
      <div className="co-strip">
        <div><div className="upper">Covenants</div><div className="v num">{summaries.length}</div></div>
        <div><div className="upper">Quarters computed</div><div className="v num">{computed}</div></div>
        <div>
          <div className="upper">Status now</div>
          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            {(["ok", "warning", "indeterminate", "breach", "refused"] as const).filter((k) => counts[k]).map((k) => <StatusChip key={k} status={k} title={`${counts[k]} covenant(s)`} />)}
          </div>
        </div>
        <div><div className="upper">Disclosed events</div><div className="v num">{events.length}</div></div>
        <div><div className="upper">Refusals</div><div className="v num">{artifact.refusals.length}</div></div>
      </div>
    </section>
  );
}

function EventsCard({ events }: { events: Ev[] }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Disclosed covenant events</h2><span className="small muted">from 8-K filings</span></div>
      {events.length === 0 ? (
        <div className="card-pad small muted">No waiver, default or loosening amendment disclosed for this company.</div>
      ) : (
        <ul className="ev-list">
          {events.map((e, i) => (
            <li key={i}>
              <span className="ev-dot" aria-hidden />
              <div className="stack" style={{ gap: 3 }}>
                <div className="row" style={{ gap: 8 }}>
                  <strong className="num">{fmtDate(e.date)}</strong>
                  <span className="chip chip-breach">{eventLabel(e.kind)}</span>
                </div>
                <span className="small text-2 ev-quote">&ldquo;{e.span.text}&rdquo;</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
