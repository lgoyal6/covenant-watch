import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { api, settle } from "@/lib/api";
import { fmtDate, humanize, reasonLabel, REASON_LABEL } from "@/lib/format";
import { EmptyState, ErrorState, FixtureBadge, SourceBanner } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Evaluation" };

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = { [k: string]: Json };

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: unknown) => v === null || ["number", "string", "boolean"].includes(typeof v);

const KEY_LABELS: Record<string, string> = {
  n: "Pairs compared",
  median_abs_error: "Median absolute error",
  mean_abs_error: "Mean absolute error",
  pct_within_0_05: "Within ±0.05x",
  pct_within_0_10: "Within ±0.10x",
  pct_inside_range: "Reported inside computed range",
  pct_reported_inside_range: "Reported inside computed range",
  events: "Events",
  hit_rate: "Hit rate",
  median_lead_quarters: "Median lead (quarters)",
  peer_false_alarm_rate: "Peer false alarm rate",
  false_alarm_rate: "False alarm rate",
  covenant_kind: "Covenant kind",
  threshold_value: "Threshold value",
  term_structure: "Term structure",
  cik: "CIK",
  f1: "F1",
};

const SECTION_META: Record<string, { title: string; blurb: string }> = {
  extraction: { title: "Extraction accuracy", blurb: "Field-level precision and recall of contract extraction against hand-labeled agreements." },
  ratio_accuracy: { title: "Ratio accuracy", blurb: "Computed covenant ratios compared with the ratios companies reported in their own 10-K and 10-Q filings." },
  early_warning: { title: "Early warning", blurb: "Did headroom shrink before a real waiver, amendment or default, and how often did matched peers trip the same signal?" },
  refusals: { title: "Refusals by reason", blurb: "What the pipeline declined to compute, grouped by reason." },
  per_company: { title: "Per company", blurb: "Breakdown for each company in the universe." },
};

function label(k: string): string {
  if (KEY_LABELS[k]) return KEY_LABELS[k];
  if (REASON_LABEL[k]) return REASON_LABEL[k];
  return humanize(k.replace(/^pct_/, "% ").replace(/_pct$/, " %"));
}

function isRateKey(k: string): boolean {
  return /(precision|recall|rate|pct|accuracy|f1|share|within|inside|coverage)/i.test(k);
}

function fmtVal(k: string, v: Json): ReactNode {
  if (v === null || v === undefined) return <span className="muted">n/a</span>;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (isRateKey(k) && v >= 0 && v <= 1) return `${(v * 100).toFixed(v === 1 || v === 0 ? 0 : 1)}%`;
    if (Number.isInteger(v)) return v.toLocaleString("en-US");
    return v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) < 1 ? 4 : 2 });
  }
  if (typeof v === "string") return /^\d{4}-\d{2}-\d{2}/.test(v) && v.length <= 25 ? fmtDate(v) : v;
  if (Array.isArray(v)) return v.every(isScalar) ? v.map(String).join(", ") : `${v.length} items`;
  return <code className="tiny">{JSON.stringify(v)}</code>;
}

function Cell({ k, v }: { k: string; v: Json }) {
  if (typeof v === "number" && isRateKey(k) && v >= 0 && v <= 1) {
    return (
      <span className="num" style={{ whiteSpace: "nowrap" }}>
        <span className="pbar"><i style={{ width: `${v * 100}%` }} /></span>
        {fmtVal(k, v)}
      </span>
    );
  }
  return <span className="num">{fmtVal(k, v)}</span>;
}

function Stats({ obj }: { obj: Obj }) {
  const entries = Object.entries(obj).filter(([, v]) => isScalar(v));
  if (!entries.length) return null;
  return (
    <div className="stats">
      {entries.map(([k, v]) => (
        <div key={k} className="stat">
          <div className="k">{label(k)}</div>
          <div className="v">{fmtVal(k, v)}</div>
        </div>
      ))}
    </div>
  );
}

