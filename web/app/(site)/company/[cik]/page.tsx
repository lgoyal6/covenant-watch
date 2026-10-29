import type { Metadata } from "next";
import Link from "next/link";
import { api, settle } from "@/lib/api";
import type { TimelineResponse } from "@/lib/types";
import CompanyView from "@/components/CompanyView";
import CovenantBento from "@/components/CovenantBento";
import { ErrorState, SourceBanner } from "@/components/ui";

export const dynamic = "force-dynamic";

type Params = Promise<{ cik: string }>;
type Search = Promise<{ cov?: string; q?: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { cik } = await params;
  const r = await settle(api.company(cik));
  return { title: r.data ? r.data.artifact.contract.company.name : `CIK ${cik}` };
}

export default async function CompanyPage({ params, searchParams }: { params: Params; searchParams: Search }) {
  const { cik } = await params;
  const sp = await searchParams;
  const res = await settle(api.company(cik));

  if (res.error || !res.data) {
    return (
      <div className="page stack">
        <Link href="/companies" className="small">&lsaquo; All companies</Link>
        <ErrorState error={res.error!} title={res.error?.kind === "not_found" ? `No artifact for CIK ${cik}` : undefined} />
      </div>
    );
  }

  const { artifact, source } = res.data;
  const realCik = artifact.contract.company.cik;
  const [tls, ov] = await Promise.all([
    Promise.all(artifact.contract.covenants.map((c) => settle(api.timeline(realCik, c.id)))),
    settle(api.companyOverview(realCik)),
  ]);
  const timelines: Record<string, TimelineResponse | null> = {};
  const timelineErrors: Record<string, string> = {};
  artifact.contract.covenants.forEach((c, i) => {
    timelines[c.id] = tls[i].data;
    if (tls[i].error) timelineErrors[c.id] = tls[i].error!.message;
  });

  return (
    <>
      <SourceBanner source={source} />
      <div className="page stack" style={{ gap: 14 }}>
        <Link href="/companies" className="small">&lsaquo; All companies</Link>
        <CompanyView
          source={source}
          artifact={artifact}
          timelines={timelines}
          timelineErrors={timelineErrors}
          initialCov={sp.cov ?? null}
          initialQuarter={sp.q ?? null}
          overview={ov.data ? <CovenantBento o={ov.data} variant="company" /> : null}
        />
      </div>
    </>
  );
}
