import { directionHelp, fmtDate, fmtHeadroomRange, fmtRatio, fmtRatioRange, kindLabel } from "@/lib/format";
import type { Direction, Status } from "@/lib/types";
import { StatusChip } from "./ui";

export interface CardSummary {
  id: string;
  kind: string;
  direction: Direction;
  status: Status;
  latest_period_end: string | null;
  ratio_low: number | null | undefined;
  ratio_high: number | null | undefined;
  threshold: number | null | undefined;
  headroom_low: number | null | undefined;
  headroom_high: number | null | undefined;
  quarters: number;
  refused: number;
  history?: { period_end: string; status: Status; rel: number | null }[];
}

const fin = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

/** Mini horizontal scale: threshold tick, breach side shaded, computed range as a bar (open sides fade to the edge). */
export function RangeGauge({ s, width = 260 }: { s: CardSummary; width?: number }) {
  if (s.status === "refused" || !fin(s.threshold)) return null;
  const vals = [s.threshold, s.ratio_low, s.ratio_high].filter(fin);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo || Math.abs(hi) * 0.2 || 1) * 0.35;
  lo -= pad;
  hi += pad;
  const H = 26;
  const x = (v: number) => 4 + ((v - lo) / (hi - lo)) * (width - 8);
  const tx = x(s.threshold);
  const color = `var(--${s.status})`;
  const rl = fin(s.ratio_low) ? x(s.ratio_low) : 4;
  const rh = fin(s.ratio_high) ? x(s.ratio_high) : width - 4;
  const gid = `g-${s.id}`;
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${H}`} height={H} aria-hidden preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={`${gid}-r`} x1="0" x2="1">
          <stop offset="0" stopColor={color} stopOpacity="1" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
        <linearGradient id={`${gid}-l`} x1="1" x2="0">
          <stop offset="0" stopColor={color} stopOpacity="1" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect x={4} y={11} width={width - 8} height={4} rx={2} fill="var(--surface-2)" />
      {s.direction === "max" ? (
        <rect x={tx} y={11} width={width - 4 - tx} height={4} fill="var(--breach-soft)" />
      ) : (
        <rect x={4} y={11} width={tx - 4} height={4} fill="var(--breach-soft)" />
      )}
      {Math.abs(rh - rl) < 3 ? (
        <circle cx={rl} cy={13} r={5} fill={color} stroke="var(--surface)" strokeWidth="1.5" />
      ) : (
        <rect
          x={rl}
          y={8}
          width={rh - rl}
          height={10}
          rx={3}
          fill={!fin(s.ratio_high) ? `url(#${gid}-r)` : !fin(s.ratio_low) ? `url(#${gid}-l)` : color}
          opacity="0.9"
        />
      )}
      <line x1={tx} x2={tx} y1={2} y2={24} stroke="var(--text)" strokeWidth="2" />
    </svg>
  );
}

/** Worst-case headroom (share of the limit) per quarter, with the limit as the zero line. */
function HeadroomSpark({ s }: { s: CardSummary }) {
  const pts = (s.history ?? []).filter((h) => h.rel !== null) as { period_end: string; status: Status; rel: number }[];
  if (pts.length < 2) return <div className="spark-empty tiny muted">Not enough computed quarters for a trend.</div>;
  const W = 300, H = 64;
  const vals = pts.map((p) => p.rel);
  const lo = Math.min(-0.05, ...vals), hi = Math.max(0.1, ...vals);
  const x = (i: number) => 4 + (i / (pts.length - 1)) * (W - 8);
  const y = (v: number) => 6 + (1 - (v - lo) / (hi - lo)) * (H - 12);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.rel).toFixed(1)}`).join("");
  const area = `${d}L${x(pts.length - 1).toFixed(1)},${y(0).toFixed(1)}L${x(0).toFixed(1)},${y(0).toFixed(1)}Z`;
  const last = pts[pts.length - 1];
  const gid = `hs-${s.id}`;
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect x="0" y={y(0)} width={W} height={Math.max(0, H - y(0))} fill="var(--breach-soft)" />
      <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="var(--breach)" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
      <path d={area} fill={`url(#${gid})`} />
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.8" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle cx={x(pts.length - 1)} cy={y(last.rel)} r="3.5" fill={`var(--${last.status})`} stroke="var(--surface)" strokeWidth="1.5" />
    </svg>
  );
}

const pctFmt = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%`;

export function CovenantCard({ s, selected, onClick }: { s: CardSummary; selected?: boolean; onClick?: () => void }) {
  const rel = s.history?.filter((h) => h.rel !== null).at(-1)?.rel ?? null;
  return (
    <button type="button" className="cov-card cov-card-v2" aria-pressed={selected} onClick={onClick}>
      <div className="between" style={{ width: "100%" }}>
        <div className="stack" style={{ gap: 2 }}>
          <h3>{kindLabel(s.kind)}</h3>
          <span className="tiny muted">
            {directionHelp(s.direction)}
            {s.latest_period_end ? ` · latest ${fmtDate(s.latest_period_end)}` : ""}
          </span>
        </div>
        <StatusChip status={s.status} />
      </div>
      <div className="cov-figure">
        <span className="cov-ratio num">{fmtRatioRange(s.ratio_low, s.ratio_high, s.status)}</span>
        <span className="cov-limit num">
          limit {s.direction === "max" ? "≤ " : "≥ "}
          {fmtRatio(s.threshold)}
        </span>
      </div>
      <div style={{ width: "100%" }}>
        <RangeGauge s={s} />
      </div>
      <div className="cov-spark-head">
        <span className="upper">Worst-case headroom</span>
        <span className="num" style={{ color: rel === null ? "var(--muted)" : `var(--${s.status})`, fontWeight: 600 }}>
          {rel === null ? fmtHeadroomRange(s.headroom_low, s.headroom_high, s.status) : `${pctFmt(rel)} of limit`}
        </span>
      </div>
      <div style={{ width: "100%" }}>
        <HeadroomSpark s={s} />
      </div>
      <div className="tiny muted">
        {s.quarters} quarter{s.quarters === 1 ? "" : "s"}
        {s.refused > 0 ? ` · ${s.refused} refused` : ""}
      </div>
    </button>
  );
}
