import type { Metadata } from "next";
import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtDate, reasonLabel } from "@/lib/format";
import { ErrorState, FixtureBadge } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Evaluation" };

type Num = number | null | undefined;
type Obj = Record<string, unknown>;
type RatioRow = { cik: string; period_end: string; reported: number; computed_low?: number | null; computed_high?: number | null; inside?: boolean; midpoint_abs_error?: number };
type EwRow = { cik: string; role: string; flagged: boolean; lead_quarters?: number | null; computable: boolean; event_kind?: string };
type Company = {
  cik: string; name: string; ticker?: string | null; covenants: number; quarters: number; status_counts: Record<string, number>;
  refusals: number; disclosed_compared: number; disclosed_inside_range: number; role?: string | null; flagged_before_event?: boolean | null; lead_quarters?: number | null;
};

const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: Num, d = 0) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
const STATUS = ["ok", "warning", "indeterminate", "breach", "refused"] as const;

function Headline({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="ev-head">
      <div className="upper">{label}</div>
      <div className="ev-big num" style={tone ? { color: tone } : undefined}>{value}</div>
      <div className="small muted">{sub}</div>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="ev-stat">
      <span className="muted">{k}</span>
      <span className="num">{v}</span>
    </div>
  );
}

/** Reported (y) vs computed (x). A point is a quarter; a horizontal bar is a computed range; the diagonal is a perfect match. */
function Scatter({ rows }: { rows: RatioRow[] }) {
  const pts = rows.filter((r) => n(r.computed_low) !== null || n(r.computed_high) !== null);
  if (pts.length === 0) return <div className="small muted">No computed quarter lines up with a reported ratio yet.</div>;
  const xs = pts.flatMap((r) => [r.computed_low, r.computed_high, r.reported].filter((v): v is number => n(v) !== null));
  const lo = Math.max(0, Math.floor(Math.min(...xs) * 2) / 2), hi = Math.ceil(Math.max(...xs) * 2) / 2 || 1;
  const W = 420, H = 300, P = 36;
  const sx = (v: number) => P + ((v - lo) / (hi - lo)) * (W - P - 10);
  const sy = (v: number) => H - P - ((v - lo) / (hi - lo)) * (H - P - 10);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  return (
    <svg className="ev-scatter" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Reported versus computed covenant ratios">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P} x2={W - 10} y1={sy(t)} y2={sy(t)} stroke="var(--border)" />
          <text x={P - 6} y={sy(t) + 3.5} textAnchor="end" className="ev-axis">{t.toFixed(1)}x</text>
          <text x={sx(t)} y={H - P + 16} textAnchor={t === hi ? "end" : "middle"} className="ev-axis">{t.toFixed(1)}x</text>
        </g>
      ))}
      <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} stroke="var(--muted)" strokeDasharray="4 4" />
      {pts.map((r, i) => {
        const a = n(r.computed_low) ?? n(r.computed_high)!, b = n(r.computed_high) ?? a;
        const good = (r.midpoint_abs_error ?? (r.inside ? 0 : 1)) <= 0.05 || r.inside;
        const c = good ? "var(--ok)" : "var(--warning)";
        return (
          <g key={i}>
            {b - a > 0.001 && <line x1={sx(a)} x2={sx(b)} y1={sy(r.reported)} y2={sy(r.reported)} stroke={c} strokeOpacity=".55" strokeWidth="3" strokeLinecap="round" />}
            <circle cx={sx((a + b) / 2)} cy={sy(r.reported)} r="3.6" fill={c} fillOpacity=".85">
              <title>{`${r.period_end}: reported ${r.reported.toFixed(2)}x, computed ${a.toFixed(2)}${b !== a ? `–${b.toFixed(2)}` : ""}x`}</title>
            </circle>
          </g>
        );
      })}
      <text x={W - 10} y={H - P - 8} textAnchor="end" className="ev-axis">computed →</text>
      <text x={P + 8} y={26} className="ev-axis">↑ reported</text>
    </svg>
  );
}

/** How many quarters ahead each disclosed event was flagged, plus the ones we missed. */
function LeadChart({ rows }: { rows: EwRow[] }) {
  const ev = rows.filter((r) => r.role === "event" && r.computable);
  if (!ev.length) return <div className="small muted">No scored events yet.</div>;
  const buckets = [
    { k: "Missed", v: ev.filter((r) => !r.flagged).length, c: "var(--breach)" },
    { k: "1 qtr", v: ev.filter((r) => r.flagged && (r.lead_quarters ?? 0) <= 1).length, c: "var(--accent)" },
    { k: "2 qtrs", v: ev.filter((r) => r.flagged && r.lead_quarters === 2).length, c: "var(--accent)" },
    { k: "3 qtrs", v: ev.filter((r) => r.flagged && r.lead_quarters === 3).length, c: "var(--accent)" },
    { k: "4+ qtrs", v: ev.filter((r) => r.flagged && (r.lead_quarters ?? 0) >= 4).length, c: "var(--accent)" },
  ];
  const max = Math.max(1, ...buckets.map((b) => b.v));
  return (
    <div className="ev-bars">
      {buckets.map((b) => (
        <div key={b.k} className="ev-bar">
          <div className="ev-bar-track"><div className="ev-bar-fill" style={{ height: `${(b.v / max) * 100}%`, background: b.c }} /></div>
          <div className="num" style={{ fontWeight: 600 }}>{b.v}</div>
          <div className="tiny muted">{b.k}</div>
        </div>
      ))}
    </div>
  );
}

