import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtHeadroomRange, fmtRatio, fmtRatioRange, kindLabel, STATUS_LABEL } from "@/lib/format";
import { severity } from "@/lib/derive";
import type { CompanyListItem, Status } from "@/lib/types";
import { EmptyState, ErrorState, FixtureBadge, SourceBanner, StatusChip } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  const sp = await searchParams;
  const q = (Array.isArray(sp.q) ? sp.q[0] : sp.q)?.trim() ?? "";
  const res = await settle(api.companies(q || undefined));
  const companies = res.data ? sortCompanies(res.data.companies) : [];

  const counts = new Map<Status, number>();
  for (const c of companies) for (const cv of c.covenants) counts.set(cv.status, (counts.get(cv.status) ?? 0) + 1);

  return (
    <>
      <SourceBanner source={res.data?.source} />
      <div className="page stack" style={{ gap: 20 }}>
        <div className="stack" style={{ gap: 6, maxWidth: 760 }}>
          <h1>Covenant headroom, rebuilt from SEC filings</h1>
          <p className="text-2">
            Each covenant is reconstructed exactly as the credit agreement defines it, computed from the company&apos;s own
            XBRL facts, and shown as a range when inputs are uncertain. Every number links to its clause and filing.
          </p>
        </div>

        <form className="search" action="/" method="get" role="search">
          <input
            className="input"
            type="search"
            name="q"
            defaultValue={q}
            placeholder="Search by company name, ticker or CIK"
            aria-label="Search companies"
            autoComplete="off"
          />
          <button className="btn btn-primary" type="submit">
            Search
          </button>
          {q && (
            <Link className="btn" href="/">
              Clear
            </Link>
          )}
        </form>

        {res.error ? (
          <ErrorState error={res.error} />
        ) : (
          <section className="card">
            <div className="card-head">
              <div className="row">
                <h2>{q ? `Results for "${q}"` : "Companies"}</h2>
                <span className="muted small num">{companies.length}</span>
                <FixtureBadge source={res.data?.source} />
              </div>
              <div className="row">
                {(["breach", "indeterminate", "warning", "ok", "refused"] as Status[])
                  .filter((s) => counts.get(s))
                  .map((s) => (
                    <span key={s} className={`chip chip-${s} num`}>
                      {counts.get(s)} {STATUS_LABEL[s].toLowerCase()}
                    </span>
                  ))}
              </div>
            </div>
            {companies.length === 0 ? (
              <EmptyState title={q ? "No matching companies" : "No companies yet"}>
                <p className="small">
                  {q
                    ? "Try a ticker, part of the name, or a CIK."
                    : "The API returned no artifacts. Run the engine to populate data/artifacts/."}
                </p>
              </EmptyState>
            ) : (
              companies.map((c) => <CompanyRow key={c.cik} c={c} />)
            )}
          </section>
        )}
      </div>
    </>
  );
}

function worst(c: CompanyListItem): number {
  return Math.max(0, ...c.covenants.map((cv) => severity(cv.status)));
}

function sortCompanies(cs: CompanyListItem[]): CompanyListItem[] {
  return [...cs].sort((a, b) => worst(b) - worst(a) || a.name.localeCompare(b.name));
}

function CompanyRow({ c }: { c: CompanyListItem }) {
  return (
    <Link href={`/company/${encodeURIComponent(c.cik)}`} className="co-row">
      <div className="stack" style={{ gap: 3 }}>
        <span className="co-name">{c.name}</span>
        <span className="row tiny muted num" style={{ gap: 8 }}>
          {c.ticker && <span className="mono">{c.ticker}</span>}
          <span>CIK {c.cik}</span>
          {c.sic && <span>SIC {c.sic}</span>}
          {c.source === "fixture" && <span className="chip chip-fixture" style={{ height: 18 }}>FIXTURE</span>}
        </span>
      </div>
      <div className="cov-mini">
        {c.covenants.length === 0 ? (
          <span className="small muted">No covenants extracted</span>
        ) : (
          c.covenants.map((cv) => (
            <div key={cv.id} className="cov-mini-row">
              <span className="text-2">{kindLabel(cv.kind)}</span>
              <StatusChip status={cv.status} />
              <span className="num hide-sm text-2">
                {cv.status === "refused" ? (
                  <span className="muted">Not computed</span>
                ) : (
                  <>
                    {fmtRatioRange(cv.ratio_low, cv.ratio_high, cv.status)}
                    <span className="muted"> vs {cv.direction === "max" ? "≤" : "≥"} {fmtRatio(cv.threshold)}</span>
                    <span className="muted"> · headroom </span>
                    {fmtHeadroomRange(cv.headroom_low, cv.headroom_high, cv.status)}
                  </>
                )}
              </span>
            </div>
          ))
        )}
      </div>
      <div className="small muted num" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
        {c.refusals > 0 ? `${c.refusals} refusal${c.refusals === 1 ? "" : "s"}` : "No refusals"}
        <span aria-hidden style={{ marginLeft: 10 }}>&rsaquo;</span>
      </div>
    </Link>
  );
}
