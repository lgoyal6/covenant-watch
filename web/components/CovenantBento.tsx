import Link from "next/link";
import type { OverviewCovenant, OverviewResponse, Status } from "@/lib/types";
import { eventLabel, fmtDate, fmtRatio, kindLabel, reasonLabel } from "@/lib/format";

/* Covenant overview in the bento style of components/ui/finance-bento.tsx (dark canvas,
   gradient cards, glass KPI tiles, tick gauges, smooth streams), drawn server-side from
   /overview. Every number on it comes from the API; nothing is filled in. */

const STATUSES: Status[] = ["ok", "warning", "indeterminate", "breach", "refused"];
const COLOR: Record<Status, string> = {
  ok: "#8EE6B8",
  warning: "#FFC857",
  indeterminate: "#B9A6FF",
  breach: "#FF5C72",
  refused: "rgba(255,255,255,.28)",
};
const LABEL: Record<Status, string> = { ok: "OK", warning: "Warning", indeterminate: "Indeterminate", breach: "Breach", refused: "Refused" };

const GR = {
  blue: { top: "#b9a6ff", base: "#2e43ff", bottom: "#6d7dff", core: "#05082a" },
  graph: { top: "#9a9aa8", base: "#3a3a44", bottom: "#55555f", core: "#060608" },
  red: { top: "#ffb3c0", base: "#d7264a", bottom: "#f0607a", core: "#2a0410" },
  copper: { top: "#f6bf96", base: "#c2683a", bottom: "#dc8a5c", core: "#1d0b05" },
  green: { top: "#a6e8c8", base: "#36956f", bottom: "#58b58c", core: "#061d15" },
  lime: { top: "#f4ffb8", base: "#a3c400", bottom: "#c9e03a", core: "#121700" },
};

function Bg({ g }: { g: (typeof GR)[keyof typeof GR] }) {
  return (
    <>
      <div className="g" style={{ background: `linear-gradient(180deg,${g.top} 0%,${g.base} 36%,${g.base} 74%,${g.bottom} 100%)` }} />
      <div className="core" style={{ background: g.core }} />
    </>
  );
}

function smoothPath(P: [number, number][], move = true): string {
  if (!P.length) return "";
  let d = (move ? "M" : "L") + `${P[0][0]},${P[0][1]}`;
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] || P[i], p1 = P[i], p2 = P[i + 1], p3 = P[i + 2] || p2, k = 0.17;
    d += `C${p1[0] + (p2[0] - p0[0]) * k},${p1[1] + (p2[1] - p0[1]) * k} ${p2[0] - (p3[0] - p1[0]) * k},${p2[1] - (p3[1] - p1[1]) * k} ${p2[0]},${p2[1]}`;
  }
  return d;
}

const pct = (v: unknown, digits = 0) => (typeof v === "number" ? `${(v * 100).toFixed(digits)}%` : "n/a");
const num = (v: unknown) => (typeof v === "number" ? String(v) : "n/a");

/* ---- Hero: status mix per calendar quarter, stacked and smoothed ---- */
function StatusStream({ rows }: { rows: OverviewResponse["status_by_quarter"] }) {
  const W = 800, H = 190;
  if (rows.length < 2) return <div className="empty">Not enough quarters yet to draw a trend.</div>;
  const totals = rows.map((r) => STATUSES.reduce((a, s) => a + r[s], 0));
  const max = Math.max(1, ...totals);
  const X = (i: number) => (i / (rows.length - 1)) * W;
  // stack bottom-up: ok at the base, refused on top
  const layers: { s: Status; lo: number[]; hi: number[] }[] = [];
  let acc = rows.map(() => 0);
  for (const s of STATUSES) {
    const hi = acc.map((a, i) => a + rows[i][s]);
    layers.push({ s, lo: acc, hi });
    acc = hi;
  }
  const Y = (v: number) => H - (v / max) * (H - 8);
  return (
    <svg className="stream" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      {layers.map(({ s, lo, hi }) => {
        const top = hi.map((v, i) => [X(i), Y(v)] as [number, number]);
        const bot = lo.map((v, i) => [X(i), Y(v)] as [number, number]).reverse();
        return <path key={s} d={smoothPath(top) + smoothPath(bot, false) + "Z"} fill={COLOR[s]} opacity={s === "ok" ? 0.92 : 0.95} />;
      })}
    </svg>
  );
}

