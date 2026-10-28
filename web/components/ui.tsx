import type { ReactNode } from "react";
import { API_URL, type ApiError } from "@/lib/api";
import { STATUS_HELP, STATUS_LABEL } from "@/lib/format";
import type { Source, Status } from "@/lib/types";

export function StatusChip({ status, title }: { status: Status; title?: string }) {
  return (
    <span className={`chip chip-${status}`} title={title ?? STATUS_HELP[status]}>
      <span className="dot" aria-hidden />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function FixtureBadge({ source }: { source: Source | undefined | null }) {
  if (source !== "fixture") return null;
  return (
    <span className="chip chip-fixture" title="Synthetic development data, not a real company">
      FIXTURE DATA
    </span>
  );
}

/** Full-width banner shown on every page whose data came from fixtures/. */
export function SourceBanner({ source }: { source: Source | undefined | null }) {
  if (source !== "fixture") return null;
  return (
    <div className="fixture-banner" role="note">
      <div>
        <strong>FIXTURE DATA</strong>
        <span>
          The API is serving synthetic example data from fixtures/. Nothing on this page describes a real company.
          Real artifacts appear automatically once data/artifacts/ is populated.
        </span>
      </div>
    </div>
  );
}

export function ErrorState({ error, title }: { error: ApiError; title?: string }) {
  if (error.kind === "not_found") {
    return (
      <div className="card empty">
        <h3>{title ?? "Not found"}</h3>
        <p>{error.message}</p>
      </div>
    );
  }
  return (
    <div className="error-box stack" role="alert" style={{ gap: 8 }}>
      <h3>{title ?? (error.kind === "down" ? "The API is not reachable" : "The API returned an error")}</h3>
      <p className="text-2">{error.message}</p>
      {error.kind === "down" && (
        <p className="small text-2">
          Start it from the repo root with <code>uv run uvicorn api.main:app --port 8000</code>, or point the UI at another
          host with <code>NEXT_PUBLIC_API_URL</code> (currently <code>{API_URL}</code>). Then reload this page.
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function ExternalLink({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={className}>
      {children}
      <span aria-hidden style={{ marginLeft: 3, fontSize: "0.85em" }}>&#8599;</span>
    </a>
  );
}
