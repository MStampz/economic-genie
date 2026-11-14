// Small hand-built SVG charts. Colours come from CSS variables: --c1..--c8 are the categorical
// slots (a budget post keeps its slot everywhere), --c0 is the neutral "not in a budget" grey.
import { useEffect, useRef, useState } from "react";
import { money, money0, type DayLine, type PostLine } from "../api";

export const postColor = (slot: number) => `var(--c${slot})`;

const shortDate = (s: string) => new Date(s + "T00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short" });
const longDate = (s: string) => new Date(s + "T00:00").toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** Running total (area) over the period, with daily spend as stacked bars underneath. */
function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function SpendChart({ days, posts, onDay }: { days: DayLine[]; posts: PostLine[]; onDay?: (d: string) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  // Drawn at the real pixel width, so text stays readable on a phone.
  const [ref, width] = useWidth<HTMLDivElement>(640);
  const W = Math.max(width, 280), H1 = W < 500 ? 120 : 150, H2 = W < 500 ? 56 : 70, GAP = 26, PADL = 44, PADR = 8, TOP = 8;
  const n = Math.max(days.length, 1);
  const step = (W - PADL - PADR) / n;
  let run = 0;
  const cum = days.map((d) => (run += Math.max(Number(d.total), 0)));
  const maxCum = niceMax(Math.max(...cum, 0));
  const maxDay = niceMax(Math.max(...days.map((d) => Math.max(Number(d.total), 0)), 0));
  const x = (i: number) => PADL + step * i + step / 2;
  const y1 = (v: number) => TOP + H1 - (v / maxCum) * H1;
  const base2 = TOP + H1 + GAP + H2;
  const color = new Map(posts.map((p) => [p.id, postColor(p.color)]));
  const order = posts.map((p) => p.id);
  const line = cum.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y1(v).toFixed(1)}`).join("");
  const area = days.length ? `${line}L${x(days.length - 1)},${TOP + H1}L${x(0)},${TOP + H1}Z` : "";
  const bw = Math.max(Math.min(step - 2, 18), 2);
  const tickEvery = Math.ceil(n / (W < 500 ? 4 : 6));
  const h = hover !== null ? days[hover] : null;

  return (
    <div className="chart-wrap" ref={ref}>
      <svg viewBox={`0 0 ${W} ${base2 + 20}`} className="chart" role="img" aria-label="Running total and daily spending"
        onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--c3)" stopOpacity="0.35" />
            <stop offset="1" stopColor="var(--c3)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PADL} x2={W - PADR} y1={y1(maxCum * f)} y2={y1(maxCum * f)} className="grid" />
            {f > 0 && <text x={PADL - 6} y={y1(maxCum * f) + 4} className="axis" textAnchor="end">{money0(maxCum * f)}</text>}
          </g>
        ))}
        <path d={area} fill="url(#areaFill)" />
        <path d={line} fill="none" stroke="var(--c3)" strokeWidth="2" strokeLinejoin="round" />
        {cum.length > 0 && <circle cx={x(cum.length - 1)} cy={y1(cum[cum.length - 1])} r="4" fill="var(--c3)" stroke="var(--bg)" strokeWidth="2" />}
        <text x={PADL - 6} y={base2 - H2 + 4} className="axis" textAnchor="end">{money0(maxDay)}</text>
        <line x1={PADL} x2={W - PADR} y1={base2} y2={base2} className="grid" />
        {days.map((d, i) => {
          let yy = base2;
          const parts = order.filter((k) => Number(d.by_post[k] ?? 0) > 0);
          return (
            <g key={d.date}>
              {parts.map((k, j) => {
                const hgt = (Number(d.by_post[k]) / maxDay) * H2;
                const top = yy - hgt;
                yy = top - (j < parts.length - 1 ? 1 : 0);
                return <rect key={k} x={x(i) - bw / 2} y={top} width={bw} height={Math.max(hgt - 1, 0.5)} rx={j === parts.length - 1 ? 2 : 0} fill={color.get(k) ?? "var(--c0)"} />;
              })}
              {i % tickEvery === 0 && <text x={x(i)} y={base2 + 14} className="axis" textAnchor="middle">{shortDate(d.date)}</text>}
            </g>
          );
        })}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={TOP} y2={base2} className="crosshair" />}
        {days.map((d, i) => (
          <rect key={d.date} x={PADL + step * i} y={0} width={step} height={base2} fill="transparent"
            onMouseEnter={() => setHover(i)} onClick={() => onDay?.(d.date)} style={{ cursor: onDay ? "pointer" : undefined }} />
        ))}
      </svg>
      {h && hover !== null && (
        <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <b>{longDate(h.date)}</b>
          <div>Spent that day <span>{money(h.total)}</span></div>
          <div>Running total <span>{money(cum[hover])}</span></div>
        </div>
      )}
    </div>
  );
}

/** Donut of spending by budget post. */
export function Donut({ posts, total, selected, onSelect }: {
  posts: PostLine[]; total: string; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const parts = posts.filter((p) => Number(p.spent) > 0);
  const sum = parts.reduce((a, p) => a + Number(p.spent), 0) || 1;
  const R = 70, r = 50, C = 90;
  let a0 = -Math.PI / 2;
  const sel = parts.find((p) => p.id === selected);
  return (
    <svg viewBox="0 0 180 180" className="donut" role="img" aria-label="Spending by budget post">
      {parts.map((p) => {
        const frac = Number(p.spent) / sum;
        const a1 = a0 + frac * Math.PI * 2;
        const gap = parts.length > 1 ? 0.012 : 0;
        const s = a0 + gap, e = Math.max(a1 - gap, s + 0.001);
        const large = e - s > Math.PI ? 1 : 0;
        const pt = (rad: number, ang: number) => `${C + rad * Math.cos(ang)},${C + rad * Math.sin(ang)}`;
        const d = frac >= 0.999
          ? `M${C},${C - R}A${R},${R} 0 1 1 ${C - 0.01},${C - R}L${C - 0.01},${C - r}A${r},${r} 0 1 0 ${C},${C - r}Z`
          : `M${pt(R, s)}A${R},${R} 0 ${large} 1 ${pt(R, e)}L${pt(r, e)}A${r},${r} 0 ${large} 0 ${pt(r, s)}Z`;
        a0 = a1;
        return (
          <path key={p.id} d={d} fill={postColor(p.color)} opacity={selected && selected !== p.id ? 0.3 : 1}
            onClick={() => onSelect(selected === p.id ? null : p.id)} style={{ cursor: "pointer" }}>
            <title>{p.name}: {money(p.spent)}</title>
          </path>
        );
      })}
      <text x={C} y={C - 2} textAnchor="middle" className="donut-total">{money0(sel ? sel.spent : total)}</text>
      <text x={C} y={C + 16} textAnchor="middle" className="donut-sub">{sel ? sel.name.slice(0, 22) : "All spending"}</text>
    </svg>
  );
}

/** Calendar heatmap: darker = more spent. Weeks start on Monday. */
export function Calendar({ days, selected, onSelect }: { days: DayLine[]; selected: string | null; onSelect: (d: string | null) => void }) {
  if (!days.length) return null;
  const max = Math.max(...days.map((d) => Number(d.total)), 1);
  const first = new Date(days[0].date + "T00:00");
  const lead = (first.getDay() + 6) % 7;
  const cells: (DayLine | null)[] = [...Array(lead).fill(null), ...days];
  return (
    <div className="calendar">
      {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="cal-head">{d}</div>)}
      {cells.map((d, i) => {
        if (!d) return <div key={i} />;
        const v = Math.max(Number(d.total), 0);
        const level = v === 0 ? 0 : Math.min(5, Math.ceil((v / max) * 5));
        return (
          <button key={d.date} className={`cal-cell l${level} ${selected === d.date ? "sel" : ""}`}
            title={`${longDate(d.date)}: ${money(d.total)}`} onClick={() => onSelect(selected === d.date ? null : d.date)}>
            {new Date(d.date + "T00:00").getDate()}
          </button>
        );
      })}
    </div>
  );
}
