"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { dateToMs, eventLabel, fmtDate, fmtHeadroomRange, fmtPct, fmtQuarter, fmtRatio, fmtRatioRange, kindLabel } from "@/lib/format";
import type { CovenantArtifact, Source, TimelineResponse } from "@/lib/types";
import { RefusalsPanel } from "./CompanyView";
import ProvenanceDrawer from "./ProvenanceDrawer";
import Timeline, { TimelineLegend } from "./Timeline";
import { FixtureBadge, StatusChip } from "./ui";

interface Props {
  source: Source;
  initialStep: number;
  companiesCount: number;
  artifact: CovenantArtifact;
  featured: TimelineResponse | null;
  quarter: string | null;
  evalReport: Record<string, unknown> | null;
  evalSource: Source | null;
  refusalArtifact: CovenantArtifact;
}

const STEPS = [
  { title: "The problem", say: "Covenant breaches are the first domino of default, and investors can't see them coming." },
  { title: "Headroom before the event", say: "Headroom shrinks toward the threshold in the quarters before the real event, marked on the chart." },
  { title: "Every number has a source", say: "Click a quarter: the clause text and the filing line behind every input appear." },
  { title: "Proven against reality", say: "Computed ratios match what companies reported, and the signal fires before events far more often than for peers." },
  { title: "Honest refusals", say: "When an agreement is redacted or a filing is missing, it refuses and says why instead of guessing." },
];

export default function DemoView(p: Props) {
  const [step, setStep] = useState(p.initialStep);
  const [sel, setSel] = useState<string | null>(p.quarter);

  const go = useCallback((n: number) => {
    const s = Math.max(1, Math.min(STEPS.length, n));
    setStep(s);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("step", String(s));
      window.history.replaceState(null, "", u.toString());
    } catch {}
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA"].includes(t.tagName)) return;
      if (e.key === "ArrowRight" || e.key === "j") go(step + 1);
      if (e.key === "ArrowLeft" || e.key === "k") go(step - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, go]);

  const company = p.artifact.contract.company;
  const tl = p.featured;

  return (
    <div className="demo">
      <nav className="demo-rail" aria-label="Demo steps">
        <div className="row" style={{ padding: "0 4px 8px" }}>
          <span className="upper">Demo walkthrough</span>
          <FixtureBadge source={p.source} />
        </div>
        {STEPS.map((s, i) => (
          <button
            key={s.title}
            type="button"
            className={`demo-step ${i + 1 < step ? "done" : ""}`}
            aria-current={i + 1 === step ? "step" : undefined}
            onClick={() => go(i + 1)}
          >
            <span className="n">{i + 1}</span>
            <span className="stack" style={{ gap: 2 }}>
              <strong style={{ fontSize: 13.5 }}>{s.title}</strong>
              <span className="tiny muted">{s.say.length > 70 ? s.say.slice(0, 68).trimEnd() + "…" : s.say}</span>
            </span>
          </button>
        ))}
        <div className="tiny muted" style={{ padding: "8px 4px" }}>
          Use <kbd>&larr;</kbd> <kbd>&rarr;</kbd> to move between steps.
        </div>
      </nav>

      <div className="stack" style={{ gap: 18, minWidth: 0 }}>
        <div className="between">
          <div className="upper">
            Step {step} of {STEPS.length}
          </div>
          <div className="row">
            <button className="btn btn-sm" type="button" onClick={() => go(step - 1)} disabled={step === 1}>
              Back
            </button>
            <button className="btn btn-sm btn-primary" type="button" onClick={() => go(step + 1)} disabled={step === STEPS.length}>
              Next
            </button>
          </div>
        </div>

        {step !== 1 && <p className="say">{STEPS[step - 1].say}</p>}

        {step === 1 && <StepProblem p={p} />}
        {step === 2 && (tl ? <StepTimeline tl={tl} company={company.name} cik={company.cik} onPick={(q) => { setSel(q); go(3); }} /> : <NoCovenant />)}
        {step === 3 &&
          (tl ? (
            <div className="stack">
              <div className="card card-pad">
                <div className="chart-scroll">
                  <Timeline data={tl} selected={sel} onSelect={setSel} height={250} />
                </div>
              </div>
              <ProvenanceDrawer inline cik={company.cik} covenantId={tl.covenant.id} periodEnd={sel ?? tl.quarters[0]?.period_end ?? null} onClose={() => {}} />
            </div>
          ) : (
            <NoCovenant />
          ))}
        {step === 4 && <StepEval report={p.evalReport} source={p.evalSource} />}
        {step === 5 && <StepRefusal artifact={p.refusalArtifact} />}
      </div>
    </div>
  );
}

