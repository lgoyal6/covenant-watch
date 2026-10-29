"use client";

import { useState } from "react";
import { callAgent, Markdown, Steps, type AgentReply } from "./shared";

const QUESTIONS = ["How close is this company to breaking a covenant?", "What drives the leverage ratio this quarter?", "Why is any quarter shown as a range?"];
const SCENARIOS = [
  { label: "Standard scenarios", value: "" },
  { label: "EBITDA −25%", value: "earnings -25%" },
  { label: "Rates up: interest +50%", value: "interest or debt costs +50%, earnings unchanged" },
  { label: "Recession: EBITDA −40%, debt +20%", value: "earnings -40% and debt or interest +20%" },
];

/** The company's agent: ask about its covenants, or stress-test them through the engine. */
export default function CompanyAgent({ cik, company }: { cik: string; company: string }) {
  const [mode, setMode] = useState<"ask" | "stress">("ask");
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [r, setR] = useState<AgentReply | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (label: string, path: string, body: unknown) => {
    setBusy(true);
    setErr(null);
    setR(null);
    setAsked(label);
    try {
      setR(await callAgent(path, body));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const ask = (q: string) => run(q, "/agent/ask", { question: q, cik, history: [] });
  const stress = (label: string, scenario: string) => run(label, "/agent/stress", { cik, scenario: scenario || null });

  return (
    <section className="card ag-company">
      <div className="card-head">
        <div className="row" style={{ gap: 12 }}>
          <span className="ag-orb" aria-hidden />
          <div className="stack" style={{ gap: 2 }}>
            <h2>{company} agent</h2>
            <span className="small muted">Claude reads this company&rsquo;s covenants, timelines and filings through tools, or stress-tests them through the engine. Every step is shown.</span>
          </div>
        </div>
        <div className="ag-seg" role="tablist" aria-label="Agent mode">
          <button type="button" role="tab" aria-pressed={mode === "ask"} onClick={() => setMode("ask")}>Ask</button>
          <button type="button" role="tab" aria-pressed={mode === "stress"} onClick={() => setMode("stress")}>Stress test</button>
        </div>
      </div>
      <div className="ag-brief-body stack" style={{ gap: 14 }}>
        {mode === "ask" ? (
          <>
            <div className="row" style={{ gap: 8 }}>
              {QUESTIONS.map((q) => (
                <button key={q} type="button" className="btn btn-sm" disabled={busy} onClick={() => ask(q)}>{q}</button>
              ))}
            </div>
            <form className="row" style={{ gap: 8 }} onSubmit={(e) => (e.preventDefault(), text.trim() && ask(text.trim()))}>
              <input className="input" style={{ height: 38, fontSize: 13.5 }} value={text} onChange={(e) => setText(e.target.value)} placeholder={`Ask anything about ${company}'s covenants`} />
              <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>Ask</button>
            </form>
          </>
        ) : (
          <>
            <div className="row" style={{ gap: 8 }}>
              {SCENARIOS.map((s) => (
                <button key={s.label} type="button" className="btn btn-sm" disabled={busy} onClick={() => stress(s.label, s.value)}>{s.label}</button>
              ))}
            </div>
            <form className="row" style={{ gap: 8 }} onSubmit={(e) => (e.preventDefault(), text.trim() && stress(text.trim(), text.trim()))}>
              <input className="input" style={{ height: 38, fontSize: 13.5 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Or describe a scenario, e.g. EBITDA falls 15% and debt rises $200M" />
              <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>Run</button>
            </form>
          </>
        )}
        {asked && <div className="ag-asked">{asked}</div>}
        {busy && <div className="ag-thinking">{mode === "ask" ? "Reading the covenants and filings" : "Running scenarios through the engine"}</div>}
        {err && <div className="callout callout-bad">{err}</div>}
        {r && !busy && (
          <div className="ag-brief-grid">
            <Markdown text={r.answer} />
            <div>
              <div className="upper" style={{ marginBottom: 8 }}>Agent steps</div>
              <Steps steps={r.steps} saved={r.saved} />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
