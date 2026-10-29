import type { Metadata } from "next";
import { api, settle } from "@/lib/api";
import { DEMO_CIK, DEMO_COVENANT_ID, DEMO_PERIOD_END } from "@/lib/demo";
import { pickDemoQuarter, severity } from "@/lib/derive";
import type { CompanyListItem, CovenantArtifact, TimelineResponse } from "@/lib/types";
import DemoView from "@/components/DemoView";
import { EmptyState, ErrorState, SourceBanner } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Demo" };

function sameCik(a: string, b: string) {
  return a.replace(/^0+/, "") === b.replace(/^0+/, "");
}

export default async function DemoPage({ searchParams }: { searchParams: Promise<{ step?: string }> }) {
  const sp = await searchParams;
  const list = await settle(api.companies());
  if (list.error || !list.data) {
    return (
      <div className="page">
        <ErrorState error={list.error!} />
      </div>
    );
  }
  const companies = list.data.companies;
  if (!companies.length) {
    return (
      <div className="page card">
        <EmptyState title="No companies to demo">
          <p className="small">The API has no artifacts yet.</p>
        </EmptyState>
      </div>
    );
  }
  const pinned = DEMO_CIK;
  const demoItem = (pinned ? companies.find((c) => sameCik(c.cik, pinned)) : undefined) ?? companies[0];
  const [co, evalRes] = await Promise.all([settle(api.company(demoItem.cik)), settle(api.eval())]);
  if (co.error || !co.data) {
    return (
      <div className="page">
        <ErrorState error={co.error!} />
      </div>
    );
  }
  const artifact = co.data.artifact;
  const tls = await Promise.all(artifact.contract.covenants.map((c) => settle(api.timeline(artifact.contract.company.cik, c.id))));
  const timelines = tls.map((t) => t.data).filter((t): t is TimelineResponse => t !== null);

  // Covenant to feature: pinned, else the one with events and the most severe latest status.
  const score = (t: TimelineResponse) =>
    (t.events.length ? 100 : 0) + Math.max(0, ...t.quarters.map((q) => severity(q.status))) * 10 + t.disclosed.length;
  const featured =
    (DEMO_COVENANT_ID && timelines.find((t) => t.covenant.id === DEMO_COVENANT_ID)) ||
    [...timelines].sort((a, b) => score(b) - score(a))[0] ||
    null;
  const quarter = featured
    ? (DEMO_PERIOD_END && featured.quarters.find((q) => q.period_end === DEMO_PERIOD_END)) ||
      pickDemoQuarter(featured.quarters, featured.events)
    : null;

  // Refusal example: prefer another company with a redacted agreement or nothing computed.
  const refusalItem = pickRefusalCompany(companies, demoItem.cik);
  let refusalArtifact: CovenantArtifact = artifact;
  if (refusalItem && !sameCik(refusalItem.cik, demoItem.cik)) {
    const r = await settle(api.company(refusalItem.cik));
    if (r.data) refusalArtifact = r.data.artifact;
  }

  const source = list.data.source;
  const step = Math.max(1, Math.min(5, Number(sp.step) || 1));

  return (
    <>
      <SourceBanner source={source} />
      <div className="page">
        <DemoView
          source={source}
          initialStep={step}
          companiesCount={companies.length}
          artifact={artifact}
          featured={featured}
          quarter={quarter?.period_end ?? null}
          evalReport={evalRes.data?.report ?? null}
          evalSource={evalRes.data?.source ?? null}
          refusalArtifact={refusalArtifact}
        />
      </div>
    </>
  );
}

function pickRefusalCompany(cs: CompanyListItem[], demoCik: string): CompanyListItem | null {
  const others = cs.filter((c) => !sameCik(c.cik, demoCik));
  return (
    others.find((c) => c.covenants.length === 0 && c.refusals > 0) ||
    others.find((c) => c.covenants.length > 0 && c.covenants.every((v) => v.status === "refused")) ||
    others.find((c) => c.refusals > 0) ||
    null
  );
}
