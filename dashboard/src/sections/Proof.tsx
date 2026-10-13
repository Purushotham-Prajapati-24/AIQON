import { scaleLinear } from "d3-scale";
import { line, curveMonotoneX } from "d3-shape";
import { motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { EASE, ErrorNote, Reveal, SectionHead, Skeleton, Ticker } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useSize } from "../hooks/useSize";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import type { Drift as DriftT, Insights } from "../lib/types";

export function Proof() {
  const data = useAsync(() => api.insights(), []);
  const ins = data.data;
  return (
    <section id="proof" className="shell pb-10">
      <SectionHead
        id="proof"
        index="05"
        kicker="Proof"
        title={["Checked against", <span className="text-fg-3">the real cause.</span>]}
        aside={ins ? `Scored on ${ins.accuracy.n_test_shipments} shipments from a later season the model never saw.` : null}
      />
      {ins ? (
        <Body ins={ins} />
      ) : data.error ? (
        <ErrorNote error={data.error} onRetry={data.retry} />
      ) : (
        <Skeleton className="h-[900px] w-full" label="Loading the evaluation" />
      )}
    </section>
  );
}

function Body({ ins }: { ins: Insights }) {
  const o = ins.accuracy.overall;
  const h = ins.headline as Record<string, number>;
  return (
    <div className="border-t border-line">
      {/* 1 · Error */}
      <Block
        n="A"
        title="Smaller error"
        lead={
          <>
            <span className="num text-[clamp(4rem,calc(8*var(--cw)),7.5rem)] text-sea">
              −<Ticker value={h.mae_improvement_vs_B1 * 100} format={(x) => `${Math.round(x)}%`} />
            </span>
            <p className="mt-3 max-w-xs text-fg-2">average error versus assuming the delay stays as it is today</p>
          </>
        }
      >
        <Bars
          unit="h"
          rows={[
            { label: "Plan as booked", v: o.B0_schedule.mae },
            { label: "Same delay as now", v: o.B1_carry_forward.mae },
            { label: "Lane history", v: o.B2_propagation_prior.mae },
            { label: "CASCADE", v: o.cascade.mae, hi: true },
          ]}
          max={niceMax([o.B0_schedule.mae, o.B1_carry_forward.mae, o.B2_propagation_prior.mae, o.cascade.mae], 10)}
          fmt={(v) => `${v.toFixed(1)} h`}
          caption="Average error at delivery, hours"
        />
      </Block>

      {/* 2 · Convergence */}
      <Block
        n="B"
        title="Sharper as it goes"
        lead={<p className="max-w-xs text-[1.15rem] text-fg-2">Error shrinks as milestones come in. The bump is the hub, where connections are made or missed.</p>}
      >
        <Convergence ins={ins} />
      </Block>

      {/* 3 · Ranges + cause */}
      <div className="grid border-b border-line lg:grid-cols-2">
        <div className="py-14 lg:pr-12">
          <Head n="C" title="Ranges you can trust" />
          <div className="mt-6 flex items-end gap-4">
            <span className="num text-[clamp(3.5rem,calc(6*var(--cw)),5.5rem)]">
              <Ticker value={ins.accuracy.coverage_p10_p90.overall * 100} format={(x) => `${Math.round(x)}%`} />
            </span>
            <span className="mb-2 max-w-[14rem] text-fg-2">of actual delays landed inside the likely range (aim: 80%)</span>
          </div>
          <Bars
            unit="%"
            rows={[
              { label: "Before sailing", v: ins.accuracy.coverage_p10_p90.pre_departure * 100 },
              { label: "At sea", v: ins.accuracy.coverage_p10_p90.at_sea * 100 },
              { label: "In port", v: ins.accuracy.coverage_p10_p90.at_port * 100 },
              { label: "After customs", v: ins.accuracy.coverage_p10_p90.post_customs * 100 },
            ]}
            max={100}
            target={80}
            fmt={(v) => `${Math.round(v)}%`}
            neutral
          />
        </div>
        <div className="border-line py-14 lg:border-l lg:pl-12">
          <Head n="D" title="Blames the right stage" />
          <div className="mt-6 flex items-end gap-4">
            <span className="num text-[clamp(3.5rem,calc(6*var(--cw)),5.5rem)]">
              <Ticker value={ins.attribution.accuracy.shap_top2 * 100} format={(x) => `${Math.round(x)}%`} />
            </span>
            <span className="mb-2 max-w-[14rem] text-fg-2">true cause is in its top two, checked against the simulator’s record</span>
          </div>
          <Bars
            unit="%"
            rows={[
              { label: "CASCADE · top two", v: ins.attribution.accuracy.shap_top2 * 100, hi: true },
              { label: "CASCADE · first pick", v: ins.attribution.accuracy.shap_top1 * 100, hi: true },
              { label: "Lane history guess", v: ins.attribution.accuracy.lane_prior_top1 * 100 },
              { label: "Random guess", v: ins.attribution.accuracy.random_top1 * 100 },
            ]}
            max={100}
            fmt={(v) => `${Math.round(v)}%`}
          />
        </div>
      </div>

      {/* 4 · Propagation */}
      <Block
        n="E"
        title="Where delay grows"
        lead={<p className="max-w-xs text-[1.15rem] text-fg-2">One extra hour late at each step becomes this many hours at the door.</p>}
      >
        <Multipliers ins={ins} />
      </Block>

      <Drift />

      <Reveal className="grid gap-6 py-14 md:grid-cols-12">
        <p className="eyebrow md:col-span-3">Honest limits</p>
        <ul className="space-y-3 text-[1.05rem] text-fg-2 md:col-span-9">
          <li>Trained and tested on simulated shipments with a known cause for every hour of delay. Not yet on real carrier data.</li>
          {ins.headline.shrink === 0 && (
            <li>
              The point forecast is the operator rulebook's projection: the learned correction did not beat it on
              validation, so it is switched off (λ = 0). The learned models supply the chance of being late and the
              ranges.
            </li>
          )}
          <li>Naming the cause first time is the weakest result ({Math.round(ins.attribution.accuracy.shap_top1 * 100)}%). The top two is the number to use.</li>
        </ul>
      </Reveal>
    </div>
  );
}

