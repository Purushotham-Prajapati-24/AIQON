import { AnimatePresence, motion, useInView, useReducedMotion } from "motion/react";
import { ArrowDown, Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CascadeChart } from "../components/CascadeChart";
import { Contours } from "../components/Contours";
import { ChartLegend, EASE, ErrorNote, HowTo, Skeleton, Ticker } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { GROUP, checkpointLabel, day, dayLong, port, signed } from "../lib/format";
import { HERO_SHIPMENT, useStore } from "../lib/store";
import type { Group, Moment } from "../lib/types";

const DWELL = 2800;

export function Hero() {
  const { world } = useStore();
  const data = useAsync(() => (world ? api.replay(HERO_SHIPMENT, world.now) : null), [world?.now]);

  return (
    <section id="top" className="grain relative isolate min-h-[100svh] overflow-hidden pt-28 md:pt-32 lg:pt-20">
      <Contours />
      <div className="shell relative">
        {data.data ? (
          <Story moments={data.data.moments} labels={[...data.data.checkpoints.map((c) => c.label), "Today"]} />
        ) : data.error ? (
          <ErrorNote error={data.error} onRetry={data.retry} className="mt-10" />
        ) : (
          <HeroSkeleton />
        )}
      </div>
    </section>
  );
}

function Story({ moments, labels }: { moments: Moment[]; labels: string[] }) {
  const reduce = useReducedMotion();
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(!reduce);
  const stage = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const inView = useInView(stage, { margin: "-20% 0px" });
  const last = moments.length - 1;

  // Auto-play the replay once it is on screen; stop at "Today".
  useEffect(() => {
    if (!playing || !inView) return;
    if (i >= last) return setPlaying(false);
    const t = setTimeout(() => setI((v) => v + 1), i === 0 ? DWELL + 600 : DWELL);
    return () => clearTimeout(t);
  }, [playing, inView, i, last]);

  const v = moments[i].ops;
  const now = moments[last].ops;
  const hubLate = now.timeline.find((t) => t.event === "ARRIVE_TS");
  const hubHours = hubLate?.observed ? (new Date(hubLate.observed).getTime() - new Date(hubLate.planned).getTime()) / 36e5 : 0;
  const yMax = Math.max(...moments.map((m) => m.ops.delay_hours.p90));
  const ghosts = useMemo(() => moments.slice(0, i).map((m) => m.ops), [moments, i]);

  const go = (n: number, focus = false) => {
    const k = Math.max(0, Math.min(last, n));
    setPlaying(false);
    setI(k);
    if (focus) tabs.current[k]?.focus();
  };

  return (
    <>
      {/* Headline: the real story of one shipment, in two lines. */}
      <div className="grid gap-8 lg:grid-cols-12">
        <div className="lg:col-span-9">
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, delay: 0.2 }}
            className="eyebrow mb-6 flex flex-wrap items-center gap-x-3 gap-y-1"
          >
            <span className="text-fg">{v.shipment_id}</span>
            <span className="h-px w-6 bg-line-2" aria-hidden />
            <span className="min-w-0">{[v.shipment.origin, v.shipment.hub, v.shipment.dest].filter(Boolean).map(port).join(" → ")}</span>
          </motion.p>
          <h1 className="font-display text-[clamp(2.9rem,calc(7.1*var(--cw)),6.75rem)] md:whitespace-nowrap font-extrabold uppercase leading-[0.86] tracking-[-0.015em]">
            {[
              <>
                {Math.round(hubHours)} hours late <span className="text-fg-3">at the hub.</span>
              </>,
              <>
                <span className="text-late">{(now.delay_hours.p50 / 24).toFixed(0)} days late</span>{" "}
                <span className="text-fg-3">at the door.</span>
              </>,
            ].map((l, k) => (
              <span key={k} className="block overflow-hidden pb-[0.05em]">
                <motion.span
                  className="block"
                  initial={{ y: "108%" }}
                  animate={{ y: "0%" }}
                  transition={{ duration: 1.2, ease: EASE, delay: 0.15 + k * 0.12 }}
                >
                  {l}
                </motion.span>
              </span>
            ))}
          </h1>
        </div>
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, ease: EASE, delay: 0.7 }}
          className="max-w-sm self-end text-[1.2rem] leading-relaxed text-fg-2 lg:col-span-3"
        >
          Delays spread from stage to stage. CASCADE sees it coming, names the stage to blame and suggests the fix.
        </motion.p>
      </div>

      {/* Replay */}
      <motion.div
        ref={stage}
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1.2, ease: EASE, delay: 0.55 }}
        className="mt-12 border-t border-line pt-8 md:mt-14"
      >
        <HowTo id="top" className="mb-8" />
        <Readout m={moments[i]} />

        <ChartLegend />
        <div className="mt-2">
          <CascadeChart view={v} ghosts={ghosts} yMax={yMax} height={430} />
        </div>

        {/* Scrubber */}
        <div className="mt-4 flex items-stretch gap-3 md:gap-5">
          <button
            onClick={() => (i >= last ? (setI(0), setPlaying(true)) : setPlaying((p) => !p))}
            className="grid size-12 shrink-0 place-items-center rounded-full border border-line-2 text-fg transition-colors hover:border-fg hover:bg-fg hover:text-bg"
            aria-label={playing ? "Pause replay" : "Play replay"}
          >
            {playing ? <Pause size={18} /> : <Play size={18} className="translate-x-px" />}
          </button>
          <div
            role="tablist"
            aria-label="Replay milestones"
            className="relative grid flex-1"
            style={{ gridTemplateColumns: `repeat(${moments.length}, minmax(0,1fr))` }}
            onKeyDown={(e) => {
              const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: last }[e.key];
              if (to === undefined) return;
              e.preventDefault();
              go(to, true);
            }}
          >
            <div className="absolute inset-x-0 top-0 h-px bg-line-2" />
            <motion.div
              className="absolute left-0 top-0 h-[3px] -translate-y-px bg-late"
              initial={false}
              animate={{ width: `${((i + 1) / moments.length) * 100}%` }}
              transition={{ duration: 0.9, ease: EASE }}
            />
            {moments.map((m, k) => (
              <button
                key={k}
                ref={(el) => {
                  tabs.current[k] = el;
                }}
                role="tab"
                aria-selected={k === i}
                aria-controls="hero-readout"
                tabIndex={k === i ? 0 : -1}
                onClick={() => go(k)}
                className={`group pt-4 text-left transition-colors ${k === i ? "text-fg" : k < i ? "text-fg-2" : "text-fg-3 hover:text-fg-2"}`}
              >
                <span className="block font-mono text-[0.75rem] uppercase tracking-[0.16em]">
                  {k === last ? "Today" : day(m.ops.as_of)}
                </span>
                <span className="mt-1 block font-display text-[1.35rem] font-bold uppercase leading-none md:text-[1.6rem]">
                  {k === last ? "Now" : checkpointLabel(labels[k])}
                </span>
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      <Proof />

      <a
        href="#fleet"
        className="mx-auto mt-16 flex w-fit items-center gap-2 pb-10 font-mono text-xs uppercase tracking-[0.2em] text-fg-3 transition-colors hover:text-fg"
      >
        The whole fleet <ArrowDown size={14} className="animate-bounce" />
      </a>
    </>
  );
}

/** Live numbers for the selected replay moment. */
function Readout({ m }: { m: Moment }) {
  const v = m.ops;
  const cause = v.root_cause_group ? GROUP[v.root_cause_group as Group] : "—";
  return (
    <div id="hero-readout" role="tabpanel" className="grid grid-cols-2 gap-x-6 gap-y-8 lg:grid-cols-12">
      <div className="lg:col-span-3">
        <p className="eyebrow">Expected delay</p>
        <div className="mt-3 flex items-baseline gap-2 text-late">
          <span className="num text-[clamp(3.5rem,calc(6*var(--cw)),5.5rem)]">
            <Ticker value={v.delay_hours.p50 / 24} format={(x) => signed(x, 1)} duration={0.9} />
          </span>
          <span className="font-display text-2xl font-bold uppercase">days</span>
        </div>
      </div>
      <div className="lg:col-span-2">
        <p className="eyebrow">Chance late</p>
        <div className="num mt-3 text-[clamp(3.5rem,calc(6*var(--cw)),5.5rem)]">
          <Ticker value={v.p_late * 100} format={(x) => `${Math.min(99, Math.round(x))}%`} duration={0.9} />
        </div>
      </div>
      <div className="lg:col-span-3">
        <p className="eyebrow">Arrives</p>
        <AnimatePresence mode="wait">
          <motion.div
            key={v.eta.p50}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.4, ease: EASE }}
            className="num mt-3 text-[clamp(3.5rem,calc(6*var(--cw)),5.5rem)] uppercase"
          >
            {day(v.eta.p50)}
          </motion.div>
        </AnimatePresence>
        <p className="mt-2 font-mono text-xs text-fg-3">Planned {day(v.planned_delivery)}</p>
      </div>
      <div className="col-span-2 lg:col-span-4">
        <p className="eyebrow">Why</p>
        <AnimatePresence mode="wait">
          <motion.div
            key={v.as_of}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.45, ease: EASE }}
          >
            <p className="mt-3 font-display text-[1.9rem] font-bold uppercase leading-none text-late">{cause}</p>
            <p className="mt-3 text-[1.05rem] leading-snug text-fg-2">{m.customer}</p>
            <p className="mt-2 font-mono text-xs text-fg-3">As of {dayLong(v.as_of)}</p>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