function NoCovenant() {
  return <div className="callout callout-muted">The demo company has no covenant timeline to show.</div>;
}

function StepProblem({ p }: { p: Props }) {
  const c = p.artifact.contract.company;
  return (
    <div className="stack" style={{ gap: 26, paddingTop: 12 }}>
      <p className="hero-quote">
        &ldquo;Covenant breaches are the first domino of default, and investors can&apos;t see them coming.&rdquo;
      </p>
      <p className="text-2" style={{ maxWidth: 680, fontSize: 15 }}>
        Loan covenants live in credit agreements buried in SEC exhibits, defined in pages of bespoke legal language. Covenant
        Watch reads the agreement, rebuilds each covenant exactly as defined, computes it every quarter from the company&apos;s
        own XBRL filings, and shows how close the company is to the line, with a source for every number.
      </p>
      <div className="card">
        <div className="stats" style={{ borderTop: "none" }}>
          <div className="stat"><div className="k">Companies covered</div><div className="v">{p.companiesCount}</div></div>
          <div className="stat"><div className="k">Demo company</div><div className="v" style={{ fontSize: 16 }}>{c.name}</div></div>
          <div className="stat"><div className="k">Covenants rebuilt</div><div className="v">{p.artifact.contract.covenants.length}</div></div>
          <div className="stat"><div className="k">Quarters computed</div><div className="v">{p.artifact.quarters.filter((q) => q.status !== "refused").length}</div></div>
        </div>
      </div>
    </div>
  );
}

