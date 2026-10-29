import type {
  CompaniesResponse,
  CompanyResponse,
  EvalResponse,
  ProvenanceResponse,
  TimelineResponse,
} from "./types";

/** Base URL of the FastAPI backend. Server code may override with API_URL (e.g. inside a container). */
export const API_URL = (
  (typeof window === "undefined" ? process.env.API_URL : undefined) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
    public kind: "down" | "not_found" | "http",
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", headers: { accept: "application/json" } });
  } catch {
    throw new ApiError(`Could not reach the Covenant Watch API at ${API_URL}.`, null, "down");
  }
  if (res.status === 404) {
    let detail = "Not found.";
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(detail, 404, "not_found");
  }
  if (!res.ok) throw new ApiError(`API returned HTTP ${res.status} for ${path}.`, res.status, "http");
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  companies: (q?: string) => get<CompaniesResponse>(`/companies${q ? `?q=${enc(q)}` : ""}`),
  company: (cik: string) => get<CompanyResponse>(`/companies/${enc(cik)}`),
  timeline: (cik: string, covId: string) =>
    get<TimelineResponse>(`/companies/${enc(cik)}/covenants/${enc(covId)}/timeline`),
  provenance: (cik: string, covId: string, periodEnd: string) =>
    get<ProvenanceResponse>(`/provenance/${enc(cik)}/${enc(covId)}/${enc(periodEnd)}`),
  eval: () => get<EvalResponse>(`/eval`),
};

/** Settle a promise into {data} | {error} so pages can render partial failures. */
export async function settle<T>(p: Promise<T>): Promise<{ data: T; error: null } | { data: null; error: ApiError }> {
  try {
    return { data: await p, error: null };
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : String(e), null, "http");
    return { data: null, error: err };
  }
}
