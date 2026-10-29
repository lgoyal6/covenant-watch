"use client";

import { useState } from "react";
import { callAgent, Markdown, Steps, type AgentReply } from "./shared";

/** Risk briefing agent: investigates the most at-risk covenants on its own and writes a ranked memo. */
export default function RiskBriefing() {
  const [top, setTop] = useState(5);
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<AgentReply | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setR(await callAgent("/agent/brief", { top }));
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
          <h2>Risk briefing agent</h2>
          <span className="small muted">Picks the covenants closest to breach, reads each timeline and the filings behind the latest quarter, and writes a ranked memo.</span>
        </div>
        <div className="row">
          <div className="ag-seg" role="group" aria-label="Covenants to brief">
            {[3, 5, 8].map((n) => (
              <button key={n} type="button" aria-pressed={top === n} onClick={() => setTop(n)}>Top {n}</button>
            ))}
          </div>
          <button type="button" className="btn btn-primary btn-sm" onClick={run} disabled={busy}>{busy ? "Investigating" : r ? "Run again" : "Run briefing"}</button>
        </div>
      </div>
      {(busy || r || err) && (
        <div className="ag-brief-body">
          {busy && <div className="ag-thinking">Investigating the riskiest covenants. This takes a minute.</div>}
          {err && <div className="callout callout-bad">{err}</div>}
          {r && !busy && (
            <div className="ag-brief-grid">
              <Markdown text={r.answer} />
              <div>
                <div className="upper" style={{ marginBottom: 8 }}>Investigation trail</div>
                <Steps steps={r.steps} />
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
