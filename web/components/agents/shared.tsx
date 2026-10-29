"use client";

import type { ReactNode } from "react";
import { API_URL } from "@/lib/api";

export type Step = { tool: string; input: Record<string, unknown>; ok: boolean };
export type AgentReply = { answer: string; steps: Step[]; model: string };

const TOOL_LABEL: Record<string, string> = {
  search_companies: "Searched companies",
  portfolio_overview: "Read the portfolio",
  covenant_timeline: "Read a covenant timeline",
  quarter_provenance: "Traced a quarter to its clause and filings",
  company_refusals: "Checked refusals",
  covenant_breakeven: "Computed breakevens",
  stress_test: "Ran a stress scenario",
};

export async function callAgent(path: string, body: unknown): Promise<AgentReply> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}.`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Agent returned HTTP ${res.status}.`);
  return data as AgentReply;
}

export function Steps({ steps }: { steps: Step[] }) {
  if (!steps.length) return null;
  return (
    <ol className="ag-steps">
      {steps.map((s, i) => (
        <li key={i} className={s.ok ? "" : "bad"}>
          <span className="ag-step-n">{i + 1}</span>
          <span>{TOOL_LABEL[s.tool] ?? s.tool}</span>
          <code>{Object.values(s.input).join(" · ") || "all"}</code>
        </li>
      ))}
    </ol>
  );
}

/** Small markdown subset the agents write: ## / ### headings, "- " bullets, **bold**. */
export function Markdown({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p));
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`u${out.length}`}>{list}</ul>);
    list = [];
  };
  text.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (t.startsWith("- ") || t.startsWith("* ")) return void list.push(<li key={i}>{inline(t.slice(2))}</li>);
    flush();
    if (t.startsWith("### ")) out.push(<h4 key={i}>{inline(t.slice(4))}</h4>);
    else if (t.startsWith("## ")) out.push(<h3 key={i}>{inline(t.slice(3))}</h3>);
    else if (t) out.push(<p key={i}>{inline(t)}</p>);
  });
  flush();
  return <div className="ag-md">{out}</div>;
}
