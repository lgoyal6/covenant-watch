"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { callAgent, Markdown, Steps, type Step } from "./shared";

type Msg = { role: "user" | "assistant"; content: string; steps?: Step[]; error?: boolean; saved?: boolean };

const SUGGEST_COMPANY = ["How close is this company to breaking a covenant?", "What drives the leverage ratio this quarter?", "Why is any quarter shown as a range?"];
const SUGGEST_PORTFOLIO = ["Which covenants are closest to breach?", "Which companies had a waiver or default?", "What could we not compute, and why?"];

/** Floating analyst agent: asks Claude, which reads our data through tools and cites what it used. */
export default function AnalystPanel() {
  const path = usePathname();
  const cik = path?.match(/^\/company\/([^/?#]+)/)?.[1] ?? null;
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [msgs, busy]);

  const send = async (question: string) => {
    if (!question.trim() || busy) return;
    const history = msgs.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: question }]);
    setQ("");
    setBusy(true);
    try {
      const r = await callAgent("/agent/ask", { question, cik, history });
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, steps: r.steps, saved: r.saved }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: (e as Error).message, error: true }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className={`ag-fab${open ? " on" : ""}`} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="ag-orb" aria-hidden /> {open ? "Close" : "Ask the analyst"}
      </button>
      {open && (
        <aside className="ag-panel" aria-label="Analyst agent">
          <header>
            <div>
              <div className="ag-title">Analyst agent</div>
              <div className="tiny muted">Reads covenants, timelines and filings through tools, then answers with the numbers it found.</div>
            </div>
            {cik && <span className="chip chip-neutral">CIK {cik}</span>}
          </header>
          <div className="ag-body">
            {msgs.length === 0 && (
              <div className="ag-suggest">
                {(cik ? SUGGEST_COMPANY : SUGGEST_PORTFOLIO).map((s) => (
                  <button key={s} type="button" onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`ag-msg ${m.role}${m.error ? " err" : ""}`}>
                {m.role === "assistant" && m.steps && <Steps steps={m.steps} saved={m.saved} />}
                {m.role === "assistant" && !m.error ? <Markdown text={m.content} /> : <p>{m.content}</p>}
              </div>
            ))}
            {busy && <div className="ag-msg assistant"><span className="ag-thinking">Looking it up</span></div>}
            <div ref={end} />
          </div>
          <form className="ag-input" onSubmit={(e) => (e.preventDefault(), send(q))}>
            <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={cik ? "Ask about this company" : "Ask about the portfolio"} />
            <button className="btn btn-primary" disabled={busy || !q.trim()}>Ask</button>
          </form>
        </aside>
      )}
    </>
  );
}
