import { animate, motion, useInView, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { AlertTriangle, CircleCheck, Clock3 } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { TIER } from "../lib/format";
import type { Tier } from "../lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Number that rolls to its new value (counts on first view, then tweens on change). */
export function Ticker({
  value,
  format = (v) => v.toFixed(0),
  duration = 1.1,
  className,
}: {
  value: number;
  format?: (v: number) => string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-10% 0px" });
  const reduce = useReducedMotion();
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => format(v));
  useEffect(() => {
    if (!inView) return;
    if (reduce) return mv.set(value);
    const c = animate(mv, value, { duration, ease: EASE });
    return () => c.stop();
  }, [value, inView, reduce, duration, mv]);
  return (
    <motion.span ref={ref} className={className} aria-label={format(value)}>
      {text}
    </motion.span>
  );
}

/** Fade-and-rise when scrolled into view. */
export function Reveal({
  children,
  delay = 0,
  className,
  y = 28,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  y?: number;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-8% 0px" }}
      transition={{ duration: 0.9, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

/** Headline whose lines slide up from behind a mask. */
export function MaskLines({
  lines,
  className,
  delay = 0,
  as: Tag = "h2",
}: {
  lines: ReactNode[];
  className?: string;
  delay?: number;
  as?: "h1" | "h2";
}) {
  return (
    <Tag className={className}>
      {lines.map((l, i) => (
        <span key={i} className="block overflow-hidden pb-[0.06em]">
          <motion.span
            className="block"
            initial={{ y: "105%" }}
            whileInView={{ y: "0%" }}
            viewport={{ once: true }}
            transition={{ duration: 1.1, ease: EASE, delay: delay + i * 0.09 }}
          >
            {l}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}

const TIER_ICON = { ON_TRACK: CircleCheck, AT_RISK: Clock3, LATE: AlertTriangle };

export function TierBadge({ tier, size = "md" }: { tier: Tier; size?: "sm" | "md" }) {
  const t = TIER[tier];
  const Icon = TIER_ICON[tier];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[4px] font-mono uppercase tracking-wider ${
        size === "sm" ? "px-1.5 py-0.5 text-[0.7rem]" : "px-2.5 py-1 text-[0.78rem]"
      }`}
      style={{ color: t.ink, background: t.wash }}
    >
      <Icon size={size === "sm" ? 12 : 14} strokeWidth={2.2} aria-hidden />
      {t.label}
    </span>
  );
}

/** Likely range (P10–P90) as a bar with the expected value (P50) as a tick, on a shared scale. */
export function RangeStrip({
  p10,
  p50,
  p90,
  min,
  max,
  tier,
}: {
  p10: number;
  p50: number;
  p90: number;
  min: number;
  max: number;
  tier: Tier;
}) {
  const x = (v: number) => `${((Math.min(Math.max(v, min), max) - min) / (max - min)) * 100}%`;
  const color = TIER[tier].color;
  return (
    <div className="relative h-5 w-full" aria-hidden>
      <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
      <div className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-line-2" style={{ left: x(0) }} />
      <motion.div
        className="absolute top-1/2 h-[6px] -translate-y-1/2 rounded-full"
        style={{ background: `color-mix(in oklab, ${color} 38%, transparent)` }}
        initial={false}
        animate={{ left: x(p10), width: `calc(${x(p90)} - ${x(p10)})` }}
        transition={{ duration: 0.7, ease: EASE }}
      />
      <motion.div
        className="absolute top-1/2 h-3.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ background: color }}
        initial={false}
        animate={{ left: x(p50) }}
        transition={{ duration: 0.7, ease: EASE }}
      />
    </div>
  );
}

export function SectionHead({
  id,
  index,
  kicker,
  title,
  aside,
}: {
  id: string;
  index: string;
  kicker: string;
  title: ReactNode[];
  aside?: ReactNode;
}) {
  return (
    <header className="grid gap-6 pb-10 pt-24 md:grid-cols-12 md:pt-32" id={`${id}-head`}>
      <div className="md:col-span-8">
        <p className="eyebrow mb-5 flex items-center gap-3">
          <span className="text-late">{index}</span>
          <span className="h-px w-8 bg-line-2" />
          {kicker}
        </p>
        <MaskLines lines={title} className="h-section" />
      </div>
      {aside && <div className="self-end text-lg text-fg-2 md:col-span-4">{aside}</div>}
    </header>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-[4px] bg-bg-3 ${className}`} />;
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <p role="alert" className="font-mono text-sm text-late">
      Could not load data · {error.message}
    </p>
  );
}

/** Small labelled figure: big number over a short label. */
export function Stat({
  value,
  label,
  className = "",
  tone,
}: {
  value: ReactNode;
  label: ReactNode;
  className?: string;
  tone?: string;
}) {
  return (
    <div className={className}>
      <div className="num text-[clamp(2.5rem,4.4vw,4rem)]" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      <div className="mt-2 text-[0.95rem] text-fg-2">{label}</div>
    </div>
  );
}