/** Round a chart maximum up to a clean step so bars never overflow when the data grows. */
const niceMax = (vals: number[], step: number) => Math.max(step, Math.ceil((Math.max(...vals) * 1.08) / step) * step);

function Head({ n, title }: { n: string; title: string }) {
  return (
    <h3 className="flex items-center gap-3">
      <span className="font-mono text-[0.78rem] text-late" aria-hidden>
        {n}
      </span>
      <span className="font-display text-[2rem] font-extrabold uppercase leading-none">{title}</span>
    </h3>
  );
}

function Block({ n, title, lead, children }: { n: string; title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-10 border-b border-line py-14 lg:grid-cols-12">
      <Reveal className="lg:col-span-4">
        <Head n={n} title={title} />
        <div className="mt-6">{lead}</div>
      </Reveal>
      <Reveal delay={0.1} className="lg:col-span-8">
        {children}
      </Reveal>
    </div>
  );
}

/** Horizontal bars. Highlighted rows carry the accent; everything else stays neutral. */
function Bars({
  rows,
  max,
  fmt,
  target,
  caption,
  neutral,
}: {
  rows: { label: string; v: number; hi?: boolean }[];
  max: number;
  fmt: (v: number) => string;
  unit: string;
  target?: number;
  caption?: string;
  neutral?: boolean;
}) {
  return (
    <figure className="mt-8">
      <ul className="space-y-4">
        {rows.map((r, k) => (
          <li key={r.label} className="grid grid-cols-[9.5rem_minmax(0,1fr)_4.5rem] items-center gap-4 sm:grid-cols-[11rem_minmax(0,1fr)_5rem]">
            <span className={r.hi ? "font-medium text-fg" : "text-fg-2"}>{r.label}</span>
            <span className="relative h-8">
              <motion.span
                className="absolute inset-y-1 left-0 rounded-r-[4px]"
                style={{ background: r.hi ? "var(--sea)" : "var(--fg-3)", opacity: r.hi || neutral ? 1 : 0.55 }}
                initial={{ width: 0 }}
                whileInView={{ width: `${(r.v / max) * 100}%` }}
                viewport={{ once: true }}
                transition={{ duration: 1, ease: EASE, delay: k * 0.08 }}
              />
              {target !== undefined && (
                <span className="absolute -inset-y-1 w-px border-l border-dashed border-fg" style={{ left: `${(target / max) * 100}%` }} />
              )}
            </span>
            <span className={`text-right font-mono ${r.hi ? "text-sea" : "text-fg-2"}`}>{fmt(r.v)}</span>
          </li>
        ))}
      </ul>
      {(caption || target !== undefined) && (
        <figcaption className="mt-4 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
          {caption ?? `Dashed line: ${target}% aim`}
        </figcaption>
      )}
    </figure>
  );
}