function StepTimeline({ tl, company, cik, onPick }: { tl: TimelineResponse; company: string; cik: string; onPick: (q: string) => void }) {
  const firstEvent = [...tl.events].sort((a, b) => dateToMs(a.date) - dateToMs(b.date))[0];
  const cutoff = firstEvent ? dateToMs(firstEvent.date) : Infinity;
  const lead = tl.quarters.filter((q) => q.status !== "refused" && dateToMs(q.period_end) <= cutoff).slice(-4);
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div className="stack" style={{ gap: 2 }}>
            <h2>
              {company}: {kindLabel(tl.covenant.kind)}
            </h2>
            <span className="small muted">
              {firstEvent ? (
                <>
                  Real {eventLabel(firstEvent.kind).toLowerCase()} disclosed {fmtDate(firstEvent.date)} ({firstEvent.span.accession}).
                </>
              ) : (
                "No covenant event disclosed for this company."
              )}{" "}
              Click any quarter to see its provenance.
            </span>
          </div>
          <Link className="btn btn-sm" href={`/company/${encodeURIComponent(cik)}?cov=${encodeURIComponent(tl.covenant.id)}`}>
            Open company page
          </Link>
        </div>
        <div className="card-pad stack">
          <div className="chart-scroll">
            <Timeline data={tl} onSelect={onPick} emphasizeEvents height={380} />
          </div>
          <TimelineLegend direction={tl.covenant.direction} hasEvents={tl.events.length > 0} hasDisclosed={tl.disclosed.length > 0} hasAmendments={tl.agreements.some((a) => a.kind !== "original")} />
        </div>
      </div>
      {lead.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>{firstEvent ? `The ${lead.length} quarters before the ${eventLabel(firstEvent.kind).toLowerCase()}` : "Latest quarters"}</h3>
          </div>
          <table className="t">
            <thead>
              <tr>
                <th>Quarter</th>
                <th>Status</th>
                <th className="r">Ratio</th>
                <th className="r">Threshold</th>
                <th className="r">Headroom (worst to best)</th>
              </tr>
            </thead>
            <tbody>
              {lead.map((q) => (
                <tr key={q.period_end} className="clickable" onClick={() => onPick(q.period_end)}>
                  <td className="num"><strong>{fmtQuarter(q.period_end)}</strong></td>
                  <td><StatusChip status={q.status} /></td>
                  <td className="r num">{fmtRatioRange(q.ratio_low, q.ratio_high, q.status)}</td>
                  <td className="r num">{fmtRatio(q.threshold)}</td>
                  <td className="r num">{fmtHeadroomRange(q.headroom_low, q.headroom_high, q.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function num(o: unknown, k: string): number | null {
  if (o && typeof o === "object" && k in o) {
    const v = (o as Record<string, unknown>)[k];
    return typeof v === "number" ? v : null;
  }
  return null;
}

function StepEval({ report, source }: { report: Record<string, unknown> | null; source: Source | null }) {
  if (!report) return <div className="callout callout-muted">No eval report is available yet.</div>;
  const ra = report.ratio_accuracy;
  const ew = report.early_warning;
  const tiles: [string, string][] = [];
  const mae = num(ra, "median_abs_error");
  const within = num(ra, "pct_within_0_05");
  const inside = num(ra, "pct_inside_range") ?? num(ra, "pct_reported_inside_range");
  const n = num(ra, "n");
  const hit = num(ew, "hit_rate");
  const lead = num(ew, "median_lead_quarters");
  const fa = num(ew, "peer_false_alarm_rate");
  if (n !== null) tiles.push(["Reported ratios compared", n.toLocaleString()]);
  if (mae !== null) tiles.push(["Median absolute error", `${mae.toFixed(3)}x`]);
  if (within !== null) tiles.push(["Within ±0.05x", fmtPct(within)]);
  if (inside !== null) tiles.push(["Reported inside our range", fmtPct(inside)]);
  if (hit !== null) tiles.push(["Early-warning hit rate", fmtPct(hit)]);
  if (lead !== null) tiles.push(["Median lead", `${lead} quarter${lead === 1 ? "" : "s"}`]);
  if (fa !== null) tiles.push(["Peer false alarm rate", fmtPct(fa)]);
  return (
    <div className="stack">
      <div className="card" style={{ overflow: "hidden" }}>
        <div className="card-head">
          <div className="row">
            <h2>Evaluation summary</h2>
            <FixtureBadge source={source} />
          </div>
          <Link className="btn btn-sm" href="/eval">Full evaluation</Link>
        </div>
        {tiles.length ? (
          <div className="stats" style={{ borderTop: "none" }}>
            {tiles.map(([k, v]) => (
              <div key={k} className="stat"><div className="k">{k}</div><div className="v">{v}</div></div>
            ))}
          </div>
        ) : (
          <div className="card-pad small muted">The report has no ratio accuracy or early-warning figures yet.</div>
        )}
        {(hit !== null || fa !== null) && (
          <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
            {[["Event companies flagged before their event", hit, "var(--accent)"], ["Matched peers flagged", fa, "var(--refused)"]].map(([l, v, c]) => (
              <div key={l as string} className="bar-row" style={{ gridTemplateColumns: "280px 1fr 56px" }}>
                <span className="small">{l as string}</span>
                <span className="bar-track" style={{ height: 14 }}>
                  <span style={{ display: "block", height: "100%", width: `${((v as number | null) ?? 0) * 100}%`, background: c as string, borderRadius: 3 }} />
                </span>
                <span className="num" style={{ textAlign: "right" }}>{v === null ? "n/a" : fmtPct(v as number)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StepRefusal({ artifact }: { artifact: CovenantArtifact }) {
  const c = artifact.contract.company;
  const redacted = artifact.contract.agreements.filter((a) => a.redacted);
  return (
    <div className="stack">
      <div className="between">
        <div className="stack" style={{ gap: 2 }}>
          <h2>{c.name}</h2>
          <span className="small muted">
            {redacted.length
              ? `${redacted.length} redacted agreement${redacted.length === 1 ? "" : "s"} on file.`
              : "No redacted agreement in the current data; showing this company's refusals."}
          </span>
        </div>
        <Link className="btn btn-sm" href={`/company/${encodeURIComponent(c.cik)}`}>Open company page</Link>
      </div>
      <RefusalsPanel artifact={artifact} title="What we refused to compute" />
    </div>
  );
}
