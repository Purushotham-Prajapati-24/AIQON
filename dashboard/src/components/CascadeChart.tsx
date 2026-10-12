import { scaleLinear } from "d3-scale";
import { area, curveStep, line } from "d3-shape";
import { AnimatePresence, motion } from "motion/react";
import { useId, useMemo, useState } from "react";
import { useSize } from "../hooks/useSize";
import { EVENT, GROUP, dateTime, delay, hoursBetween, port } from "../lib/format";
import type { Group, ShipmentView } from "../lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;

export interface Node {
  event: string;
  planned: string;
  at: string | null;
  kind: "actual" | "predicted" | "missing";
  delay: number; // hours vs plan (interpolated when missing)
}

/** Delay (hours vs plan) at every milestone: reported where known, predicted ahead, interpolated gaps. */
export function nodesOf(v: ShipmentView): Node[] {
  const raw = v.timeline.map((t) => {
    const at = t.observed ?? t.projected;
    return {
      event: t.event,
      planned: t.planned,
      at,
      kind: (t.observed ? "actual" : t.projected ? "predicted" : "missing") as Node["kind"],
      delay: at ? hoursBetween(t.planned, at) : NaN,
    };
  });
  for (let i = 0; i < raw.length; i++) {
    if (!Number.isNaN(raw[i].delay)) continue;
    let p = i - 1;
    while (p >= 0 && Number.isNaN(raw[p].delay)) p--;
    let n = i + 1;
    while (n < raw.length && Number.isNaN(raw[n].delay)) n++;
    const a = p >= 0 ? raw[p].delay : 0;
    const b = n < raw.length ? raw[n].delay : a;
    const ia = p >= 0 ? p : -1;
    raw[i].delay = a + ((b - a) * (i - ia)) / (n - ia);
  }
  return raw;
}

/** Stage spans on the milestone axis, for highlighting the main cause. */
function span(group: Group | null, events: string[]): [number, number] | null {
  const at = (e: string) => events.indexOf(e);
  const hub = at("ARRIVE_TS") >= 0;
  const m: Record<Group, [string, string]> = {
    ORIGIN: ["GATE_IN_ORIGIN", "DEPART_ORIGIN"],
    OCEAN: [hub ? "DEPART_TS" : "DEPART_ORIGIN", "ARRIVE_DEST_PORT"],
    TRANSSHIPMENT: ["ARRIVE_TS", "DEPART_TS"],
    PORT: ["ARRIVE_DEST_PORT", "DISCHARGED"],
    CUSTOMS: ["DISCHARGED", "CUSTOMS_CLEARED"],
    INLAND: ["CUSTOMS_CLEARED", "DELIVERED"],
  };
  if (!group || !m[group]) return null;
  const [a, b] = m[group].map(at);
  return a >= 0 && b >= 0 ? [a, b] : null;
}