/* ---- Gauge: latest status of every covenant as a half ring of ticks ---- */
function StatusGauge({ latest }: { latest: Record<Status, number> }) {
  const total = STATUSES.reduce((a, s) => a + latest[s], 0);
  const n = 56;
  const cuts: { s: Status; to: number }[] = [];
  let run = 0;
  for (const s of STATUSES) {
    run += total ? latest[s] / total : 0;
    cuts.push({ s, to: run });
  }
  const computed = total - latest.refused;
  const ok = computed ? Math.round((latest.ok / computed) * 100) : null;
  const ticks = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n, a = ((180 + f * 180) * Math.PI) / 180;
    const s = total ? (cuts.find((c) => f <= c.to + 1e-9) || cuts[cuts.length - 1]).s : "refused";
    const r1 = 136, r2 = i % 7 === 0 ? 112 : 118;
    ticks.push(
      <line key={i} x1={(r1 * Math.cos(a)).toFixed(1)} y1={(r1 * Math.sin(a)).toFixed(1)} x2={(r2 * Math.cos(a)).toFixed(1)} y2={(r2 * Math.sin(a)).toFixed(1)}
        stroke={COLOR[s]} strokeWidth="3.2" strokeLinecap="round" className="tk" style={{ animationDelay: `${i * 12}ms` }} />,
    );
  }
  return (
    <svg className="gauge" viewBox="-150 -150 300 168" aria-hidden="true">
      {ticks}
      <text y="-22" textAnchor="middle" className="gauge-num">{ok === null ? "n/a" : ok}{ok === null ? null : <tspan className="gauge-pct" dy="-24">%</tspan>}</text>
      <text y="0" textAnchor="middle" className="gauge-cap">computed covenants OK</text>
    </svg>
  );
}

/* ---- Sparkline of worst-case headroom (% of the limit) with the zero line ---- */
function Spark({ c }: { c: OverviewCovenant }) {
  const pts = c.history.filter((h) => h.headroom_pct !== null) as { period_end: string; headroom_pct: number }[];
  if (pts.length < 2) return <svg width="96" height="30" aria-hidden="true" />;
  const W = 96, H = 30;
  const vals = pts.map((p) => p.headroom_pct);
  const lo = Math.min(0, ...vals), hi = Math.max(0.05, ...vals);
  const Y = (v: number) => H - 3 - ((v - lo) / (hi - lo)) * (H - 6);
  const P = pts.map((p, i) => [2 + (i / (pts.length - 1)) * (W - 6), Y(p.headroom_pct)] as [number, number]);
  const e = P[P.length - 1];
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      <line x1="0" x2={W} y1={Y(0)} y2={Y(0)} stroke="rgba(255,255,255,.45)" strokeDasharray="2 2" />
      <path d={smoothPath(P)} fill="none" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={e[0]} cy={e[1]} r="3" fill={COLOR[c.status]} stroke="rgba(0,0,0,.35)" />
    </svg>
  );
}

function Ticks({ frac, n = 36 }: { frac: number; n?: number }) {
  return (
    <svg className="ticks" viewBox={`0 0 ${n * 6} 20`} preserveAspectRatio="none" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <line key={i} x1={i * 6 + 2} x2={i * 6 + 2} y1={i % 6 === 0 ? 2 : 8} y2="20" stroke={i / (n - 1) <= frac ? "#E8FF1F" : "rgba(255,255,255,.28)"} strokeWidth="1.6" strokeLinecap="round" />
      ))}
    </svg>
  );
}

