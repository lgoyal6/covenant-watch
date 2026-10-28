"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { refusalsForQuarter } from "@/lib/derive";
import {
  dateToMs,
  eventLabel,
  fmtDate,
  fmtHeadroomRange,
  fmtQuarter,
  fmtRatio,
  fmtRatioRange,
  reasonLabel,
  STATUS_LABEL,
} from "@/lib/format";
import type { QuarterResult, Status, TimelineResponse } from "@/lib/types";

const DAY = 86_400_000;
const STATUS_VAR: Record<Status, string> = {
  ok: "var(--ok)",
  warning: "var(--warning)",
  breach: "var(--breach)",
  indeterminate: "var(--indeterminate)",
  refused: "var(--refused)",
};

function niceStep(range: number, target: number): number {
  const raw = range / Math.max(1, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

const finite = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

interface Props {
  data: TimelineResponse;
  selected?: string | null;
  onSelect?: (periodEnd: string) => void;
  height?: number;
  /** Emphasize event markers (demo mode). */
  emphasizeEvents?: boolean;
}

export default function Timeline({ data, selected, onSelect, height = 360, emphasizeEvents }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(960);
  const [hover, setHover] = useState<number | null>(null);
  const uid = "tl" + useId().replace(/[^a-zA-Z0-9]/g, "");

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (w > 0) setW(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = height;
  const M = { top: 40, right: 20, bottom: 58, left: 54 };
  const pw = Math.max(100, W - M.left - M.right);
  const ph = H - M.top - M.bottom;
  const direction = data.covenant.direction;

  const model = useMemo(() => {
    const quarters = [...data.quarters].sort((a, b) => dateToMs(a.period_end) - dateToMs(b.period_end));
    const qMs = quarters.map((q) => dateToMs(q.period_end));
    const events = [...(data.events ?? [])].sort((a, b) => dateToMs(a.date) - dateToMs(b.date));
    const disclosed = data.disclosed ?? [];
    const firstQ = qMs[0] ?? Date.now();
    const lastQ = qMs[qMs.length - 1] ?? Date.now();
    const amendments = (data.agreements ?? []).filter(
      (a) => a.kind !== "original" && dateToMs(a.filed) >= firstQ - 400 * DAY,
    );

    let x0 = firstQ;
    let x1 = lastQ;
    for (const e of events) x1 = Math.max(x1, dateToMs(e.date));
    for (const d of disclosed) {
      x0 = Math.min(x0, dateToMs(d.period_end));
      x1 = Math.max(x1, dateToMs(d.period_end));
    }
    for (const a of amendments) x0 = Math.min(x0, dateToMs(a.filed));
    const spacing = qMs.length > 1 ? (lastQ - firstQ) / (qMs.length - 1) : 91 * DAY;
    x0 -= spacing * 0.6;
    x1 += spacing * 0.6;

    // y domain from every finite value we draw
    const ys: number[] = [];
    for (const q of quarters) {
      if (finite(q.ratio_low)) ys.push(q.ratio_low);
      if (finite(q.ratio_high)) ys.push(q.ratio_high);
      if (finite(q.threshold)) ys.push(q.threshold);
    }
    const thresholds = [...(data.thresholds ?? [])].sort((a, b) => dateToMs(a.effective_from) - dateToMs(b.effective_from));
    for (const t of thresholds) {
      const from = dateToMs(t.effective_from);
      const to = t.effective_to ? dateToMs(t.effective_to) : Infinity;
      if (to >= x0 && from <= x1) ys.push(t.value);
    }
    for (const d of disclosed) {
      ys.push(d.reported_value);
      if (finite(d.reported_threshold)) ys.push(d.reported_threshold);
    }
    let yMin = ys.length ? Math.min(...ys) : 0;
    let yMax = ys.length ? Math.max(...ys) : 1;
    const span = yMax - yMin || Math.max(0.5, Math.abs(yMax) * 0.2);
    yMin -= span * 0.18;
    yMax += span * 0.18;
    if (yMin < 0 && Math.min(...(ys.length ? ys : [0])) >= 0) yMin = 0;
    const step = niceStep(yMax - yMin, 5);
    yMin = Math.floor(yMin / step) * step;
    yMax = Math.ceil(yMax / step) * step;
    const yTicks: number[] = [];
    for (let v = yMin; v <= yMax + step / 2; v += step) yTicks.push(Number(v.toFixed(6)));

    return { quarters, qMs, events, disclosed, amendments, thresholds, x0, x1, yMin, yMax, yTicks, spacing };
  }, [data]);

  const { quarters, qMs, events, disclosed, amendments, thresholds, x0, x1, yMin, yMax, yTicks, spacing } = model;
  const sx = (ms: number) => M.left + ((ms - x0) / (x1 - x0 || 1)) * pw;
  const sy = (v: number) => M.top + (1 - (v - yMin) / (yMax - yMin || 1)) * ph;
  const yTop = M.top;
  const yBot = M.top + ph;
  const colW = Math.max(6, Math.min(80, (spacing / (x1 - x0 || 1)) * pw));
  const barW = Math.max(5, Math.min(12, colW * 0.22));

  // threshold steps clipped to domain
  const steps = thresholds
    .map((t) => {
      const a = Math.max(x0, dateToMs(t.effective_from));
      const b = Math.min(x1, t.effective_to ? dateToMs(t.effective_to) + DAY : x1);
      return b > a ? { a, b, v: t.value, t } : null;
    })
    .filter((s): s is NonNullable<typeof s> => s !== null);
  let thrPath = "";
  steps.forEach((s, i) => {
    const prev = steps[i - 1];
    if (prev && Math.abs(prev.b - s.a) <= 3 * DAY) thrPath += ` L${sx(s.a)},${sy(s.v)}`;
    else thrPath += ` M${sx(s.a)},${sy(s.v)}`;
    thrPath += ` L${sx(s.b)},${sy(s.v)}`;
  });
  // Fallback: no threshold schedule, step through each quarter's threshold.
  if (!steps.length) {
    quarters.forEach((q, i) => {
      if (!finite(q.threshold)) return;
      const a = i === 0 ? x0 : (qMs[i - 1] + qMs[i]) / 2;
      const b = i === quarters.length - 1 ? x1 : (qMs[i] + qMs[i + 1]) / 2;
      thrPath += `${thrPath ? " L" : " M"}${sx(a)},${sy(q.threshold)} L${sx(b)},${sy(q.threshold)}`;
    });
  }

  // Band segments split at refused quarters. A null side on a computed quarter is unbounded and runs to the plot edge.
  const segments: { x: number; lo: number; hi: number; loOpen: boolean; hiOpen: boolean }[][] = [];
  let cur: (typeof segments)[number] = [];
  quarters.forEach((q, i) => {
    if (q.status === "refused" || (!finite(q.ratio_low) && !finite(q.ratio_high) && q.status !== "indeterminate")) {
      if (cur.length) segments.push(cur);
      cur = [];
      return;
    }
    const loOpen = !finite(q.ratio_low);
    const hiOpen = !finite(q.ratio_high);
    cur.push({
      x: sx(qMs[i]),
      lo: loOpen ? yBot : sy(q.ratio_low as number),
      hi: hiOpen ? yTop : sy(q.ratio_high as number),
      loOpen,
      hiOpen,
    });
  });
  if (cur.length) segments.push(cur);

  const linePath = (pts: { x: number; y: number; open: boolean }[]) => {
    let d = "";
    let pen = false;
    for (const p of pts) {
      if (p.open) {
        pen = false;
        continue;
      }
      d += `${pen ? " L" : " M"}${p.x},${p.y}`;
      pen = true;
    }
    return d;
  };

  const xLabelEvery = Math.max(1, Math.ceil((quarters.length * 58) / pw));
  const hovered = hover !== null ? quarters[hover] : null;
  const hoveredRefusals = hovered ? refusalsForQuarter(data.refusals ?? [], data.covenant.id, hovered.period_end) : [];

  // stagger event labels that would collide
  const eventLabels: { x: number; row: number; text: string }[] = [];
  for (const e of events) {
    const x = sx(dateToMs(e.date));
    const text = `${eventLabel(e.kind)} ${fmtDate(e.date)}`;
    let row = 0;
    while (eventLabels.some((l) => l.row === row && Math.abs(l.x - x) < 150)) row++;
    eventLabels.push({ x, row, text });
  }

  const selectAt = (i: number) => onSelect?.(quarters[i].period_end);

  return (
    <div ref={wrapRef} className="chart-wrap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        height={H}
        role="img"
        aria-label={`Headroom timeline for ${data.covenant.kind}: computed ratio range per quarter against the threshold.`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <pattern id={`${uid}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--refused-soft)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--refused)" strokeOpacity="0.35" strokeWidth="2" />
          </pattern>
          <clipPath id={`${uid}-clip`}>
            <rect x={M.left} y={yTop} width={pw} height={ph} />
          </clipPath>
          {(["ok", "warning", "breach", "indeterminate"] as Status[]).map((s) => (
            <g key={s}>
              <linearGradient id={`${uid}-up-${s}`} x1="0" y1="1" x2="0" y2="0">
                <stop offset="0" stopColor={STATUS_VAR[s]} stopOpacity="0.9" />
                <stop offset="1" stopColor={STATUS_VAR[s]} stopOpacity="0" />
              </linearGradient>
              <linearGradient id={`${uid}-dn-${s}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={STATUS_VAR[s]} stopOpacity="0.9" />
                <stop offset="1" stopColor={STATUS_VAR[s]} stopOpacity="0" />
              </linearGradient>
            </g>
          ))}
        </defs>

        {/* grid + y axis */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={M.left + pw} y1={sy(v)} y2={sy(v)} stroke="var(--border)" strokeWidth="1" />
            <text x={M.left - 8} y={sy(v)} dy="0.32em" textAnchor="end" fontSize="11" fill="var(--muted)" className="num">
              {v.toFixed(step2digits(yTicks))}x
            </text>
          </g>
        ))}
        <text x={14} y={M.top + ph / 2} fontSize="11" fill="var(--muted)" transform={`rotate(-90 14 ${M.top + ph / 2})`} textAnchor="middle">
          Ratio
        </text>

        <g clipPath={`url(#${uid}-clip)`}>
          {/* breach zone beyond the threshold */}
          {steps.map((s, i) => (
            <rect
              key={`z${i}`}
              x={sx(s.a)}
              width={Math.max(0, sx(s.b) - sx(s.a))}
              y={direction === "max" ? yTop : sy(s.v)}
              height={direction === "max" ? Math.max(0, sy(s.v) - yTop) : Math.max(0, yBot - sy(s.v))}
              fill="var(--breach-soft)"
              opacity="0.65"
            />
          ))}

          {/* selected column */}
          {quarters.map((q, i) =>
            q.period_end === selected ? (
              <rect key={`sel${i}`} x={sx(qMs[i]) - colW / 2} width={colW} y={yTop} height={ph} fill="var(--accent-soft)" />
            ) : null,
          )}

          {/* refused quarters: a gap, hatched */}
          {quarters.map((q, i) =>
            q.status === "refused" ? (
              <g key={`ref${i}`}>
                <rect x={sx(qMs[i]) - colW * 0.35} width={colW * 0.7} y={yTop} height={ph} fill={`url(#${uid}-hatch)`} />
                <text x={sx(qMs[i])} y={yTop + 14} textAnchor="middle" fontSize="10.5" fontWeight="600" fill="var(--refused)">
                  Refused
                </text>
              </g>
            ) : null,
          )}

          {/* amendment guide lines */}
          {amendments.map((a) => (
            <line key={`al${a.accession}`} x1={sx(dateToMs(a.filed))} x2={sx(dateToMs(a.filed))} y1={yTop} y2={yBot} stroke="var(--accent)" strokeOpacity="0.35" strokeDasharray="1 3" />
          ))}

          {/* computed range band */}
          {segments.map((seg, i) =>
            seg.length > 1 ? (
              <g key={`band${i}`}>
                <path
                  d={`M${seg.map((p) => `${p.x},${p.hi}`).join(" L")} L${[...seg].reverse().map((p) => `${p.x},${p.lo}`).join(" L")} Z`}
                  fill="var(--band)"
                />
                <path d={linePath(seg.map((p) => ({ x: p.x, y: p.hi, open: p.hiOpen })))} fill="none" stroke="var(--band-stroke)" strokeWidth="1.5" />
                <path d={linePath(seg.map((p) => ({ x: p.x, y: p.lo, open: p.loOpen })))} fill="none" stroke="var(--band-stroke)" strokeWidth="1.5" />
              </g>
            ) : null,
          )}

          {/* threshold step line */}
          <path d={thrPath} fill="none" stroke="var(--text)" strokeWidth="2" strokeLinejoin="round" />

          {/* per-quarter range bars, colored by status */}
          {quarters.map((q, i) => {
            if (q.status === "refused") return null;
            const x = sx(qMs[i]);
            const loF = finite(q.ratio_low);
            const hiF = finite(q.ratio_high);
            if (!loF && !hiF) {
              return (
                <rect key={`b${i}`} x={x - barW / 2} width={barW} y={yTop} height={ph} fill={STATUS_VAR[q.status]} opacity="0.25" />
              );
            }
            const yl = loF ? sy(q.ratio_low as number) : null;
            const yh = hiF ? sy(q.ratio_high as number) : null;
            const color = STATUS_VAR[q.status];
            return (
              <g key={`b${i}`}>
                {yl !== null && yh !== null && Math.abs(yl - yh) < 2 ? (
                  <circle cx={x} cy={yl} r={4.5} fill={color} stroke="var(--surface)" strokeWidth="1.5" />
                ) : (
                  <>
                    {yl !== null && yh !== null && (
                      <rect x={x - barW / 2} width={barW} y={yh} height={Math.max(2, yl - yh)} rx={2} fill={color} />
                    )}
                    {yh === null && yl !== null && (
                      <>
                        <rect x={x - barW / 2} width={barW} y={yTop} height={Math.max(2, yl - yTop)} fill={`url(#${uid}-up-${q.status})`} />
                        <path d={`M${x - 5},${yTop + 9} L${x},${yTop + 3} L${x + 5},${yTop + 9}`} fill="none" stroke={color} strokeWidth="1.6" />
                      </>
                    )}
                    {yl === null && yh !== null && (
                      <>
                        <rect x={x - barW / 2} width={barW} y={yh} height={Math.max(2, yBot - yh)} fill={`url(#${uid}-dn-${q.status})`} />
                        <path d={`M${x - 5},${yBot - 9} L${x},${yBot - 3} L${x + 5},${yBot - 9}`} fill="none" stroke={color} strokeWidth="1.6" />
                      </>
                    )}
                  </>
                )}
              </g>
            );
          })}

          {/* company-reported ratios (ground truth) */}
          {disclosed.map((d, i) => (
            <circle
              key={`d${i}`}
              cx={sx(dateToMs(d.period_end))}
              cy={sy(d.reported_value)}
              r={5.5}
              fill="var(--surface)"
              stroke="var(--disclosed)"
              strokeWidth="2.2"
            >
              <title>{`Company reported ${fmtRatio(d.reported_value)} for ${fmtDate(d.period_end)}${finite(d.reported_threshold) ? ` (threshold ${fmtRatio(d.reported_threshold)})` : ""}: "${d.span.text}"`}</title>
            </circle>
          ))}
        </g>

        {/* event markers: real disclosed waiver / default dates */}
        {events.map((e, i) => {
          const x = sx(dateToMs(e.date));
          const lbl = eventLabels[i];
          return (
            <g key={`e${i}`}>
              <line x1={x} x2={x} y1={yTop - 4 - lbl.row * 14} y2={yBot} stroke="var(--event)" strokeWidth={emphasizeEvents ? 2.4 : 1.6} strokeDasharray="5 4" />
              <text
                x={x}
                y={yTop - 9 - lbl.row * 14}
                textAnchor={x > M.left + pw - 120 ? "end" : x < M.left + 120 ? "start" : "middle"}
                fontSize="11"
                fontWeight="650"
                fill="var(--event)"
              >
                {lbl.text}
              </text>
              <title>{`${eventLabel(e.kind)} disclosed ${fmtDate(e.date)} (${e.span.accession}): "${e.span.text}"`}</title>
            </g>
          );
        })}

        {/* x axis */}
        <line x1={M.left} x2={M.left + pw} y1={yBot} y2={yBot} stroke="var(--border-strong)" />
        {quarters.map((q, i) =>
          i % xLabelEvery === 0 || i === quarters.length - 1 ? (
            <text key={`x${i}`} x={sx(qMs[i])} y={yBot + 16} textAnchor="middle" fontSize="11" fill="var(--muted)" className="num">
              {fmtQuarter(q.period_end)}
            </text>
          ) : null,
        )}

        {/* amendment diamonds on the axis */}
        {amendments.map((a) => {
          const x = sx(dateToMs(a.filed));
          if (x < M.left || x > M.left + pw) return null;
          return (
            <g key={`am${a.accession}`}>
              <rect x={x - 4.5} y={yBot - 4.5} width={9} height={9} transform={`rotate(45 ${x} ${yBot})`} fill="var(--accent)" stroke="var(--surface)" strokeWidth="1.5" />
              <title>{`${a.kind === "amendment" ? "Amendment" : "Restatement"} filed ${fmtDate(a.filed)} (${a.accession})${a.redacted ? ", redacted" : ""}`}</title>
            </g>
          );
        })}

        {/* status strip */}
        {quarters.map((q, i) => (
          <rect
            key={`s${i}`}
            x={sx(qMs[i]) - Math.min(colW * 0.42, 22)}
            width={Math.min(colW * 0.84, 44)}
            y={yBot + 26}
            height={7}
            rx={2}
            fill={q.status === "refused" ? `url(#${uid}-hatch)` : STATUS_VAR[q.status]}
            stroke={q.status === "refused" ? "var(--refused)" : "none"}
            strokeOpacity="0.5"
          />
        ))}
        <text x={M.left - 8} y={yBot + 32} textAnchor="end" fontSize="10" fill="var(--muted)">
          Status
        </text>

        {/* hit targets */}
        {quarters.map((q, i) => (
          <rect
            key={`h${i}`}
            x={sx(qMs[i]) - colW / 2}
            width={colW}
            y={yTop}
            height={ph + 36}
            fill={hover === i ? "var(--text)" : "transparent"}
            fillOpacity={hover === i ? 0.04 : 0}
            style={{ cursor: onSelect ? "pointer" : "default" }}
            tabIndex={onSelect ? 0 : -1}
            role={onSelect ? "button" : undefined}
            aria-label={`${fmtQuarter(q.period_end)}: ${STATUS_LABEL[q.status]}, ratio ${fmtRatioRange(q.ratio_low, q.ratio_high, q.status)}, threshold ${fmtRatio(q.threshold)}. Open provenance.`}
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
            onClick={() => selectAt(i)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                selectAt(i);
              }
            }}
          />
        ))}
      </svg>

      {hovered && hover !== null && (
        <div
          className="chart-tip"
          style={{
            left: Math.min(Math.max(0, sx(qMs[hover]) + 14), W - 240),
            top: M.top + 6,
          }}
        >
          <div className="between" style={{ marginBottom: 6 }}>
            <strong className="num">{fmtQuarter(hovered.period_end)}</strong>
            <span className={`chip chip-${hovered.status}`}>{STATUS_LABEL[hovered.status]}</span>
          </div>
          <div className="muted tiny" style={{ marginBottom: 6 }}>
            Period ending {fmtDate(hovered.period_end)}
          </div>
          {hovered.status === "refused" ? (
            <div className="small">
              {hoveredRefusals.length
                ? hoveredRefusals.map((r, k) => (
                    <div key={k}>
                      <strong>{reasonLabel(r.reason)}.</strong> {r.detail}
                    </div>
                  ))
                : "Not computed. No reason recorded for this quarter."}
            </div>
          ) : (
            <>
              <div className="tip-row"><span className="muted">Ratio</span><span className="num">{fmtRatioRange(hovered.ratio_low, hovered.ratio_high)}</span></div>
              <div className="tip-row"><span className="muted">Threshold ({direction})</span><span className="num">{fmtRatio(hovered.threshold)}</span></div>
              <div className="tip-row"><span className="muted">Headroom</span><span className="num">{fmtHeadroomRange(hovered.headroom_low, hovered.headroom_high)}</span></div>
              {hovered.missing.length > 0 && (
                <div className="small" style={{ marginTop: 6, color: "var(--warning)" }}>
                  Unmapped: {hovered.missing.join(", ")}
                </div>
              )}
            </>
          )}
          {disclosedFor(disclosed, hovered.period_end) !== null && (
            <div className="tip-row" style={{ marginTop: 4 }}>
              <span style={{ color: "var(--disclosed)" }}>Company reported</span>
              <span className="num">{fmtRatio(disclosedFor(disclosed, hovered.period_end))}</span>
            </div>
          )}
          {onSelect && <div className="tiny muted" style={{ marginTop: 6 }}>Click for clause and filing provenance</div>}
        </div>
      )}
    </div>
  );
}

function disclosedFor(ds: TimelineResponse["disclosed"], periodEnd: string): number | null {
  const d = ds.find((x) => x.period_end === periodEnd);
  return d ? d.reported_value : null;
}

function step2digits(ticks: number[]): number {
  if (ticks.length < 2) return 1;
  const s = Math.abs(ticks[1] - ticks[0]);
  return s >= 1 ? 1 : s >= 0.1 ? 1 : 2;
}

export function TimelineLegend({ hasEvents, hasDisclosed, hasAmendments, direction }: { hasEvents: boolean; hasDisclosed: boolean; hasAmendments: boolean; direction: "max" | "min" }) {
  return (
    <div className="legend">
      <span><i className="lg-band" />Computed ratio range</span>
      <span><i className="lg-thr" />Threshold in force</span>
      <span><i className="lg-zone" />Breach zone ({direction === "max" ? "above" : "below"} threshold)</span>
      {hasAmendments && <span><i className="lg-amd" />Amendment filed</span>}
      {hasEvents && <span><i className="lg-evt" />Disclosed waiver or default</span>}
      {hasDisclosed && <span><i className="lg-disc" />Company-reported ratio</span>}
    </div>
  );
}

export type { QuarterResult };