export function CascadeChart({
  view,
  ghosts = [],
  yMax,
  height = 420,
  compact = false,
}: {
  view: ShipmentView;
  ghosts?: ShipmentView[];
  yMax?: number;
  height?: number;
  compact?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const [ref, { width }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const nodes = useMemo(() => nodesOf(view), [view]);
  const events = nodes.map((n) => n.event);
  const lastActual = nodes.reduce((acc, n, i) => (n.kind === "actual" ? i : acc), -1);
  const { p10, p50, p90 } = view.delay_hours;
  const s = view.shipment;

  const narrow = width > 0 && width < 600;
  const M = { t: 56, r: compact ? 24 : narrow ? 80 : 150, b: narrow ? 74 : 70, l: narrow ? 54 : 56 };
  const W = narrow ? width : Math.max(width, 640);
  const lo = Math.min(-18, ...nodes.map((n) => n.delay), p10);
  const hi = Math.max(yMax ?? 0, p90, ...nodes.map((n) => n.delay)) * 1.04;
  const x = scaleLinear().domain([0, nodes.length - 1]).range([M.l, W - M.r]);
  const y = scaleLinear().domain([lo, hi]).range([M.t, height - M.b]);
  const step = x(1) - x(0);

  const pathOf = (ns: Node[]) =>
    line<Node>()
      .x((_, i) => x(i))
      .y((n) => y(n.delay))
      .curve(curveStep)(ns) ?? "";
  const areaOf = (ns: Node[]) =>
    area<Node>()
      .x((_, i) => x(i))
      .y0(y(0))
      .y1((n) => y(n.delay))
      .curve(curveStep)(ns) ?? "";

  const d = pathOf(nodes);
  const fill = areaOf(nodes);
  const splitX = lastActual >= 0 ? x(lastActual) + step / 2 : M.l;
  const cause = span(view.root_cause_group, events);
  const tickStep = hi > 200 ? 48 : 24;
  const dayTicks = Array.from({ length: Math.floor(hi / tickStep) + 1 }, (_, i) => i * tickStep);

  const label = (e: string) => {
    const L = EVENT[e];
    return L ? L.long(port(s.hub), port(s.dest), port(s.origin)) : e;
  };
  const portUnder: Record<string, string> = {
    GATE_IN_ORIGIN: port(s.origin),
    ARRIVE_TS: port(s.hub),
    ARRIVE_DEST_PORT: port(s.dest),
  };

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(x.invert(px));
    setHover(i >= 0 && i < nodes.length ? i : null);
  };

  const h = hover !== null ? nodes[hover] : null;

  return (
    <div ref={ref} className="relative w-full overflow-x-auto overflow-y-hidden [scrollbar-width:thin]">
      {width > 0 && (
        <svg
          width={W}
          height={height}
          viewBox={`0 0 ${W} ${height}`}
          className="block select-none"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          role="img"
          aria-label={`Delay by milestone for ${view.shipment_id}: expected ${delay(p50)} at delivery, likely ${delay(p10)} to ${delay(p90)}.`}
        >
          <defs>
            <pattern id={`hatch-${uid}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="7" height="7" fill="var(--late)" opacity="0.06" />
              <line x1="0" y1="0" x2="0" y2="7" stroke="var(--late)" strokeWidth="2.2" opacity="0.38" />
            </pattern>
            <linearGradient id={`solid-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--late)" stopOpacity="0.15" />
              <stop offset="1" stopColor="var(--late)" stopOpacity="0.55" />
            </linearGradient>
            <clipPath id={`past-${uid}`}>
              <motion.rect initial={false} animate={{ width: Math.max(0, splitX) }} transition={{ duration: 1, ease: EASE }} x={0} y={0} height={height} />
            </clipPath>
            <clipPath id={`future-${uid}`}>
              <motion.rect initial={false} animate={{ x: splitX }} transition={{ duration: 1, ease: EASE }} y={0} width={W} height={height} />
            </clipPath>
          </defs>

          {/* grid: days late */}
          {dayTicks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeDasharray={t === 0 ? undefined : "1 5"} />
              <text x={M.l - 12} y={y(t) + 4} textAnchor="end" className="fill-fg-3 font-mono text-[11px]">
                {t === 0 ? "plan" : `+${t / 24}d`}
              </text>
            </g>
          ))}

          {/* main cause band */}
          <AnimatePresence>
            {cause && (
              <motion.g key="cause" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.5 }}>
                <motion.rect
                  initial={false}
                  animate={{ x: x(cause[0]), width: x(cause[1]) - x(cause[0]) }}
                  transition={{ duration: 1, ease: EASE }}
                  y={M.t - 30}
                  height={height - M.b - M.t + 30}
                  fill="var(--late-wash)"
                />
                <motion.text
                  initial={false}
                  animate={{ x: (x(cause[0]) + x(cause[1])) / 2 }}
                  transition={{ duration: 1, ease: EASE }}
                  y={M.t - 12}
                  textAnchor="middle"
                  className="fill-late font-mono text-[11px] uppercase tracking-[0.14em]"
                >
                  Main cause · {GROUP[view.root_cause_group as Group]}
                </motion.text>
              </motion.g>
            )}
          </AnimatePresence>

          {/* earlier forecasts, faint */}
          {ghosts.map((g, i) => (
            <path key={i} d={pathOf(nodesOf(g))} fill="none" stroke="var(--fg-3)" strokeOpacity={0.35} strokeWidth={1} strokeDasharray="3 4" />
          ))}

          {/* delay mass: solid where it already happened, hatched where it is predicted */}
          <motion.path initial={false} animate={{ d: fill }} transition={{ duration: 1, ease: EASE }} fill={`url(#solid-${uid})`} clipPath={`url(#past-${uid})`} />
          <motion.path initial={false} animate={{ d: fill }} transition={{ duration: 1, ease: EASE }} fill={`url(#hatch-${uid})`} clipPath={`url(#future-${uid})`} />
          <motion.path initial={false} animate={{ d }} transition={{ duration: 1, ease: EASE }} fill="none" stroke="var(--late)" strokeWidth={2.5} strokeLinejoin="round" clipPath={`url(#past-${uid})`} />
          <motion.path initial={false} animate={{ d }} transition={{ duration: 1, ease: EASE }} fill="none" stroke="var(--late)" strokeWidth={2} strokeDasharray="6 5" clipPath={`url(#future-${uid})`} />

          {/* plan line */}
          <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} stroke="var(--fg-2)" strokeWidth={1.25} />

          {/* milestones */}
          {nodes.map((n, i) => (
            <g key={n.event}>
              <line x1={x(i)} x2={x(i)} y1={height - M.b + 8} y2={height - M.b + 14} stroke="var(--line-2)" />
              <motion.circle
                initial={false}
                animate={{ cy: y(n.delay) }}
                transition={{ duration: 1, ease: EASE }}
                cx={x(i)}
                r={hover === i ? 6 : 4.5}
                fill={n.kind === "actual" ? "var(--late)" : "var(--bg)"}
                stroke={n.kind === "missing" ? "var(--fg-3)" : "var(--late)"}
                strokeWidth={2}
                strokeDasharray={n.kind === "missing" ? "2 2" : undefined}
              />
              <text
                x={x(i)}
                y={height - M.b + (narrow ? 24 : 32)}
                textAnchor={narrow ? "end" : "middle"}
                transform={narrow ? `rotate(-40 ${x(i)} ${height - M.b + 24})` : undefined}
                className={`font-mono text-[11px] uppercase tracking-wider ${hover === i ? "fill-fg" : "fill-fg-2"}`}
              >
                {EVENT[n.event]?.short ?? n.event}
              </text>
              {!narrow && portUnder[n.event] && (
                <text x={x(i)} y={height - M.b + 50} textAnchor="middle" className="fill-fg-3 text-[11px]">
                  {portUnder[n.event]}
                </text>
              )}
            </g>
          ))}

          {/* the vessel: where the shipment is now */}
          {lastActual >= 0 && (
            <motion.g initial={false} animate={{ x: x(lastActual), y: y(nodes[lastActual].delay) }} transition={{ duration: 1, ease: EASE }}>
              <circle r={9} fill="none" stroke="var(--late)" strokeWidth={1.5} style={{ transformOrigin: "0 0", animation: "ping-soft 2.2s ease-out infinite" }} />
              <circle r={6.5} fill="var(--fg)" stroke="var(--bg)" strokeWidth={2.5} />
            </motion.g>
          )}

          {/* likely range at delivery */}
          {!compact && (
            <motion.g initial={false} animate={{ x: x(nodes.length - 1) }} transition={{ duration: 1, ease: EASE }}>
              <motion.line initial={false} animate={{ y1: y(p10), y2: y(p90) }} transition={{ duration: 1, ease: EASE }} x1={narrow ? 14 : 22} x2={narrow ? 14 : 22} stroke="var(--late)" strokeWidth={6} strokeLinecap="round" strokeOpacity={0.35} />
              <motion.circle initial={false} animate={{ cy: y(p50) }} transition={{ duration: 1, ease: EASE }} cx={narrow ? 14 : 22} r={5} fill="var(--late)" />
              <motion.text initial={false} animate={{ y: y(p50) + 4 }} transition={{ duration: 1, ease: EASE }} x={narrow ? 24 : 36} className="fill-fg font-mono text-[12px]">
                {delay(p50, { short: true })}
              </motion.text>
              <motion.text initial={false} animate={{ y: y(p90) + 4 }} transition={{ duration: 1, ease: EASE }} x={narrow ? 24 : 36} className="fill-fg-3 font-mono text-[11px]">
                {delay(p90, { short: true })}
              </motion.text>
              <motion.text initial={false} animate={{ y: y(p10) + 4 }} transition={{ duration: 1, ease: EASE }} x={narrow ? 24 : 36} className="fill-fg-3 font-mono text-[11px]">
                {delay(p10, { short: true })}
              </motion.text>
            </motion.g>
          )}

          {/* hover crosshair */}
          {h && hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={M.t - 30} y2={height - M.b} stroke="var(--fg-3)" strokeDasharray="2 3" />
            </g>
          )}
        </svg>
      )}

      {/* tooltip */}
      <AnimatePresence>
        {h && hover !== null && (
          <motion.div
            key="tip"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="pointer-events-none absolute z-10 w-60 rounded-md border border-line-2 bg-bg-2 p-3.5 text-sm shadow-[0_18px_40px_-20px_rgb(0_0_0/0.6)]"
            style={{
              left: Math.min(Math.max(x(hover) - 120, 8), W - 248),
              top: Math.max(8, Math.min(y(h.delay) + 18, height - 180)),
            }}
          >
            <div className="font-medium">{label(h.event)}</div>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[12px]">
              <dt className="text-fg-3">Plan</dt>
              <dd>{dateTime(h.planned)}</dd>
              <dt className="text-fg-3">{h.kind === "actual" ? "Actual" : h.kind === "predicted" ? "Predicted" : "Status"}</dt>
              <dd>{h.at ? dateTime(h.at) : "Not reported"}</dd>
              {h.kind !== "missing" && (
                <>
                  <dt className="text-fg-3">Delay</dt>
                  <dd className={h.delay > 0.5 ? "text-late" : "text-ok"}>{delay(h.delay)}</dd>
                </>
              )}
            </dl>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
