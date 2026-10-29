"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, settle } from "@/lib/api";
import {
  directionHelp,
  fmtDate,
  fmtHeadroomRange,
  fmtPct,
  fmtQuarter,
  fmtRatio,
  fmtRatioRange,
  fmtUsd,
  fmtUsdFull,
  kindLabel,
  OP_LABEL,
  reasonLabel,
  refusalScopeLabel,
} from "@/lib/format";
import type { Input, ProvenanceResponse, SpanWithContext, TermNode } from "@/lib/types";
import { ErrorState, ExternalLink, FixtureBadge, StatusChip } from "./ui";

interface Props {
  cik: string;
  covenantId: string;
  periodEnd: string | null;
  onClose: () => void;
  /** Render inline (demo mode) instead of as a modal drawer. */
  inline?: boolean;
}

export default function ProvenanceDrawer({ cik, covenantId, periodEnd, onClose, inline }: Props) {
  const [state, setState] = useState<{ key: string; data: ProvenanceResponse | null; error: ApiError | null } | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const key = `${cik}/${covenantId}/${periodEnd}`;

  useEffect(() => {
    if (!periodEnd) return;
    let alive = true;
    settle(api.provenance(cik, covenantId, periodEnd)).then((r) => {
      if (alive) setState({ key, data: r.data, error: r.error });
    });
    return () => {
      alive = false;
    };
  }, [cik, covenantId, periodEnd, key]);

  useEffect(() => {
    if (!periodEnd || inline) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [periodEnd, inline, onClose]);

  if (!periodEnd) return null;
  const loaded = state && state.key === key ? state : null;
  const p = loaded?.data ?? null;

  const head = (
    <div className="drawer-head">
      <div className="between">
        <div className="stack" style={{ gap: 4 }}>
          <div className="upper">Provenance</div>
          <h2 className="num">
            {p ? kindLabel(p.covenant.kind) : "Loading"} <span className="muted">·</span> {fmtQuarter(periodEnd)}
          </h2>
        </div>
        <div className="row">
          {p && <FixtureBadge source={p.source} />}
          {p && <StatusChip status={p.quarter.status} />}
          {!inline && (
            <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Close provenance">
              Close <kbd>Esc</kbd>
            </button>
          )}
        </div>
      </div>
    </div>
  );

  const body = (
    <div className="drawer-body">
      {!loaded && <DrawerSkeleton />}
      {loaded?.error && <ErrorState error={loaded.error} title="Could not load provenance" />}
      {p && <ProvenanceBody p={p} />}
    </div>
  );

  if (inline) {
    return (
      <div className="card" style={{ overflow: "hidden", background: "var(--bg)" }}>
        {head}
        {body}
      </div>
    );
  }

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} aria-hidden />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Provenance for ${fmtQuarter(periodEnd)}`}>
        {head}
        {body}
      </aside>
    </>
  );
}

function DrawerSkeleton() {
  return (
    <div className="stack">
      <div className="skeleton" style={{ height: 70 }} />
      <div className="skeleton" style={{ height: 120 }} />
      <div className="skeleton" style={{ height: 200 }} />
    </div>
  );
}

function ProvenanceBody({ p }: { p: ProvenanceResponse }) {
  const q = p.quarter;
  const inputsByNode = new Map<string, Input>();
  for (const i of p.inputs) inputsByNode.set(i.term_node, i);
  const termsById = new Map<string, TermNode>();
  for (const t of p.terms) termsById.set(t.id, t);
  const missing = q.missing ?? [];
  const labelOf = (id: string) => termsById.get(id)?.label ?? inputsByNode.get(id)?.label ?? id;

  return (
    <>
      {/* summary, in the company page's style: big light numerals, status colour, worst case first */}
      <div className={`dr-hero dr-${q.status}`}>
        <div>
          <div className="upper">Computed ratio</div>
          <div className="dr-big num">{fmtRatioRange(q.ratio_low, q.ratio_high, q.status)}</div>
          <div className="small muted">limit {p.covenant.direction === "max" ? "≤" : "≥"} {fmtRatio(q.threshold)}</div>
        </div>
        <div>
          <div className="upper">Headroom</div>
          <div className="dr-big num" style={{ color: `var(--${q.status})` }}>{fmtHeadroomRange(q.headroom_low, q.headroom_high, q.status)}</div>
          <div className="small muted">
            {q.headroom_low != null && q.threshold
              ? `${q.headroom_low >= 0 ? "+" : "−"}${Math.abs((q.headroom_low / Math.abs(q.threshold)) * 100).toFixed(1)}% of the limit, worst case`
              : "worst case to best case"}
          </div>
        </div>
        <div className="dr-note small muted">
          {directionHelp(p.covenant.direction)}. Tested on {p.covenant.test_period === "ttm" ? "the trailing four quarters" : p.covenant.test_period.replace(/_/g, " ")} ending {fmtDate(q.period_end)}.
        </div>
      </div>

      {q.status === "refused" && (
        <div className="callout callout-muted">
          <strong>Refused.</strong> This quarter was not computed.
          {p.refusals.length > 0 ? (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {p.refusals.map((r, i) => (
                <li key={i}>
                  <strong>{reasonLabel(r.reason)}</strong> ({refusalScopeLabel(r)}): {r.detail}
                </li>
              ))}
            </ul>
          ) : (
            " No reason was recorded for it."
          )}
        </div>
      )}

      {missing.length > 0 && (
        <div className="callout callout-warn">
          <strong>Missing inputs.</strong> {missing.length === 1 ? "One definition term has" : `${missing.length} definition terms have`} no
          XBRL source this quarter: {missing.map((m, i) => (
            <span key={m}>
              {i > 0 && ", "}
              <strong>{labelOf(m)}</strong>
            </span>
          ))}
          . The ratio is shown as a range: the low case assumes zero and the high case assumes the contract cap
          {q.ratio_low === null || q.ratio_high === null ? " (no cap exists, so one side is unbounded)" : ""}.
        </div>
      )}

      {q.status !== "refused" && p.refusals.length > 0 && (
        <div className="callout callout-muted small">
          {p.refusals.map((r, i) => (
            <div key={i}>
              <strong>{reasonLabel(r.reason)}</strong> ({refusalScopeLabel(r)}): {r.detail}
            </div>
          ))}
        </div>
      )}

      <section className="stack" style={{ gap: 8 }}>
        <h3 className="dr-h">Covenant clause</h3>
        <Clause span={p.covenant_clause} />
      </section>

      <section className="stack" style={{ gap: 8 }}>
        <h3 className="dr-h">Threshold in force</h3>
        {p.threshold_clause ? (
          <Clause span={p.threshold_clause} />
        ) : (
          <div className="callout callout-muted small">No threshold step covers this period end.</div>
        )}
      </section>

      <section className="stack" style={{ gap: 8 }}>
        <div className="between">
          <h3 className="dr-h">Definition tree</h3>
          <span className="tiny muted">Click a term to read its clause</span>
        </div>
        <div className="card card-pad tree">
          <div className="small muted" style={{ marginBottom: 6 }}>
            Ratio = <strong className="text-2">{labelOf(p.covenant.numerator_term)}</strong>
            {p.covenant.denominator_term && (
              <>
                {" "}÷ <strong className="text-2">{labelOf(p.covenant.denominator_term)}</strong>
              </>
            )}
          </div>
          <ul>
            <TreeNode id={p.covenant.numerator_term} terms={termsById} inputs={inputsByNode} missing={missing} depth={0} seen={[]} />
            {p.covenant.denominator_term && (
              <TreeNode id={p.covenant.denominator_term} terms={termsById} inputs={inputsByNode} missing={missing} depth={0} seen={[]} />
            )}
          </ul>
        </div>
      </section>

      <section className="stack" style={{ gap: 8 }}>
        <h3 className="dr-h">XBRL inputs</h3>
        {p.inputs.length === 0 ? (
          <div className="callout callout-muted small">No inputs were used for this quarter.</div>
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            {p.inputs.map((i) => (
              <InputRow key={i.term_node} input={i} isMissing={missing.includes(i.term_node)} />
            ))}
          </div>
        )}
      </section>

      <div className="tiny muted">
        Every clause above is an exact substring of the filed agreement at the cited character offsets. Values come from the
        company&apos;s XBRL facts in the cited filing.
      </div>
    </>
  );
}

export function Clause({ span }: { span: SpanWithContext }) {
  const ctx = span.context;
  return (
    <div>
      <div className="clause">
        {ctx ? (
          <>
            <span className="ctx">{ctx.before ? `…${ctx.before}` : ""}</span>
            <mark>{ctx.match}</mark>
            <span className="ctx">{ctx.after ? `${ctx.after}…` : ""}</span>
          </>
        ) : (
          <mark>{span.text}</mark>
        )}
      </div>
      <div className="clause-meta">
        {span.section && <span>Section {span.section}</span>}
        <span className="mono">{span.accession}</span>
        <span className="num">chars {span.char_start.toLocaleString()} to {span.char_end.toLocaleString()}</span>
        <ExternalLink href={span.url}>Source document</ExternalLink>
        {!ctx && <span>{span.context_note ?? "Surrounding text not cached; showing the clause only."}</span>}
      </div>
    </div>
  );
}

function capText(t: TermNode, terms: Map<string, TermNode>): string | null {
  const c = t.cap;
  if (!c) return null;
  if (c.kind === "pct_of" && typeof c.pct === "number") {
    const of = c.of ? terms.get(c.of)?.label ?? c.of : "the base";
    return `${t.op === "floor" ? "floor at" : "capped at"} ${fmtPct(c.pct, c.pct * 100 % 1 ? 1 : 0)} of ${of}`;
  }
  if (c.kind === "abs" && typeof c.usd === "number") return `${t.op === "floor" ? "floor at" : "capped at"} ${fmtUsd(c.usd)}`;
  return `cap: ${JSON.stringify(c)}`;
}

function TreeNode({
  id,
  terms,
  inputs,
  missing,
  depth,
  seen,
}: {
  id: string;
  terms: Map<string, TermNode>;
  inputs: Map<string, Input>;
  missing: string[];
  depth: number;
  seen: string[];
}) {
  const [open, setOpen] = useState(false);
  const t = terms.get(id);
  const input = inputs.get(id);
  const isMissing = missing.includes(id);
  if (!t) {
    return (
      <li>
        <div className="tnode">
          <span className="mono">{id}</span>
          <span className="muted small">definition not in provenance</span>
        </div>
      </li>
    );
  }
  const cycle = seen.includes(id);
  const cap = capText(t, terms);
  return (
    <li>
      <div className="tnode">
        <button type="button" className="lbl" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {t.label}
        </button>
        <span className={`op ${t.op === "cap" || t.op === "floor" ? "op-cap" : ""}`}>{OP_LABEL[t.op] ?? t.op}</span>
        {cap && <span className="small" style={{ color: "var(--warning)" }}>{cap}</span>}
        {t.op === "leaf" && input && input.value !== null && input.value !== undefined && (
          <span className="num small text-2" title={fmtUsdFull(input.value)}>{fmtUsd(input.value)}</span>
        )}
        {t.op === "leaf" && input?.xbrl_concept && <span className="mono tiny muted">{input.xbrl_concept}</span>}
        {isMissing && <span className="missing-flag">missing</span>}
      </div>
      {open && t.clause && (
        <div style={{ margin: "4px 0 8px 6px" }}>
          <Clause span={t.clause} />
        </div>
      )}
      {!cycle && t.children.length > 0 && depth < 12 && (
        <ul>
          {t.children.map((c) => (
            <TreeNode key={c} id={c} terms={terms} inputs={inputs} missing={missing} depth={depth + 1} seen={[...seen, id]} />
          ))}
        </ul>
      )}
    </li>
  );
}

function InputRow({ input: i, isMissing }: { input: Input; isMissing: boolean }) {
  const hasValue = i.value !== null && i.value !== undefined;
  return (
    <div className="card" style={{ padding: "10px 12px", borderColor: isMissing ? "color-mix(in srgb, var(--warning) 45%, var(--border))" : undefined }}>
      <div className="between" style={{ alignItems: "baseline" }}>
        <div className="stack" style={{ gap: 2 }}>
          <strong>{i.label ?? i.term_node}</strong>
          <span className="mono tiny muted">{i.xbrl_concept ?? "no XBRL concept mapped"}</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="num" style={{ fontWeight: 600, fontSize: 15 }} title={hasValue ? fmtUsdFull(i.value) : undefined}>
            {hasValue ? fmtUsdFull(i.value) : <span style={{ color: "var(--warning)" }}>no value</span>}
          </div>
          <div className="tiny muted num">
            {i.period_start ? `${fmtDate(i.period_start)} to ${fmtDate(i.period_end)}` : `as of ${fmtDate(i.period_end)}`}
          </div>
        </div>
      </div>
      <div className="row small" style={{ marginTop: 8, gap: 14 }}>
        <span className="conf" title="Mapping confidence: how sure the mapper is that this XBRL concept matches the contract term">
          <span className="conf-bar"><i style={{ width: `${Math.max(0, Math.min(1, i.mapping_confidence)) * 100}%` }} /></span>
          <span className="num text-2">{fmtPct(i.mapping_confidence)} confidence</span>
        </span>
        <span style={{ color: i.validated ? "var(--ok)" : "var(--warning)", fontWeight: 600 }}>
          {i.validated ? "Validated" : "Not validated"}
        </span>
        {i.fact_accession && (
          <ExternalLink href={i.filing_url} className="mono tiny">
            {i.fact_accession}
          </ExternalLink>
        )}
      </div>
      {i.validation_note && <div className="small text-2" style={{ marginTop: 6 }}>{i.validation_note}</div>}
    </div>
  );
}