const CP = ["Booked", "Container in", "Sailed", "Hub in", "Hub out", "Port in", "Unloaded", "Cleared", "Gate out"];
const CP_SHORT = ["Book", "In", "Sail", "Hub", "Hub→", "Port", "Unld", "Clr", "Out"];

/** Error by milestone: CASCADE vs "same delay as now". Two series, one axis, direct labels. */
function Convergence({ ins }: { ins: Insights }) {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = ins.accuracy.by_checkpoint_mae;
  const series = [
    { key: "B1_carry_forward", label: "Same delay as now", color: "var(--fg-3)", w: 2, dash: "5 5" },
    { key: "cascade", label: "CASCADE", color: "var(--sea)", w: 3, dash: undefined },
  ].map((s) => ({ ...s, pts: CP.map((_, i) => m[s.key]?.[String(i)] ?? 0) }));

  const H = 340;
  const W = Math.max(width, 320);
  const M = { t: 20, r: width < 640 ? 16 : 150, b: 54, l: 44 };
  const x = scaleLinear().domain([0, CP.length - 1]).range([M.l, W - M.r]);
  const top = niceMax(series.flatMap((s) => s.pts), 20);
  const y = scaleLinear().domain([0, top]).range([H - M.b, M.t]);
  const ticks = Array.from({ length: top / 20 + 1 }, (_, k) => k * 20);
  // Pick the label set that fits: full names need ~84 px per milestone, short ones ~34 px.
  const gap = (W - M.l - M.r) / (CP.length - 1);
  const labels = gap >= 84 ? CP : gap >= 34 ? CP_SHORT : CP_SHORT.map((c, i) => (i % 2 ? "" : c));
  const cas = series[1].pts;
  const b1 = series[0].pts;
  const alt = `Average error by milestone. CASCADE falls from ${Math.round(cas[0])} hours at booking to ${cas[cas.length - 1].toFixed(1)} hours at gate out; "same delay as now" goes from ${Math.round(b1[0])} to ${b1[b1.length - 1].toFixed(1)} hours. The largest error for both is at the hub.`;
  const path = (pts: number[]) =>
    line<number>()
      .x((_, i) => x(i))
      .y((v) => y(v))
      .curve(curveMonotoneX)(pts) ?? "";

  return (
    <div ref={ref} className="relative">
      <ul className="mb-4 flex gap-6 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
        {series.map((s) => (
          <li key={s.key} className="flex items-center gap-2">
            <span className="w-6 border-t-2" style={{ borderColor: s.color, borderStyle: s.dash ? "dashed" : "solid" }} />
            {s.label}
          </li>
        ))}
      </ul>
      {width > 0 && (
        <svg
          width={W}
          height={H}
          className="block"
          onPointerMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const i = Math.round(x.invert(e.clientX - r.left));
            setHover(i >= 0 && i < CP.length ? i : null);
          }}
          onPointerLeave={() => setHover(null)}
          role="img"
          aria-label={alt}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="var(--line)" />
              <text x={M.l - 10} y={y(t) + 4} textAnchor="end" className="fill-fg-3 font-mono text-[12px]">
                {t}h
              </text>
            </g>
          ))}
          {CP.map((c, i) => (
            <text key={c} x={x(i)} y={H - M.b + 26} textAnchor="middle" className={`font-mono text-[12px] uppercase ${hover === i ? "fill-fg" : "fill-fg-3"}`}>
              {labels[i]}
            </text>
          ))}
          {series.map((s) => (
            <g key={s.key}>
              <motion.path
                d={path(s.pts)}
                fill="none"
                stroke={s.color}
                strokeWidth={s.w}
                strokeDasharray={s.dash}
                strokeLinecap="round"
                initial={{ pathLength: 0 }}
                whileInView={{ pathLength: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 1.6, ease: EASE }}
              />
              {width >= 640 && (
                <text x={x(CP.length - 1) + 12} y={y(s.pts[s.pts.length - 1]) + 4} className="font-mono text-[12px]" style={{ fill: s.color }}>
                  {s.label}
                </text>
              )}
            </g>
          ))}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="var(--fg-3)" strokeDasharray="2 3" />
              {series.map((s) => (
                <circle key={s.key} cx={x(hover)} cy={y(s.pts[hover])} r={5} fill={s.color} stroke="var(--bg)" strokeWidth={2} />
              ))}
            </g>
          )}
        </svg>
      )}
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-10 z-10 w-52 rounded-md border border-line-2 bg-bg-2 p-3 font-mono text-[12px]"
          style={{ left: Math.min(Math.max(x(hover) + 12, 0), W - 216) }}
        >
          <div className="mb-1.5 font-sans text-sm font-medium">{CP[hover]}</div>
          {[...series].reverse().map((s) => (
            <div key={s.key} className="flex justify-between">
              <span style={{ color: s.color }}>{s.label}</span>
              <span>{s.pts[hover].toFixed(1)} h</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Predicted vs true multiplier per step. Reference line at 1× = delay neither grows nor shrinks. */
function Multipliers({ ins }: { ins: Insights }) {
  const names: Record<string, string> = {
    DEPART_ORIGIN: "Leaving origin",
    ARRIVE_TS: "Reaching the hub",
    ARRIVE_DEST_PORT: "Reaching the port",
    DISCHARGED: "Unloading",
  };
  const order = ["DEPART_ORIGIN", "ARRIVE_TS", "ARRIVE_DEST_PORT", "DISCHARGED"];
  const vals = order.flatMap((e) => (ins.propagation.by_event[e] ? [ins.propagation.by_event[e].phi_hat, ins.propagation.by_event[e].phi_true] : []));
  const max = Math.max(2.6, Math.ceil(Math.max(...vals, 0) * 1.15 * 5) / 5);
  const pos = (v: number) => `${(Math.min(Math.max(v, 0), max) / max) * 100}%`;
  return (
    <figure>
      <ul className="mb-6 flex flex-wrap gap-6 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
        <li className="flex items-center gap-2">
          <span className="size-3 rounded-full bg-sea" /> CASCADE estimate
        </li>
        <li className="flex items-center gap-2">
          <span className="size-3 rounded-full border-2 border-fg" /> True (re-simulated)
        </li>
      </ul>
      <ul className="space-y-6">
        {order.map((e, k) => {
          const d = ins.propagation.by_event[e];
          if (!d) return null;
          const grow = d.phi_hat > 1;
          return (
            <li key={e} className="grid grid-cols-[9.5rem_minmax(0,1fr)_4rem] items-center gap-4 sm:grid-cols-[11rem_minmax(0,1fr)_5rem]">
              <span className="text-fg-2">{names[e]}</span>
              <span className="relative h-8">
                <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                <span className="absolute -inset-y-1 border-l border-dashed border-fg-3" style={{ left: pos(1) }} />
                <motion.span
                  className="absolute top-1/2 h-[3px] -translate-y-1/2"
                  style={{ background: grow ? "var(--late)" : "var(--ok)", opacity: 0.5 }}
                  initial={{ left: pos(1), width: 0 }}
                  whileInView={{ left: pos(Math.min(1, d.phi_hat)), width: `${(Math.abs(d.phi_hat - 1) / max) * 100}%` }}
                  viewport={{ once: true }}
                  transition={{ duration: 1, ease: EASE, delay: k * 0.08 }}
                />
                <span className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-fg bg-bg" style={{ left: pos(d.phi_true) }} title={`True ${d.phi_true.toFixed(2)}×`} />
                <motion.span
                  className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sea"
                  initial={{ left: pos(1) }}
                  whileInView={{ left: pos(d.phi_hat) }}
                  viewport={{ once: true }}
                  transition={{ duration: 1, ease: EASE, delay: k * 0.08 }}
                />
              </span>
              <span className={`text-right font-mono ${grow ? "text-late" : "text-ok"}`}>{d.phi_hat.toFixed(1)}×</span>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 grid grid-cols-[9.5rem_minmax(0,1fr)_4rem] gap-4 font-mono text-[0.75rem] uppercase tracking-[0.12em] text-fg-3 sm:grid-cols-[11rem_minmax(0,1fr)_5rem]">
        <span />
        <span className="relative h-4">
          <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: pos(1) }}>
            1×<span className="hidden sm:inline"> · no change</span>
          </span>
          <span className="absolute left-0 hidden sm:inline">shrinks</span>
          <span className="absolute right-0 hidden sm:inline">grows</span>
        </span>
      </div>
    </figure>
  );
}

const DRIFT_NAMES: Record<string, string> = {
  current_delay_h: "Delay so far",
  rho_dest_fcst: "Arrival-port congestion",
  rho_hub_fcst: "Hub congestion",
  weather_fcst_remaining: "Weather ahead",
  overdue_h: "Overdue milestones",
  ts_buffer_remaining_h: "Connection buffer",
  n_missing_past: "Missing reports",
  hours_since_last_event: "Time since last update",
};
const DRIFT_TONE = { stable: "var(--ok-ink)", watch: "var(--risk-ink)", drift: "var(--late-ink)" } as const;

/** Live inputs vs the training data (PSI). Shown openly: drift is why the ranges are drift-calibrated. */
function Drift() {
  const { mode } = useStore();
  const data = useAsync(() => api.drift(), [mode]);
  const d: DriftT | null | undefined = data.data;
  if (!d) return null;
  const feats = Object.entries(d.features).sort((a, b) => b[1].psi - a[1].psi);
  const shifted = feats.filter(([, f]) => f.status === "drift").length;
  return (
    <Reveal className="grid gap-6 border-b border-line py-14 md:grid-cols-12">
      <div className="md:col-span-3">
        <h3 className="eyebrow">{mode === "live" ? "Live drift check" : "Drift check · recorded run"}</h3>
        <p className="mt-3 text-fg-2">
          {shifted} of {feats.length} inputs have shifted since training. Expected here: the test season is the Q4 peak, which is why
          the ranges are calibrated on later data.
        </p>
      </div>
      <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2 md:col-span-9">
        {feats.map(([k, f]) => (
          <li key={k} className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
            <span className="text-fg-2">{DRIFT_NAMES[k] ?? k.replace(/_/g, " ")}</span>
            <span className="font-mono text-[0.85rem]" style={{ color: DRIFT_TONE[f.status] }}>
              {f.status} · PSI {f.psi.toFixed(2)}
            </span>
          </li>
        ))}
      </ul>
      <p className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg-3 md:col-span-9 md:col-start-4">
        {d.rule} · {d.n} live predictions
      </p>
    </Reveal>
  );
}