/** variant "portfolio" spans every company (dashboard); "company" is one company's page. */
export default function CovenantBento({ o, variant = "portfolio" }: { o: OverviewResponse; variant?: "portfolio" | "company" }) {
  const one = variant === "company";
  const ra = o.ratio_accuracy || {};
  const ew = o.early_warning || {};
  const attention = o.status_latest.warning + o.status_latest.breach + o.status_latest.indeterminate;
  const refusalTotal = Object.values(o.refusals).reduce((a, b) => a + b, 0);
  const refusalMax = Math.max(1, ...Object.values(o.refusals));
  const q0 = o.status_by_quarter[0]?.quarter, q1 = o.status_by_quarter[o.status_by_quarter.length - 1]?.quarter;
  const hit = typeof ew.hit_rate === "number" ? ew.hit_rate : null;
  // headline accuracy: share of company-reported ratios inside our computed range; older reports only carry the ±0.05x rate
  const acc = typeof ra.pct_inside_range === "number"
    ? { v: ra.pct_inside_range, cap: "Reported ratio inside our range" }
    : typeof ra.pct_within_0_05 === "number" ? { v: ra.pct_within_0_05, cap: "Within ±0.05x of reported" } : { v: null, cap: "Reported ratio inside our range" };

  return (
    <div className="cwb">
      <style>{CSS}</style>
      <div className="canvas">
        <div className="grid">
          {/* hero: covenant health over time */}
          <section className="card h1" id="cw-health" aria-label="Covenant health over time" style={{ animationDelay: "0ms" }}>
            <Bg g={GR.blue} />
            <div className="in-c">
              <div className="row between">
                <div className="ttl">Covenant health over time</div>
                <div className="legend">{STATUSES.map((s) => <span key={s}><i style={{ background: COLOR[s] }} />{LABEL[s]}</span>)}</div>
              </div>
              <div className="row" style={{ marginTop: 16, alignItems: "flex-end", gap: 16 }}>
                <span className="big">{attention}<span className="of"> of {o.covenants - o.status_latest.refused}</span></span>
                <div style={{ paddingBottom: 6 }}>
                  <div className="delta">need attention now</div>
                  <div className="muted" style={{ marginTop: 3 }}>{one ? "" : `${o.companies === 1 ? "1 company" : `${o.companies} companies`} · `}{o.covenants} covenants · {o.quarters} covenant-quarters computed</div>
                </div>
              </div>
              <div className="stream-wrap">
                <StatusStream rows={o.status_by_quarter} />
                <div className="axis"><span>{q0}</span><span>{q1}</span></div>
              </div>
            </div>
            <div className="rim" />
          </section>

          {/* gauge: latest status mix */}
          <section className="card h1" id="cw-mix" aria-label="Latest status" style={{ animationDelay: "60ms" }}>
            <Bg g={GR.graph} />
            <div className="in-c">
              <div className="row between"><div className="ttl">Latest status</div><span className="chip">{o.covenants} covenants</span></div>
              <StatusGauge latest={o.status_latest} />
              <div className="list">
                {STATUSES.map((s, i) => (
                  <div key={s} className="row lrow" style={i ? { borderTop: "1px solid rgba(255,255,255,.1)" } : undefined}>
                    <i className="dot" style={{ background: COLOR[s] }} />
                    <span className="lname">{LABEL[s]}</span>
                    <span className="mono">{o.status_latest[s]}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="rim" />
          </section>

          {/* KPI row */}
          <section className="card h2 kpi" aria-label="Ratio accuracy" style={{ animationDelay: "120ms" }}>
            <Bg g={GR.lime} />
            <div className="in-c">
              <div className="row between"><div className="cap dark">{acc.cap}</div><span className="chip">n={num(ra.n)}</span></div>
              <div className="kbig">{pct(acc.v)}</div>
              <div className="foot dark">vs ratios companies reported in 10-K/10-Q</div>
            </div>
            <div className="rim" />
          </section>
          <section className="card glass h2 kpi" aria-label="Early warning" style={{ animationDelay: "180ms" }}>
            <div className="in-c">
              <div className="row between"><div className="cap">{one ? "Flagged before its event" : "Early-warning hit rate"}</div><span className="muted">{num(ew.events_scored)} events</span></div>
              <div className="row between" style={{ marginTop: 14, alignItems: "baseline" }}>
                <span className="big sm">{pct(hit)}</span>
                <span className="mono lead">{num(ew.median_lead_quarters)}<span className="muted"> qtr lead</span></span>
              </div>
              <Ticks frac={hit ?? 0} />
            </div>
          </section>
          <section className="card glass h2 kpi" aria-label="Peer false alarms" style={{ animationDelay: "240ms" }}>
            <div className="in-c">
              <div className="row between"><div className="cap">{one ? "Its peers flagged" : "Peer false alarm rate"}</div><span className="muted">{num(ew.peers_scored)} peers</span></div>
              <div className="big sm" style={{ marginTop: 14 }}>{pct(ew.peer_false_alarm_rate)}</div>
              <div className="foot">matched peers that never had a covenant event</div>
            </div>
          </section>
          <section className="card glass h2 kpi" aria-label="Refusals" style={{ animationDelay: "300ms" }}>
            <div className="in-c">
              <div className="row between"><div className="cap">Honest refusals</div><span className="muted">not guessed</span></div>
              <div className="big sm" style={{ marginTop: 14 }}>{refusalTotal}</div>
              <div className="foot">{Object.keys(o.refusals).slice(0, 2).map(reasonLabel).join(" · ") || "none"}</div>
            </div>
          </section>

          {/* bottom row */}
          <section className="card h3" id="cw-closest" aria-label="Closest to breach" style={{ animationDelay: "360ms" }}>
            <Bg g={GR.red} />
            <div className="in-c">
              <div className="row between"><div><div className="ttl">{one ? "Covenants" : "Closest to breach"}</div><div className="muted" style={{ marginTop: 4 }}>{one ? "closest to the limit first; " : ""}worst-case headroom, % of the limit</div></div></div>
              <div className="rows">
                {o.closest.length === 0 ? <div className="empty">No computed covenants yet.</div> : o.closest.slice(0, 5).map((c, i) => (
                  <Link key={c.cik + c.covenant_id} href={`/company/${c.cik}?cov=${encodeURIComponent(c.covenant_id)}#timeline`} className="row crow" style={i ? { borderTop: "1px solid rgba(255,255,255,.12)" } : undefined}>
                    <div className="cname"><div className="nm">{one ? kindLabel(c.kind) : c.name}</div><div className="mono muted sub">{one ? `${fmtRatio(c.threshold)} limit · ${c.quarters} quarters` : `${kindLabel(c.kind)} · ${fmtRatio(c.threshold)} limit`}</div></div>
                    <Spark c={c} />
                    <div className="cval"><div className="mono">{pct(c.headroom_pct, 1)}</div><div className="mono sub" style={{ color: COLOR[c.status] }}>{LABEL[c.status]}</div></div>
                  </Link>
                ))}
              </div>
            </div>
            <div className="rim" />
          </section>

          <section className="card h3" id="cw-events" aria-label="Disclosed covenant events" style={{ animationDelay: "420ms" }}>
            <Bg g={GR.copper} />
            <div className="in-c">
              <div className="row between"><div className="ttl">Disclosed events</div><span className="muted">{o.events_total} total</span></div>
              <div className="muted" style={{ marginTop: 4 }}>waivers, defaults and loosening amendments from 8-Ks</div>
              <div className="rows">
                {o.events.length === 0 ? <div className="empty">No events for companies on screen.</div> : o.events.slice(0, 5).map((e, i) => (
                  <Link key={e.cik + e.date + i} href={`/company/${e.cik}`} className="row crow" style={i ? { borderTop: "1px solid rgba(255,255,255,.12)" } : undefined}>
                    <div className="cname"><div className="nm">{one ? fmtDate(e.date) : e.name}</div><div className="mono muted sub">{one ? (e.span?.text || "").slice(0, 60) + "…" : fmtDate(e.date)}</div></div>
                    <span className="chip">{eventLabel(e.kind)}</span>
                  </Link>
                ))}
              </div>
            </div>
            <div className="rim" />
          </section>

          <section className="card h3" id="cw-refusals" aria-label="Refusals by reason" style={{ animationDelay: "480ms" }}>
            <Bg g={GR.green} />
            <div className="in-c">
              <div className="ttl">Refusals by reason</div>
              <div className="muted" style={{ marginTop: 4 }}>what we would not compute, and why</div>
              <div className="bars">
                {Object.keys(o.refusals).length === 0 ? <div className="empty">None.</div> : Object.entries(o.refusals).slice(0, 5).map(([r, n]) => (
                  <div key={r} className="bar">
                    <div className="row between"><span className="lname">{reasonLabel(r)}</span><span className="mono">{n}</span></div>
                    <div className="track"><div className="fill" style={{ width: `${(n / refusalMax) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
            </div>
            <div className="rim" />
          </section>
        </div>
      </div>
    </div>
  );
}

const CSS = `.cwb{font-family:var(--font);-webkit-font-smoothing:antialiased;color:#fff;width:100%;--acc:#E8FF1F;--t2:rgba(255,255,255,.62);--t3:rgba(255,255,255,.42);--ease:cubic-bezier(.32,.72,0,1)}
.cwb *{box-sizing:border-box}
.cwb .canvas{position:relative;padding:20px 22px 22px;background:#000;border-radius:28px}
.cwb .grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}
.cwb .h1{height:376px}.cwb .h2{height:168px}.cwb .h3{height:360px}
.cwb #cw-health{grid-column:span 8}.cwb #cw-mix{grid-column:span 4}.cwb .kpi{grid-column:span 3}
.cwb #cw-closest{grid-column:span 5}.cwb #cw-events{grid-column:span 4}.cwb #cw-refusals{grid-column:span 3}
@media (max-width:1199px){.cwb #cw-health{grid-column:span 12}.cwb #cw-mix{grid-column:span 12}.cwb .kpi{grid-column:span 6}
  .cwb #cw-closest{grid-column:span 12}.cwb #cw-events,.cwb #cw-refusals{grid-column:span 6}}
@media (max-width:767px){.cwb .canvas{padding:14px}.cwb .kpi,.cwb #cw-events,.cwb #cw-refusals{grid-column:span 12}.cwb .legend{display:none}.cwb .grid{gap:12px}}
.cwb .card{position:relative;border-radius:28px;overflow:hidden;opacity:0;transform:translateY(14px) scale(.985);animation:cwb-in .9s var(--ease) forwards}
@keyframes cwb-in{to{opacity:1;transform:none}}
.cwb .rim{position:absolute;inset:0;border-radius:inherit;box-shadow:inset 0 1px 0 rgba(255,255,255,.2),inset 0 0 0 1px rgba(255,255,255,.06);pointer-events:none;z-index:9}
.cwb .g{position:absolute;inset:0}
.cwb .core{position:absolute;left:10%;right:10%;top:16%;bottom:-6%;border-radius:90px;filter:blur(60px)}
.cwb .glass{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12)}
.cwb .in-c{position:absolute;inset:0;padding:22px 24px;z-index:2;display:flex;flex-direction:column}
.cwb .row{display:flex;align-items:center;gap:12px}.cwb .between{justify-content:space-between}
.cwb .ttl{font-size:18px;font-weight:600;letter-spacing:-.02em}
.cwb .cap{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--t2)}
.cwb .cap.dark,.cwb .foot.dark{color:rgba(0,0,0,.62)}
.cwb .big{font-size:52px;font-weight:200;letter-spacing:-.04em;line-height:1;font-variant-numeric:tabular-nums}
.cwb .big.sm{font-size:38px}.cwb .big .of{font-size:18px;color:var(--t2);letter-spacing:-.01em;font-weight:400}
.cwb .kbig{margin-top:auto;margin-bottom:6px;font-size:52px;font-weight:200;letter-spacing:-.04em;line-height:1;color:#0b0b0c;font-variant-numeric:tabular-nums}
.cwb .foot{font-size:11.5px;color:var(--t3);margin-top:6px}
.cwb .kpi .foot{margin-top:auto}
.cwb .kpi .kbig + .foot{margin-top:0}
.cwb .delta{font:600 12.5px var(--mono);color:var(--acc)}
.cwb .muted{font-size:12.5px;color:var(--t3);font-weight:500}
.cwb .mono{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:13px}
.cwb .lead{font-size:20px}
.cwb .chip{display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:11px;background:rgba(0,0,0,.6);color:#fff;font:600 11px var(--mono);white-space:nowrap}
.cwb .legend{display:flex;gap:14px;font-size:12px;font-weight:500;color:var(--t2)}
.cwb .legend span{display:inline-flex;align-items:center;gap:6px}.cwb .legend i,.cwb .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.cwb .stream-wrap{margin-top:auto}
.cwb .stream{display:block;width:100%;height:190px;transform-origin:bottom;animation:cwb-grow 1.1s var(--ease) both .2s}
@keyframes cwb-grow{from{transform:scaleY(0)}to{transform:none}}
.cwb .axis{display:flex;justify-content:space-between;font:500 10.5px var(--mono);color:rgba(255,255,255,.75);margin-top:6px}
.cwb .gauge{display:block;width:300px;max-width:100%;height:auto;align-self:center;margin-top:8px}
.cwb .gauge .tk{opacity:0;animation:cwb-tk .4s forwards}@keyframes cwb-tk{to{opacity:1}}
.cwb .gauge-num{font-family:var(--font);font-weight:200;font-size:52px;fill:#fff;letter-spacing:-2px}
.cwb .gauge-pct{font-size:17px;fill:var(--t2)}.cwb .gauge-cap{font-size:12px;font-weight:500;fill:var(--t3)}
.cwb .list{margin-top:auto}.cwb .lrow{height:26px}.cwb .lname{flex:1;font-size:13px;font-weight:600}
.cwb .ticks{display:block;width:100%;height:20px;margin-top:auto}
.cwb .rows{margin-top:14px;display:flex;flex-direction:column}
.cwb .crow{height:52px;color:#fff;text-decoration:none;border-radius:10px;transition:background .2s}
.cwb .crow:hover{background:rgba(0,0,0,.18)}
.cwb .cname{flex:1;min-width:0}.cwb .nm{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cwb .sub{font-size:11px}.cwb .cval{width:96px;text-align:right}
.cwb .bars{margin-top:18px;display:flex;flex-direction:column;gap:14px}
.cwb .track{height:6px;border-radius:3px;background:rgba(0,0,0,.28);margin-top:7px;overflow:hidden}
.cwb .fill{height:100%;border-radius:3px;background:#fff;transform-origin:left;animation:cwb-bar .8s var(--ease) both .5s}
@keyframes cwb-bar{from{transform:scaleX(0)}to{transform:none}}
.cwb .empty{font-size:12.5px;color:var(--t2);margin-top:16px}
@media (prefers-reduced-motion: reduce){.cwb .card,.cwb .stream,.cwb .gauge .tk,.cwb .fill{animation:none;opacity:1;transform:none}}`;