function StatusMix({ counts }: { counts: Record<string, number> }) {
  const total = STATUS.reduce((a, s) => a + (counts[s] ?? 0), 0) || 1;
  return (
    <div className="ev-mix" title={STATUS.filter((s) => counts[s]).map((s) => `${s}: ${counts[s]}`).join(", ")}>
      {STATUS.map((s) => (counts[s] ? <i key={s} style={{ width: `${(counts[s] / total) * 100}%`, background: `var(--${s})` }} /> : null))}
    </div>
  );
}

export default async function EvalPage() {
  const res = await settle(api.eval());
  if (res.error) return <div className="page"><ErrorState error={res.error} /></div>;
  const { report, source } = res.data;
  const detail = ((res.data as unknown as { detail?: { ratio_rows?: RatioRow[]; early_warning_rows?: EwRow[] } }).detail) ?? {};
  const rep = (report ?? {}) as Obj;
  const ra = (rep.ratio_accuracy ?? {}) as Obj;
  const ew = (rep.early_warning ?? {}) as Obj;
  const ex = (rep.extraction ?? {}) as Obj;
  const refusals = Object.entries((rep.refusals ?? {}) as Record<string, number>).sort((a, b) => b[1] - a[1]);
  const refMax = Math.max(1, ...refusals.map(([, v]) => v));
  const companies = ((rep.per_company ?? []) as Company[]).slice().sort(
    (a, b) => Number(b.role === "event") - Number(a.role === "event") || (b.status_counts.breach ?? 0) - (a.status_counts.breach ?? 0),
  );
  const labeled = n(ex.agreements_labeled) ?? 0;
  const fields = Object.entries(ex).filter(([, v]) => typeof v === "object" && v !== null) as [string, { precision: Num; recall: Num }][];

  return (
    <div className="page stack" style={{ gap: 22 }}>
      <div className="stack" style={{ gap: 8 }}>
        <div className="row"><h1>Evaluation</h1><FixtureBadge source={source} /></div>
        <p className="text-2" style={{ maxWidth: 760 }}>
          Proven two ways: our computed ratios against the ratios companies reported in their own filings, and whether headroom fell before
          real waivers, defaults and loosening amendments, compared with matched peers that had none.
        </p>
        {typeof rep.generated_at === "string" && <span className="tiny muted">Generated {fmtDate(rep.generated_at)}</span>}
      </div>

      <section className="ev-headlines">
        <Headline label="Within ±0.05x of reported" value={pct(n(ra.pct_within_0_05))} sub={`${n(ra.n) ?? 0} reported ratios compared`} tone="var(--ok)" />
        <Headline label="Flagged before the event" value={pct(n(ew.hit_rate))} sub={`${n(ew.events_scored) ?? 0} events · median ${n(ew.median_lead_quarters) ?? "n/a"} quarters ahead`} tone="var(--accent)" />
        <Headline label="Peer false alarms" value={pct(n(ew.peer_false_alarm_rate))} sub={`${n(ew.peers_scored) ?? 0} matched peers with no event`} tone="var(--warning)" />
        <Headline label="Limit read correctly" value={pct(n(ra.threshold_agreement))} sub={`extracted limit = limit the company stated (${n(ra.threshold_n) ?? 0})`} />
      </section>

      <section className="card">
        <div className="card-head"><div className="stack" style={{ gap: 2 }}><h2>Ratio accuracy</h2><span className="small muted">Each point is a quarter where the company reported its own covenant ratio. On the diagonal means we matched it; a bar is our computed range.</span></div></div>
        <div className="ev-split">
          <Scatter rows={detail.ratio_rows ?? []} />
          <div className="ev-stats">
            <Stat k="Reported ratios compared" v={String(n(ra.n) ?? 0)} />
            <Stat k="Median absolute error" v={n(ra.median_abs_error) == null ? "n/a" : `${n(ra.median_abs_error)!.toFixed(3)}x`} />
            <Stat k="Within ±0.05x" v={pct(n(ra.pct_within_0_05), 1)} />
            <Stat k="Within ±0.25x" v={pct(n(ra.pct_within_0_25), 1)} />
            <Stat k="Inside our computed range" v={pct(n(ra.pct_inside_range), 1)} />
            <Stat k="Limit matches the company's" v={pct(n(ra.threshold_agreement), 1)} />
            <Stat k="Not comparable (refused or no quarter)" v={String(n(ra.refused_or_unmatched) ?? 0)} />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><div className="stack" style={{ gap: 2 }}><h2>Early warning</h2><span className="small muted">A company is flagged when any quarter in the year before its first disclosed event shows warning or breach in the worst case.</span></div></div>
        <div className="ev-split">
          <div>
            <div className="upper" style={{ marginBottom: 10 }}>Lead time before the event</div>
            <LeadChart rows={detail.early_warning_rows ?? []} />
          </div>
          <div className="stack" style={{ gap: 18, justifyContent: "center" }}>
            {[
              ["Event companies flagged", n(ew.hit_rate), "var(--accent)"],
              ["Matched peers flagged (false alarms)", n(ew.peer_false_alarm_rate), "var(--warning)"],
            ].map(([k, v, c]) => (
              <div key={k as string}>
                <div className="between small"><span>{k as string}</span><span className="num" style={{ fontWeight: 600 }}>{pct(v as Num)}</span></div>
                <div className="bar-track" style={{ marginTop: 6 }}><div className="bar-fill" style={{ width: `${((v as number) ?? 0) * 100}%`, background: c as string }} /></div>
              </div>
            ))}
            <div className="ev-stats">
              <Stat k="Events scored" v={String(n(ew.events_scored) ?? 0)} />
              <Stat k="Median lead" v={n(ew.median_lead_quarters) == null ? "n/a" : `${n(ew.median_lead_quarters)} quarters`} />
              <Stat k="Peers scored" v={String(n(ew.peers_scored) ?? 0)} />
            </div>
          </div>
        </div>
      </section>

      <div className="co-pair">
        <section className="card">
          <div className="card-head"><div className="stack" style={{ gap: 2 }}><h2>Extraction accuracy</h2><span className="small muted">Contract fields against hand-verified gold labels.</span></div></div>
          {labeled === 0 ? (
            <div className="card-pad small text-2">
              No verified gold labels yet. Twenty agreements are drafted with an exact quote for every field and are waiting for a person to check them
              (<code>validation/labels</code>). Precision and recall appear here once they are signed off.
            </div>
          ) : (
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>Field</th><th className="r">Precision</th><th className="r">Recall</th></tr></thead>
                <tbody>
                  {fields.map(([k, v]) => (
                    <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="r num">{pct(v.precision, 1)}</td><td className="r num">{pct(v.recall, 1)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card">
          <div className="card-head"><div className="stack" style={{ gap: 2 }}><h2>Refusals</h2><span className="small muted">What we declined to compute, by reason. Nothing is filled in.</span></div></div>
          <div className="card-pad stack" style={{ gap: 4 }}>
            {refusals.length === 0 ? <span className="small muted">None.</span> : refusals.map(([k, v]) => (
              <div key={k} className="bar-row">
                <span>{k === "refused_quarters" ? "Quarters refused" : reasonLabel(k)}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / refMax) * 100}%` }} /></div>
                <span className="num r">{v}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><div className="stack" style={{ gap: 2 }}><h2>By company</h2><span className="small muted">Companies with a disclosed event first, then by quarters in breach.</span></div><span className="small muted">{companies.length} companies</span></div>
        <div className="table-wrap">
          <table className="t ev-table">
            <thead>
              <tr><th>Company</th><th className="r">Covenants</th><th className="r">Quarters</th><th>Status mix</th><th className="r">Reported ratios matched</th><th>Event</th><th className="r">Refusals</th></tr>
            </thead>
            <tbody>
              {companies.map((c) => (
                <tr key={c.cik}>
                  <td><Link href={`/company/${c.cik}`}>{c.name}</Link><div className="tiny muted">{c.ticker ? `${c.ticker} · ` : ""}CIK {c.cik}</div></td>
                  <td className="r num">{c.covenants}</td>
                  <td className="r num">{c.quarters}</td>
                  <td><StatusMix counts={c.status_counts} /></td>
                  <td className="r num">{c.disclosed_compared ? `${c.disclosed_inside_range} of ${c.disclosed_compared}` : <span className="muted">none reported</span>}</td>
                  <td>
                    {c.role === "event" ? (
                      c.flagged_before_event ? <span className="chip chip-ok">Flagged {c.lead_quarters} qtr{c.lead_quarters === 1 ? "" : "s"} ahead</span> : <span className="chip chip-breach">Missed</span>
                    ) : c.role === "peer" ? (
                      c.flagged_before_event ? <span className="chip chip-warning">Peer, false alarm</span> : <span className="chip chip-neutral">Peer, quiet</span>
                    ) : <span className="muted small">none</span>}
                  </td>
                  <td className="r num">{c.refusals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
