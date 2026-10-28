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

export function CovenantCard({ s, selected, onClick }: { s: CardSummary; selected?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className="cov-card" aria-pressed={selected} onClick={onClick}>
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
      <div className="kv" style={{ width: "100%" }}>
        <div>
          <div className="k">Ratio</div>
          <div className="v small num">{fmtRatioRange(s.ratio_low, s.ratio_high, s.status)}</div>
        </div>
        <div>
          <div className="k">Threshold</div>
          <div className="v small num">
            {s.direction === "max" ? "≤ " : "≥ "}
            {fmtRatio(s.threshold)}
          </div>
        </div>
        <div>
          <div className="k">Headroom</div>
          <div className="v small num">{fmtHeadroomRange(s.headroom_low, s.headroom_high, s.status)}</div>
        </div>
      </div>
      <div style={{ width: "100%" }}>
        <RangeGauge s={s} />
      </div>
      <div className="tiny muted">
        {s.quarters} quarter{s.quarters === 1 ? "" : "s"}
        {s.refused > 0 ? ` · ${s.refused} refused` : ""}
      </div>
    </button>
  );
}