/** Four numbers that earn trust, straight from the evaluation. */
function Proof() {
  const data = useAsync(() => api.model(), []);
  const m = data.data?.metrics;
  const items = m
    ? [
        { v: m.mae_improvement_vs_B1 * 100, f: (x: number) => `${Math.round(x)}%`, l: "smaller error than “same delay as now”" },
        { v: m.coverage_p10_p90_overall * 100, f: (x: number) => `${Math.round(x)}%`, l: "of likely ranges held (target 80%)" },
        { v: m.promise_hit_rate * 100, f: (x: number) => `${Math.round(x)}%`, l: "of customer dates kept" },
        { v: m.latency_p95_ms, f: (x: number) => `${x.toFixed(1)} ms`, l: "to answer, start to finish" },
      ]
    : [];
  return (
    <div className="mt-20 grid grid-cols-2 border-t border-line md:grid-cols-4" aria-label="Model results">
      {items.map((it, k) => (
        <motion.div
          key={k}
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.9, ease: EASE, delay: k * 0.08 }}
          className={`py-8 pr-4 ${k > 0 ? "md:border-l md:border-line md:pl-6" : ""} ${k % 2 === 1 ? "border-l border-line pl-4 md:pl-6" : ""}`}
        >
          <div className="num text-[clamp(2.6rem,calc(4.6*var(--cw)),4.2rem)]">
            <Ticker value={it.v} format={it.f} />
          </div>
          <p className="mt-2 max-w-[16rem] text-[0.98rem] text-fg-2">{it.l}</p>
        </motion.div>
      ))}
      {/* Same cells as the loaded state, so the row doesn't grow (and push the page) when the numbers arrive. */}
      {!m &&
        !data.error &&
        [0, 1, 2, 3].map((k) => (
          <div key={k} className={`py-8 pr-4 ${k > 0 ? "md:border-l md:border-line md:pl-6" : ""} ${k % 2 === 1 ? "border-l border-line pl-4 md:pl-6" : ""}`} aria-hidden>
            <Skeleton className="h-[clamp(2.6rem,calc(4.6*var(--cw)),4.2rem)] w-24" />
            <Skeleton className="mt-2 h-[3.1rem] w-full max-w-[16rem]" />
          </div>
        ))}
    </div>
  );
}

function HeroSkeleton() {
  return (
    <div className="space-y-8">
      <Skeleton className="h-6 w-64" />
      <Skeleton className="h-40 w-full max-w-4xl" />
      <Skeleton className="mt-16 h-[430px] w-full" />
    </div>
  );
}
