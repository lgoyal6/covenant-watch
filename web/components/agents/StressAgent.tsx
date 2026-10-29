"use client";

import { useState } from "react";
import { callAgent, Markdown, Steps, type AgentReply } from "./shared";

const PRESETS = [
  { label: "Standard scenarios", value: "" },
  { label: "EBITDA −25%", value: "earnings -25%" },
  { label: "Rates up: interest +50%", value: "interest or debt costs +50%, earnings unchanged" },
  { label: "Recession: EBITDA −40%, debt +20%", value: "earnings -40% and debt or interest +20%" },
];

/** Stress-test agent: the engine computes breakevens and scenarios, Claude chooses them and writes the result. */
export default function StressAgent({ cik, company }: { cik: string; company: string }) {
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState("");
  const [r, setR] = useState<AgentReply | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (scenario: string) => {
    setBusy(true);
    setErr(null);
    try {
      setR(await callAgent("/agent/stress", { cik, scenario: scenario || null }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card ag-brief">
      <div className="card-head">
        <div className="stack" style={{ gap: 2 }}>
          <h2>Stress-test agent</h2>
          <span className="small muted">How much bad news can {company}&rsquo;s covenants absorb? The engine recomputes each scenario through the contract&rsquo;s own definitions; the agent picks them and writes it up.</span>
        </div>
      </div>
      <div className="ag-brief-body stack" style={{ gap: 14 }}>
        <div className="row" style={{ gap: 8 }}>
          {PRESETS.map((p) => (
            <button key={p.label} type="button" className="btn btn-sm" disabled={busy} onClick={() => run(p.value)}>{p.label}</button>
          ))}
        </div>
        <form className="row" style={{ gap: 8 }} onSubmit={(e) => (e.preventDefault(), custom.trim() && run(custom.trim()))}>
          <input className="input" style={{ height: 38, fontSize: 13.5 }} value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Or describe a scenario, e.g. EBITDA falls 15% and the company draws $200M more on its revolver" />
          <button className="btn btn-primary btn-sm" disabled={busy || !custom.trim()}>Run</button>
        </form>
        {busy && <div className="ag-thinking">Running scenarios through the engine</div>}
        {err && <div className="callout callout-bad">{err}</div>}
        {r && !busy && (
          <div className="ag-brief-grid">
            <Markdown text={r.answer} />
            <div>
              <div className="upper" style={{ marginBottom: 8 }}>Engine runs</div>
              <Steps steps={r.steps} />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
