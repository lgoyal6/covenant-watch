import type { Metadata } from "next";
import { api, settle } from "@/lib/api";
import CovenantBento from "@/components/CovenantBento";
import { ErrorState, FixtureBadge } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const r = await settle(api.overview());
  if (r.error) return <div className="page"><ErrorState error={r.error} title="Could not load the overview" /></div>;
  const o = r.data;
  return (
    <>
      <div className="page">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <h1 style={{ margin: 0, fontSize: 26, letterSpacing: "-0.02em" }}>Covenant overview</h1>
          <FixtureBadge source={o.source} />
          <span className="muted" style={{ fontSize: 13 }}>Every covenant we rebuilt, across every company, from SEC filings.</span>
        </div>
        <CovenantBento o={o} />
      </div>
    </>
  );
}