function ObjTable({ rows, rowKeyLabel = "Group" }: { rows: [string, Obj][]; rowKeyLabel?: string }) {
  const cols = [...new Set(rows.flatMap(([, o]) => Object.keys(o)))];
  return (
    <div className="table-wrap">
      <table className="t">
        <thead>
          <tr>
            <th>{rowKeyLabel}</th>
            {cols.map((c) => (
              <th key={c} className="r">{label(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, o]) => (
            <tr key={k}>
              <td><strong>{label(k)}</strong></td>
              {cols.map((c) => (
                <td key={c} className="r"><Cell k={c} v={o[c] ?? null} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListTable({ items }: { items: Json[] }) {
  const objs = items.filter(isObj);
  if (!objs.length) return <div className="card-pad small">{items.map(String).join(", ") || "None"}</div>;
  const cols = [...new Set(objs.flatMap((o) => Object.keys(o)))];
  const nameCol = cols.includes("name") ? "name" : null;
  return (
    <div className="table-wrap">
      <table className="t">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} className={typeof objs[0][c] === "number" ? "r" : undefined}>{label(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {objs.map((o, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = o[c] ?? null;
                const cik = typeof o.cik === "string" ? o.cik : null;
                if (c === nameCol && cik && typeof v === "string") {
                  return <td key={c}><Link href={`/company/${encodeURIComponent(cik)}`}>{v}</Link></td>;
                }
                return (
                  <td key={c} className={typeof v === "number" ? "r" : c === "cik" ? "mono small" : undefined}>
                    {v === "FIXTURE" ? <span className="chip chip-fixture">FIXTURE</span> : <Cell k={c} v={v} />}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RefusalBars({ obj }: { obj: Obj }) {
  const entries = Object.entries(obj)
    .filter(([, v]) => typeof v === "number")
    .sort((a, b) => (b[1] as number) - (a[1] as number)) as [string, number][];
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <div className="card-pad small muted">No refusals recorded.</div>;
  return (
    <div className="card-pad">
      {entries.map(([k, v]) => (
        <div key={k} className="bar-row">
          <span>{reasonLabel(k)}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(v / max) * 100}%`, display: "block" }} /></span>
          <span className="num r" style={{ textAlign: "right" }}>{v.toLocaleString()}</span>
        </div>
      ))}
      <div className="small muted num" style={{ marginTop: 8 }}>{total.toLocaleString()} total</div>
      <Nested obj={obj} />
    </div>
  );
}

/** Early-warning comparison: event companies flagged vs peers flagged. */
function HitVsPeers({ obj }: { obj: Obj }) {
  const hit = typeof obj.hit_rate === "number" ? obj.hit_rate : null;
  const fa = typeof obj.peer_false_alarm_rate === "number" ? obj.peer_false_alarm_rate : typeof obj.false_alarm_rate === "number" ? obj.false_alarm_rate : null;
  if (hit === null && fa === null) return null;
  const rows: [string, number | null, string][] = [
    ["Event companies flagged before their event", hit, "var(--accent)"],
    ["Matched peers flagged (false alarms)", fa, "var(--refused)"],
  ];
  return (
    <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
      <div className="upper" style={{ marginBottom: 8 }}>Signal vs peers</div>
      {rows.map(([l, v, c]) => (
        <div key={l} className="bar-row" style={{ gridTemplateColumns: "300px 1fr 56px" }}>
          <span className="small">{l}</span>
          <span className="bar-track" style={{ height: 14 }}>
            <span style={{ display: "block", height: "100%", width: `${(v ?? 0) * 100}%`, background: c, borderRadius: 3 }} />
          </span>
          <span className="num" style={{ textAlign: "right" }}>{v === null ? "n/a" : `${(v * 100).toFixed(0)}%`}</span>
        </div>
      ))}
    </div>
  );
}

/** Non-scalar children of a mixed object, rendered recursively. */
function Nested({ obj }: { obj: Obj }) {
  const rest = Object.entries(obj).filter(([, v]) => !isScalar(v));
  if (!rest.length) return null;
  return (
    <div className="stack" style={{ gap: 0 }}>
      {rest.map(([k, v]) => (
        <div key={k} style={{ borderTop: "1px solid var(--border)" }}>
          <div className="upper" style={{ padding: "12px 18px 4px" }}>{label(k)}</div>
          <Generic value={v} />
        </div>
      ))}
    </div>
  );
}

function Generic({ value, rowKeyLabel }: { value: Json; rowKeyLabel?: string }) {
  if (Array.isArray(value)) return value.length ? <ListTable items={value} /> : <div className="card-pad small muted">None.</div>;
  if (isObj(value)) {
    const entries = Object.entries(value);
    if (!entries.length) return <div className="card-pad small muted">No data yet.</div>;
    if (entries.every(([, v]) => isObj(v))) return <ObjTable rows={entries as [string, Obj][]} rowKeyLabel={rowKeyLabel} />;
    return (
      <>
        <Stats obj={value} />
        <Nested obj={value} />
      </>
    );
  }
  return <div className="card-pad">{fmtVal("", value)}</div>;
}

function Section({ k, value }: { k: string; value: Json }) {
  const meta = SECTION_META[k] ?? { title: label(k), blurb: "" };
  let body: ReactNode;
  if (k === "refusals" && isObj(value)) body = <RefusalBars obj={value} />;
  else if (k === "early_warning" && isObj(value))
    body = (
      <>
        <Generic value={value} />
        <HitVsPeers obj={value} />
      </>
    );
  else body = <Generic value={value} rowKeyLabel={k === "extraction" ? "Field" : undefined} />;
  return (
    <section className="card" style={{ overflow: "hidden" }}>
      <div className="card-head">
        <div className="stack" style={{ gap: 2 }}>
          <h2>{meta.title}</h2>
          {meta.blurb && <span className="small muted">{meta.blurb}</span>}
        </div>
      </div>
      {value === null || value === undefined ? <div className="card-pad small muted">Not in this report yet.</div> : body}
    </section>
  );
}

const ORDER = ["ratio_accuracy", "early_warning", "extraction", "refusals", "per_company"];
const SKIP = new Set(["schema_version", "generated_at", "source"]);

export default async function EvalPage() {
  const res = await settle(api.eval());
  const report = (res.data?.report ?? null) as Obj | null;
  const keys = report
    ? [...ORDER, ...Object.keys(report).filter((k) => !ORDER.includes(k) && !SKIP.has(k))]
    : [];

  return (
    <>
      <SourceBanner source={res.data?.source} />
      <div className="page stack" style={{ gap: 18 }}>
        <div className="between">
          <div className="stack" style={{ gap: 4 }}>
            <div className="row">
              <h1>Evaluation</h1>
              <FixtureBadge source={res.data?.source} />
            </div>
            <p className="text-2 small">
              Proven two ways: computed ratios vs what companies themselves reported, and headroom falling before real
              covenant events compared with matched peers that had none.
            </p>
          </div>
          {report && (
            <span className="small muted num">
              {typeof report.schema_version === "string" && `Schema ${report.schema_version} · `}
              {typeof report.generated_at === "string" && `Generated ${fmtDate(report.generated_at)}`}
            </span>
          )}
        </div>
        {res.error ? (
          <ErrorState error={res.error} />
        ) : !report ? (
          <div className="card">
            <EmptyState title="No eval report yet">
              <p className="small">Run the validation scorer to write data/eval/report.json.</p>
            </EmptyState>
          </div>
        ) : (
          keys.map((k) => <Section key={k} k={k} value={report[k] ?? null} />)
        )}
      </div>
    </>
  );
}
